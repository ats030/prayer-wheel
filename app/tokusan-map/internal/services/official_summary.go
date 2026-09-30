package services

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// officialSummarySections are the detail-panel sections that official-source items
// carry an LLM-structured summary for. They are produced off-line by
// official-warm and served by the handler; the warm tool, the cache, and the
// handler must agree on this set.
var officialSummarySections = []string{"history", "production"}

// officialSummaryValue is one item's stored summary: section key to content.
type officialSummaryValue struct {
	Sections map[string]SectionContent `json:"sections"`
}

// OfficialSummaryCache holds the pre-computed LLM sections for official-source
// items, persisted to data/official_summaries.json (separate from the Wikipedia
// summaries.json on purpose: a different key space and warm tool). It is keyed
// by qid, which is stable across catalogue edits, so a warm run stays valid on
// the Cloud Run deployment where the LLM is disabled.
type OfficialSummaryCache struct {
	mu      sync.Mutex
	flushMu sync.Mutex
	path    string
	byQID   map[string]officialSummaryValue
}

func officialSummaryPath() string {
	if v := os.Getenv("OFFICIAL_SUMMARY_PATH"); v != "" {
		return v
	}
	return "data/official_summaries.json"
}

var officialSummaryCache = newOfficialSummaryCache(officialSummaryPath())

func newOfficialSummaryCache(path string) *OfficialSummaryCache {
	c := &OfficialSummaryCache{path: path, byQID: map[string]officialSummaryValue{}}
	c.load()
	return c
}

// hasOfficialSummary reports whether item qid already has a stored summary for
// section.
func (c *OfficialSummaryCache) hasOfficialSummary(qid, section string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	v, ok := c.byQID[qid]
	if !ok {
		return false
	}
	_, ok = v.Sections[section]
	return ok
}

func (c *OfficialSummaryCache) Get(qid, section string) (SectionContent, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	v, ok := c.byQID[qid]
	if !ok {
		return SectionContent{}, false
	}
	s, ok := v.Sections[section]
	if !ok {
		return SectionContent{}, false
	}
	s = sanitizeSectionContent(s)
	return s, true
}

func (c *OfficialSummaryCache) Put(qid, section string, content SectionContent) {
	c.mu.Lock()
	v, ok := c.byQID[qid]
	if !ok {
		v = officialSummaryValue{Sections: map[string]SectionContent{}}
	}
	v.Sections[section] = content
	c.byQID[qid] = v
	c.mu.Unlock()
}

// load reads the backing file. A missing or malformed file yields an empty
// cache rather than an error: official items fall back to their raw text.
func (c *OfficialSummaryCache) load() {
	data, err := os.ReadFile(c.path)
	if err != nil {
		return
	}
	var raw map[string]officialSummaryValue
	if err := json.Unmarshal(data, &raw); err != nil {
		return
	}
	for qid, v := range raw {
		v = officialSummaryValue{Sections: map[string]SectionContent{}}
		for k, s := range raw[qid].Sections {
			v.Sections[k] = s
		}
		c.byQID[qid] = v
	}
}

// flush atomically rewrites the backing file to make a partial warm run
// resumable.
func (c *OfficialSummaryCache) flush() {
	c.flushMu.Lock()
	defer c.flushMu.Unlock()
	c.mu.Lock()
	data, err := json.Marshal(c.byQID)
	c.mu.Unlock()
	if err != nil {
		return
	}
	if err := os.MkdirAll(filepath.Dir(c.path), 0o755); err != nil {
		return
	}
	tmp := c.path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return
	}
	_ = os.Rename(tmp, c.path)
}

// SummarizeOfficialSection asks the local LLM to structure sourceText into a
// SectionContent for the official-source section key (history / production),
// using the same labels and instructions as the Wikipedia path, then stores it
// in the official summary cache (flushed immediately so a warm run resumes
// safely). An empty sourceText stores SummaryNone so the item is not retried:
// the official item genuinely has no text for that section.
func SummarizeOfficialSection(ctx context.Context, qid, section, sourceText string) (SectionContent, error) {
	specs := OfficialSectionSpecs()
	spec, ok := specs[section]
	if !ok {
		return SectionContent{}, fmt.Errorf("unknown official section %q", section)
	}
	if strings.TrimSpace(sourceText) == "" {
		content := SectionContent{Summary: SummaryNone, Items: []SectionItem{}}
		putOfficialSummary(qid, section, content)
		return content, nil
	}
	content, err := generateSectionContent(ctx, spec.Label, spec.Instruction, sourceText)
	if err != nil {
		return SectionContent{}, err
	}
	content = sanitizeSectionContent(content)
	trimSectionItems(&content)
	putOfficialSummary(qid, section, content)
	return content, nil
}

// GetOfficialSummary returns the stored structured summary for one
// official-source item and section, or false when the item has none (the
// caller shows its raw text instead).
func GetOfficialSummary(qid, section string) (SectionContent, bool) {
	return officialSummaryCache.Get(qid, section)
}

// HasOfficialSummary reports whether item qid already has a stored summary for
// section.
func HasOfficialSummary(qid, section string) bool {
	return officialSummaryCache.hasOfficialSummary(qid, section)
}

func putOfficialSummary(qid, section string, content SectionContent) {
	officialSummaryCache.Put(qid, section, content)
	officialSummaryCache.flush()
}
