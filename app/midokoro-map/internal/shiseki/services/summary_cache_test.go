package services

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func useTempSummaryCache(t *testing.T, max int) {
	t.Helper()
	dir := t.TempDir()
	cache := newSummaryCache(filepath.Join(dir, "summaries.json"), max)
	orig := summaryCache
	summaryCache = cache
	t.Cleanup(func() { summaryCache = orig })
}

func TestSummaryCachePutGetAndLRUEviction(t *testing.T) {
	useTempSummaryCache(t, 2)

	summaryCache.Put("a", "要約A")
	summaryCache.Put("b", "要約B")
	summaryCache.Put("c", "要約C") // evicts "a" if "b" was touched last

	summaryCache.Put("d", "要約D") // evicts "b"

	if got, ok := summaryCache.Get("c"); !ok || got != "要約C" {
		t.Errorf("c = %q, %v", got, ok)
	}
	if got, ok := summaryCache.Get("d"); !ok || got != "要約D" {
		t.Errorf("d = %q, %v", got, ok)
	}
	if _, ok := summaryCache.Get("a"); ok {
		t.Error("a should have been evicted")
	}
	if _, ok := summaryCache.Get("b"); ok {
		t.Error("b should have been evicted")
	}
}

func TestSummaryCachePersistsAndReloads(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "sub", "summaries.json")

	orig := summaryCache
	cache1 := newSummaryCache(path, 10)
	summaryCache = cache1
	cache1.Put("k1", "要約1")
	cache1.Put("k2", "要約2")
	cache1.flush()
	summaryCache = orig

	// A new instance at the same path must recover both entries.
	summaryCache = newSummaryCache(path, 10)
	defer func() { summaryCache = orig }()
	if got, ok := summaryCache.Get("k1"); !ok || got != "要約1" {
		t.Errorf("k1 = %q, %v after reload", got, ok)
	}
}

func TestSummaryDisabledHonoursEnv(t *testing.T) {
	useTempSummaryCache(t, 4)
	cases := []struct {
		value string
		want  bool
	}{
		{"", false},
		{"0", false},
		{"1", true},
		{"true", true},
		{"yes", true},
		{"on", true},
		{"OFF", false},
	}
	for _, tc := range cases {
		t.Setenv("SHISEKI_SUMMARY_DISABLE", tc.value)
		if got := SummaryDisabled(); got != tc.want {
			t.Errorf("SHISEKI_SUMMARY_DISABLE=%q: SummaryDisabled() = %v, want %v", tc.value, got, tc.want)
		}
	}
}

// fakeOllama stands up an in-memory /api/chat endpoint that records the number
// of requests it receives. Two kinds of calls are distinguished by their system
// prompt (the heading-resolution pass vs. the per-section summary pass), so
// tests can set headingBody / summaryBody independently; status / headingStatus
// let tests exercise the failure fallbacks.
type fakeOllama struct {
	srv           *httptest.Server
	calls         int
	summaryBody   string
	headingBody   string
	status        int
	headingStatus int
	lastBody      string
}

// respond writes the standard Ollama /api/chat envelope with content JSON-encoded
// as a string field. For the heading-resolution pass, content is a JSON-object
// literal; the production parser extracts the first {...} block either way. A
// non-200 status writes a failure body instead.
func (f *fakeOllama) respond(w http.ResponseWriter, content string, status int) {
	f.calls++
	w.Header().Set("Content-Type", "application/json")
	if status != http.StatusOK {
		w.WriteHeader(status)
		w.Write([]byte(`{}`))
		return
	}
	env := struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	}{}
	env.Message.Content = content
	b, err := json.Marshal(env)
	if err != nil {
		http.Error(w, "marshal", http.StatusInternalServerError)
		return
	}
	w.Write(b)
}

func (f *fakeOllama) Handler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		f.lastBody = string(raw)
		var req struct {
			Messages []struct {
				Role    string `json:"role"`
				Content string `json:"content"`
			} `json:"messages"`
		}
		_ = json.Unmarshal(raw, &req)

		// The heading-resolution pass carries the headingPromptSystem system
		// prompt (unlike the summary path); use it to tell the two apart.
		isHeading := false
		for _, m := range req.Messages {
			if m.Role == "system" && strings.Contains(m.Content, "指定されたセクションへ見出しを割り当て") {
				isHeading = true
				break
			}
		}
		if isHeading {
			f.respond(w, f.headingBody, f.headingStatus)
		} else {
			f.respond(w, f.summaryBody, f.status)
		}
	}
}

func newFakeOllama(t *testing.T, body string) *fakeOllama {
	t.Helper()
	f := &fakeOllama{
		summaryBody:   body,
		headingBody:   `{}`,
		status:        http.StatusOK,
		headingStatus: http.StatusOK,
	}
	f.srv = httptest.NewServer(f.Handler())
	t.Cleanup(f.srv.Close)
	return f
}

func withFakeOllama(t *testing.T, f *fakeOllama) {
	t.Helper()
	orig := OllamaBaseURL
	OllamaBaseURL = f.srv.URL
	t.Cleanup(func() { OllamaBaseURL = orig })
}

// Cloud Run runs with SHISEKI_SUMMARY_DISABLE=1 and serves only what
// cmd/summary-warm baked into data/shiseki/summaries.json, so the disabled path must
// still read both the cached heading map and the cached section summary.
func TestDisabledPathServesWarmedSummaries(t *testing.T) {
	useTempSummaryCache(t, 10)
	t.Setenv("SHISEKI_SUMMARY_DISABLE", "1")
	title := "テスト遺跡"
	fullText := "冒頭\n発掘の経緯\n縄文時代に集落が営まれた。\n"
	headings := []wikipediaHeading{{Line: "発掘の経緯", Level: 2}}
	mapping, _ := json.Marshal(map[string]string{"history": "発掘の経緯"})
	summaryCache.Put(headingMapCacheKey(title, []string{"発掘の経緯"}), string(mapping))
	summaryCache.Put(summaryCacheKey(title, sectionSpecs[0].label, fullText), "縄文集落の要約")

	headingMap := resolveSectionHeadings(context.Background(), title, headings)
	if headingMap["history"] != "発掘の経緯" {
		t.Fatalf("cached heading map ignored when disabled: %v", headingMap)
	}
	got := resolvePanelSection(context.Background(), title, fullText, headings, "src", sectionSpecs[0], headingMap)
	if got.Summary != "縄文集落の要約" {
		t.Fatalf("cached summary ignored when disabled: %+v", got)
	}
}

// The self-hosted server and cmd/summary-warm each hold their own copy of the
// same file; a flush from one must not drop what the other already wrote.
func TestSummaryCacheFlushMergesOtherWriters(t *testing.T) {
	path := filepath.Join(t.TempDir(), "summaries.json")
	server := newSummaryCache(path, 10)
	warm := newSummaryCache(path, 10)
	warm.Put("warmed", "要約W")
	warm.flush()
	server.Put("served", "要約S")
	server.flush()

	reloaded := newSummaryCache(path, 10)
	for key, want := range map[string]string{"warmed": "要約W", "served": "要約S"} {
		if got, ok := reloaded.Get(key); !ok || got != want {
			t.Errorf("%s = %q, %v; want %q", key, got, ok, want)
		}
	}
	if got, ok := server.Get("warmed"); !ok || got != "要約W" {
		t.Errorf("server did not pick up the warmed entry: %q, %v", got, ok)
	}
}
