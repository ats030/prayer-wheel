package services

import (
	"container/list"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"midokoro-map/internal/shared"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// SummaryCache is a small LRU of LLM-generated section summaries, persisted to
// data/shiseki/summaries.json so repeated detail-panel opens do not pay the
// generation cost again. The key embeds the article's full text, so any edit
// to the Wikipedia article automatically yields a different key and the stale
// summary simply stops being found.
type SummaryCache struct {
	mu    sync.Mutex
	path  string
	max   int
	order *list.List               // keys in recency order, most recent at back
	byKey map[string]*list.Element // key -> element holding a summaryEntry
}

type summaryEntry struct {
	key, summary string
}

// The cap must hold every warmed summary: cmd/summary-warm fills this file for
// the whole catalogue (about 20k articles, up to five entries each) and Cloud
// Run serves it read-only, so eviction would silently drop shipped summaries.
var summaryCache = newSummaryCache(shared.DataPath("shiseki", "summaries.json"), 200000)

func newSummaryCache(path string, max int) *SummaryCache {
	c := &SummaryCache{path: path, max: max, order: list.New(), byKey: map[string]*list.Element{}}
	c.load()
	return c
}

// summaryCacheKey is stable for a given (article, section, revision) triple.
func summaryCacheKey(title, sectionLabel, fullText string) string {
	h := sha256.Sum256([]byte(title + "|" + sectionLabel + "|" + fullText))
	return hex.EncodeToString(h[:])
}

// headingMapCacheKey is stable for a given (article, heading-snapshot) pair.
// The LLM heading-resolution result is cheap to compute once per article
// revision, so we cache it keyed on the sorted snapshot of headings rather
// than the full text. Any revision that adds, removes, or renames a heading
// changes the snapshot and the stale map simply stops being found.
func headingMapCacheKey(title string, headings []string) string {
	sorted := make([]string, len(headings))
	copy(sorted, headings)
	sort.Strings(sorted)
	combined := strings.Join(sorted, "\n")
	h := sha256.Sum256([]byte("headingmap|" + title + "|" + combined))
	return hex.EncodeToString(h[:])
}

func (c *SummaryCache) Get(key string) (string, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.byKey[key]
	if !ok {
		return "", false
	}
	c.order.MoveToBack(e)
	return e.Value.(*summaryEntry).summary, true
}

func (c *SummaryCache) Put(key, summary string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.putLocked(key, summary)
}

// putLocked stores key as the most recent entry and evicts beyond the cap.
// Caller holds the mutex.
func (c *SummaryCache) putLocked(key, summary string) {
	if e, ok := c.byKey[key]; ok {
		e.Value.(*summaryEntry).summary = summary
		c.order.MoveToBack(e)
	} else {
		c.byKey[key] = c.order.PushBack(&summaryEntry{key: key, summary: summary})
	}
	for c.order.Len() > c.max {
		oldest := c.order.Front()
		c.order.Remove(oldest)
		delete(c.byKey, oldest.Value.(*summaryEntry).key)
	}
}

func (c *SummaryCache) readFile() map[string]string {
	data, err := os.ReadFile(c.path)
	if err != nil {
		return nil
	}
	var raw map[string]string
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil
	}
	return raw
}

func (c *SummaryCache) load() {
	raw := c.readFile()
	keys := make([]string, 0, len(raw))
	for k := range raw {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		c.putLocked(k, raw[k])
	}
}

// flush atomically rewrites the backing file. Small enough to run after every
// Put; at most one JSON write per panel open. The self-hosted server and
// cmd/summary-warm share this file, so entries another process wrote since
// load are merged in (in-memory values win) rather than overwritten, and each
// write goes through its own temp file.
func (c *SummaryCache) flush() {
	onDisk := c.readFile()
	c.mu.Lock()
	for k, v := range onDisk {
		if _, ok := c.byKey[k]; !ok {
			c.putLocked(k, v)
		}
	}
	out := make(map[string]string, c.order.Len())
	for e := c.order.Front(); e != nil; e = e.Next() {
		entry := e.Value.(*summaryEntry)
		out[entry.key] = entry.summary
	}
	c.mu.Unlock()
	data, err := json.Marshal(out)
	if err != nil {
		return
	}
	if err := os.MkdirAll(filepath.Dir(c.path), 0o755); err != nil {
		return
	}
	tmp, err := os.CreateTemp(filepath.Dir(c.path), filepath.Base(c.path)+".tmp*")
	if err != nil {
		return
	}
	_, werr := tmp.Write(data)
	cerr := tmp.Close()
	if werr != nil || cerr != nil || os.Chmod(tmp.Name(), 0o644) != nil {
		os.Remove(tmp.Name())
		return
	}
	if err := os.Rename(tmp.Name(), c.path); err != nil {
		os.Remove(tmp.Name())
	}
}

// SummaryDisabled reports whether the LLM/summary pipeline must be bypassed
// (e.g. a Cloud Run deployment with no local Ollama). When true, sections are
// rendered from their raw blocks only.
func SummaryDisabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("SHISEKI_SUMMARY_DISABLE"))) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

func lookupSummary(key string) (string, bool) {
	return summaryCache.Get(key)
}

func saveSummary(key, summary string) {
	summaryCache.Put(key, summary)
	summaryCache.flush()
}
