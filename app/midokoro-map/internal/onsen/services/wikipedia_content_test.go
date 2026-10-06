package services

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func withWikipediaBase(t *testing.T, s *httptest.Server) {
	t.Helper()
	orig := wikipediaAPIBase
	origBackoff := initialBackoff
	wikipediaAPIBase = s.URL
	initialBackoff = time.Millisecond
	t.Cleanup(func() {
		wikipediaAPIBase = orig
		initialBackoff = origBackoff
	})
}

func TestParseWikipediaContent(t *testing.T) {
	body := []byte(`{"query":{"pages":[{"title":"長崎くんち","extract":"祭りの概要です。","pageprops":{"wikibase_item":"Q114712"},"thumbnail":{"source":"https://upload.wikimedia.org/x.jpg"}}]}}`)
	got, err := parseWikipediaContent(body, "Q114712")
	if err != nil {
		t.Fatal(err)
	}
	if got.Description != "祭りの概要です。" {
		t.Fatalf("description = %q", got.Description)
	}
	if got.SourceURL != "https://ja.wikipedia.org/wiki/%E9%95%B7%E5%B4%8E%E3%81%8F%E3%82%93%E3%81%A1" {
		t.Fatalf("source URL = %q", got.SourceURL)
	}
}

func TestParseWikipediaContentRejectsMissingExtract(t *testing.T) {
	if _, err := parseWikipediaContent([]byte(`{"query":{"pages":[{"title":"不明","missing":true}]}}`), "Q1"); err == nil {
		t.Fatal("expected missing content error")
	}
}

func TestParseWikipediaContentRejectsDifferentWikidataItem(t *testing.T) {
	body := []byte(`{"query":{"pages":[{"title":"同名記事","extract":"別の記事です。","pageprops":{"wikibase_item":"Q2"}}]}}`)
	if _, err := parseWikipediaContent(body, "Q1"); err == nil {
		t.Fatal("expected Wikidata identity mismatch error")
	}
}

func TestUsableArticleImageTitlesSkipsInterfaceArtwork(t *testing.T) {
	got := usableArticleImageTitles([]string{
		"ファイル:Commons-logo.svg",
		"ファイル:Camera-photo Upload.svg",
		"ファイル:Sirotoriodori.jpg",
		"ファイル:白鳥おどり発祥の碑.jpg",
	})
	if len(got) != 2 || got[0] != "ファイル:Sirotoriodori.jpg" || got[1] != "ファイル:白鳥おどり発祥の碑.jpg" {
		t.Fatalf("unexpected candidates: %#v", got)
	}
}

func TestMatchSectionHeading_OnsenNewCandidates(t *testing.T) {
	headings := []wikipediaHeading{
		{Line: "温泉街", Level: 2},
		{Line: "名所・旧跡", Level: 2},
		{Line: "文化財", Level: 3},
		{Line: "由来", Level: 3},
		{Line: "年表", Level: 2},
	}
	if got := matchSectionHeading(headings, sectionSpecs[4].candidates); got == nil || got.Line != "温泉街" {
		t.Errorf("tourism heading = %+v, want the most specific 温泉街 first", got)
	}
	if got := matchSectionHeading(headings, sectionSpecs[0].candidates); got == nil || got.Line != "由来" {
		t.Errorf("history heading = %+v, want 由来 over 年表 (absent 歴史/沿革/起源)", got)
	}

	noStreet := []wikipediaHeading{
		{Line: "名所・旧跡", Level: 2},
		{Line: "文化財", Level: 3},
	}
	if got := matchSectionHeading(noStreet, sectionSpecs[4].candidates); got == nil || got.Line != "名所・旧跡" {
		t.Errorf("tourism heading = %+v, want 名所・旧跡 over 文化財", got)
	}

	culture := []wikipediaHeading{{Line: "文化財", Level: 3}}
	if got := matchSectionHeading(culture, sectionSpecs[4].candidates); got == nil || got.Line != "文化財" {
		t.Errorf("tourism heading = %+v, want 文化財", got)
	}
}

func TestFetchWikipediaContent_RetriesOn429ThenSucceeds(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n <= 2 {
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"query":{"pages":[{"title":"長崎くんち","extract":"祭りの概要です。","pageprops":{"wikibase_item":"Q114712"}}]}}`))
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	content, err := FetchWikipediaContent("長崎くんち", "Q114712")
	if err != nil {
		t.Fatalf("expected success after retry, got err: %v", err)
	}
	if content.Description != "祭りの概要です。" {
		t.Errorf("description = %q", content.Description)
	}
	if got := atomic.LoadInt32(&calls); got != 3 {
		t.Errorf("expected 3 calls (2 retries + 1 success), got %d", got)
	}
}

func TestFetchWikipediaContent_StopsRetryingOnNonRetryableError(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	if _, err := FetchWikipediaContent("無い記事", "Q1"); err == nil {
		t.Fatal("expected error for 404, got nil")
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Errorf("404 must not be retried, expected 1 call, got %d", got)
	}
}

func TestFetchWikipediaSectionHeadings_RetriesOn429ThenSucceeds(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n <= 2 {
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"parse":{"sections":[{"line":"歴史","level":"2"},{"line":"交通","level":"2"}]}}`))
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	headings, err := fetchWikipediaSectionHeadings(t.Context(), "草津温泉")
	if err != nil {
		t.Fatalf("expected success after retry, got err: %v", err)
	}
	if len(headings) != 2 || headings[0].Line != "歴史" || headings[0].Level != 2 {
		t.Errorf("unexpected headings: %#v", headings)
	}
	if got := atomic.LoadInt32(&calls); got != 3 {
		t.Errorf("expected 3 calls (2 retries + 1 success), got %d", got)
	}
}

func TestFetchWikipediaSectionHeadings_StopsRetryingOnNonRetryableError(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	if _, err := fetchWikipediaSectionHeadings(t.Context(), "無い記事"); err == nil {
		t.Fatal("expected error for 404, got nil")
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Errorf("404 must not be retried, expected 1 call, got %d", got)
	}
}

func TestFetchWikipediaPlainText_RetriesOn429ThenSucceeds(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n <= 2 {
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"query":{"pages":[{"title":"草津温泉","extract":"歴史 本文です。"}]}}`))
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	text, title, err := fetchWikipediaPlainText(t.Context(), "草津温泉")
	if err != nil {
		t.Fatalf("expected success after retry, got err: %v", err)
	}
	if title != "草津温泉" || text != "歴史 本文です。" {
		t.Errorf("unexpected result: title=%q text=%q", title, text)
	}
	if got := atomic.LoadInt32(&calls); got != 3 {
		t.Errorf("expected 3 calls (2 retries + 1 success), got %d", got)
	}
}

func TestFetchWikipediaPlainText_RetriesExhausted(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, "rate limited", http.StatusTooManyRequests)
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	if _, _, err := fetchWikipediaPlainText(t.Context(), "草津温泉"); err == nil {
		t.Fatal("expected error after retries exhausted")
	}
	if got := atomic.LoadInt32(&calls); got != maxRetries+1 {
		t.Errorf("expected %d calls (initial + %d retries), got %d", maxRetries+1, maxRetries, got)
	}
}

func TestWithRetryRespectsRetryAfterHeader(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n <= 1 {
			w.Header().Set("Retry-After", "7")
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`ok`))
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	got, err := withRetry(t.Context(), "test", func() (string, error) {
		req, _ := http.NewRequestWithContext(t.Context(), http.MethodGet, wikipediaAPIBase+"/w/api.php", nil)
		resp, err := wikipediaClient.Do(req)
		if err != nil {
			return "", err
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			return "", &apiStatusError{status: resp.StatusCode, retryAfter: parseRetryAfter(resp.Header.Get("Retry-After"))}
		}
		return "ok", nil
	})
	if err != nil {
		t.Fatalf("expected success after retry, got err: %v", err)
	}
	if got != "ok" {
		t.Errorf("got %q, want %q", got, "ok")
	}
	if c := atomic.LoadInt32(&calls); c != 2 {
		t.Errorf("expected 2 calls, got %d", c)
	}
}

// Wikimedia throttles anonymous requests that do not follow its User-Agent
// policy much more aggressively (measured: HTTP 429 after 10 requests with a
// bare product token, 70+ with a contact URL), which is what made the
// 歴史 / アクセス sections disappear after a few detail-panel opens.
func TestWikimediaUserAgentCarriesContactInformation(t *testing.T) {
	if !strings.HasPrefix(wikimediaUserAgent, "midokoro-map/") {
		t.Errorf("User-Agent = %q, want the application identity as the product token", wikimediaUserAgent)
	}
	if !strings.Contains(wikimediaUserAgent, "https://") {
		t.Errorf("User-Agent = %q, want contact information required by Wikimedia's User-Agent policy", wikimediaUserAgent)
	}
}

func TestWikipediaRequestsSendCompliantUserAgent(t *testing.T) {
	var got string
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Get("User-Agent")
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"query":{"pages":[{"title":"草津温泉","extract":"概要です。","pageprops":{"wikibase_item":"Q1"}}]}}`))
	}))
	defer s.Close()
	withWikipediaBase(t, s)

	if _, err := FetchWikipediaContent("草津温泉", "Q1"); err != nil {
		t.Fatal(err)
	}
	if got != wikimediaUserAgent {
		t.Errorf("User-Agent = %q, want %q", got, wikimediaUserAgent)
	}
}

func TestIsTransientWikimediaError(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"rate limited", &apiStatusError{status: http.StatusTooManyRequests}, true},
		{"server error", &apiStatusError{status: http.StatusServiceUnavailable}, true},
		{"not found", &apiStatusError{status: http.StatusNotFound}, false},
		{"article missing", errWikipediaArticleContentNotFound, false},
		{"article missing, wrapped", fmt.Errorf("fetching sections: %w", errWikipediaArticleContentNotFound), false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := IsTransientWikimediaError(tc.err); got != tc.want {
				t.Errorf("IsTransientWikimediaError(%v) = %v, want %v", tc.err, got, tc.want)
			}
		})
	}
}

func TestExtractSectionBlocks_GroupsSubsections(t *testing.T) {
	fullText := "歴史\n\n安土桃山時代以前\n\n段落A\n\n安土桃山時代\n\n段落B1\n\n段落B2\n\n現代\n\n段落C"
	headings := []wikipediaHeading{
		{Line: "歴史", Level: 2},
		{Line: "安土桃山時代以前", Level: 3},
		{Line: "安土桃山時代", Level: 3},
		{Line: "現代", Level: 3},
	}
	blocks := extractSectionBlocks(fullText, headings[0], headings)
	if len(blocks) != 3 {
		t.Fatalf("expected 3 blocks, got %d: %#v", len(blocks), blocks)
	}
	if blocks[0].Heading != "安土桃山時代以前" || blocks[0].Text != "段落A" {
		t.Errorf("block 0 = %#v", blocks[0])
	}
	if blocks[1].Heading != "安土桃山時代" || blocks[1].Text != "段落B1\n\n段落B2" {
		t.Errorf("block 1 = %#v", blocks[1])
	}
	if blocks[2].Heading != "現代" || blocks[2].Text != "段落C" {
		t.Errorf("block 2 = %#v", blocks[2])
	}
}

func TestExtractSectionBlocks_LedInSectionLeadIn(t *testing.T) {
	fullText := "沿革\n\n導入段落1\n\n導入段落2\n\n明治時代\n\n段落M"
	headings := []wikipediaHeading{
		{Line: "沿革", Level: 2},
		{Line: "明治時代", Level: 3},
	}
	blocks := extractSectionBlocks(fullText, headings[0], headings)
	if len(blocks) != 2 {
		t.Fatalf("expected 2 blocks, got %d: %#v", len(blocks), blocks)
	}
	if blocks[0].Heading != "" || blocks[0].Text != "導入段落1\n\n導入段落2" {
		t.Errorf("lead-in block = %#v", blocks[0])
	}
	if blocks[1].Heading != "明治時代" || blocks[1].Text != "段落M" {
		t.Errorf("second block = %#v", blocks[1])
	}
}

func TestExtractSectionBlocks_StopsAtSiblingHeading(t *testing.T) {
	fullText := "歴史\n\n段落A\n\n地理\n\n段落B"
	headings := []wikipediaHeading{
		{Line: "歴史", Level: 2},
		{Line: "地理", Level: 2},
	}
	blocks := extractSectionBlocks(fullText, headings[0], headings)
	if len(blocks) != 1 {
		t.Fatalf("expected 1 block, got %d: %#v", len(blocks), blocks)
	}
	if blocks[0].Heading != "" || blocks[0].Text != "段落A" {
		t.Errorf("block 0 = %#v", blocks[0])
	}
}

func TestExtractSectionBlocks_DropsHeadingWithNoParagraph(t *testing.T) {
	fullText := "歴史\n\n近世\n\n明治時代\n\n段落M\n\n近代"
	headings := []wikipediaHeading{
		{Line: "歴史", Level: 2},
		{Line: "近世", Level: 3},
		{Line: "明治時代", Level: 3},
		{Line: "近代", Level: 3},
	}
	blocks := extractSectionBlocks(fullText, headings[0], headings)
	if len(blocks) != 1 {
		t.Fatalf("expected 1 block (heading-only dropped), got %d: %#v", len(blocks), blocks)
	}
	if blocks[0].Heading != "明治時代" || blocks[0].Text != "段落M" {
		t.Errorf("block 0 = %#v", blocks[0])
	}
}

func TestTruncateSectionBlocks_FitsWithinBudget(t *testing.T) {
	blocks := []WikipediaTextBlock{
		{Heading: "鉄道", Text: "1"},
		{Heading: "路線バス", Text: "2222"},
	}
	got := truncateSectionBlocks(blocks)
	if len(got) != 2 {
		t.Fatalf("expected 2 blocks, got %d: %#v", len(got), got)
	}
	if got[0].Heading != "鉄道" || got[0].Text != "1" {
		t.Errorf("block 0 = %#v", got[0])
	}
	if got[1].Heading != "路線バス" || got[1].Text != "2222" {
		t.Errorf("block 1 = %#v", got[1])
	}
}

func TestTruncateSectionBlocks_CutsMidBlock(t *testing.T) {
	long := strings.Repeat("あ", maxSectionChars+5)
	blocks := []WikipediaTextBlock{
		{Heading: "", Text: long},
	}
	got := truncateSectionBlocks(blocks)
	if len(got) != 1 {
		t.Fatalf("expected 1 block, got %d: %#v", len(got), got)
	}
	if !strings.HasSuffix(got[0].Text, "…") {
		t.Errorf("expected trailing ellipsis, got %q", got[0].Text)
	}
	if len([]rune(got[0].Text)) > maxSectionChars {
		t.Errorf("expected budget <= %d, got %d", maxSectionChars, len([]rune(got[0].Text)))
	}
}

func TestTruncateSectionBlocks_DropsLaterBlocks(t *testing.T) {
	blocks := []WikipediaTextBlock{
		{Heading: "", Text: strings.Repeat("あ", maxSectionChars/2)},
		{Heading: "鉄道", Text: strings.Repeat("い", maxSectionChars/2+10)},
	}
	got := truncateSectionBlocks(blocks)
	if len(got) != 2 {
		t.Fatalf("expected 2 blocks, got %d: %#v", len(got), got)
	}
	if !strings.HasSuffix(got[1].Text, "…") {
		t.Errorf("expected trailing ellipsis on last block, got %q", got[1].Text)
	}
}

// ---- FetchPanelSections / resolvePanelSection (history|food|access|tourism) ----

// fakeWikipedia serves both action=parse (sections/headings) and
// action=query (plain-text extract) against wikipediaAPIBase, so a single
// withWikipediaBase(t, s) redirect covers the whole panel pipeline.
func newFakeWikipedia(t *testing.T, headings []wikipediaHeading, extract string) *httptest.Server {
	t.Helper()
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		action := r.URL.Query().Get("action")
		w.Header().Set("Content-Type", "application/json")
		switch action {
		case "parse":
			type sec struct {
				Line  string `json:"line"`
				Level string `json:"level"`
			}
			sections := make([]sec, 0, len(headings))
			for _, h := range headings {
				sections = append(sections, sec{Line: h.Line, Level: strconv.Itoa(h.Level)})
			}
			json.NewEncoder(w).Encode(map[string]any{"parse": map[string]any{"sections": sections}})
		case "query":
			json.NewEncoder(w).Encode(map[string]any{
				"query": map[string]any{
					"pages": []any{map[string]any{
						"title":   "テスト温泉",
						"extract": extract,
					}},
				},
			})
		default:
			http.Error(w, "unexpected action "+action, http.StatusBadRequest)
		}
	}))
	t.Cleanup(s.Close)
	return s
}

func TestFetchPanelSections_SummaryGeneratedAndCached(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{
			{Line: "歴史", Level: 2},
			{Line: "アクセス", Level: 2},
			{Line: "名物", Level: 2},
		},
		"概要\n\n歴史\n\n創業は江戸時代。\n\n名物\n\n地元のそばが名物です。\n\nアクセス\n\n JR東海道本線 草津温泉駅下車、徒歩10分。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `江戸時代創業で、地元に縁ある歴史を持つ。`)
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	hist, food, _, access, tourism, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("did not expect a transient failure")
	}

	// 歴史 has a matching heading -> blocks + summary from the LLM.
	if hist.Summary == "" {
		t.Errorf("history: expected a non-empty summary, got %q", hist.Summary)
	}
	if len(hist.Blocks) == 0 {
		t.Error("history: expected fallback blocks")
	}

	// 名物 matched its heading -> LLM summary too.
	if food.Summary == "" {
		t.Errorf("food: expected a non-empty summary, got %q", food.Summary)
	}

	// アクセス matched but the LLM was asked once per section; it returned the
	// same canned body, so a summary is present here as well.
	if access.Summary == "" {
		t.Errorf("access: expected a non-empty summary, got %q", access.Summary)
	}

	// 周辺 / 近隣 etc. are absent -> tourism has neither summary nor blocks.
	if tourism.Summary != "" || len(tourism.Blocks) != 0 {
		t.Errorf("tourism: expected empty section, got %#v", tourism)
	}

	// 3 matched sections each get a summary from the LLM; tourism has no
	// exact candidate and triggers a heading-resolution LLM call (the fake
	// server returns a non-JSON body, which the parser treats as no-result,
	// leaving tourism empty as before).
	if got := fakeOllama.calls; got != 4 {
		t.Errorf("expected 4 Ollama calls (3 summaries + 1 heading-resolution fallback), got %d", got)
	}

	var sent map[string]any
	if err := json.Unmarshal([]byte(fakeOllama.lastBody), &sent); err != nil {
		t.Fatalf("could not decode recorded Ollama request: %v", err)
	}
	if sent["think"] != false {
		t.Errorf("Ollama request must set think=false so thinking models answer into content; got %v", sent["think"])
	}

	// A second open of the same article must be served entirely from cache:
	// both the heading-resolution map and the three per-section summaries hit
	// the cache, so no additional Ollama round-trips.
	if _, _, _, _, _, _, err := FetchPanelSections(t.Context(), "テスト温泉", ""); err != nil {
		t.Fatal(err)
	}
	if got := fakeOllama.calls; got != 4 {
		t.Errorf("expected cache hit on second call (still %d), got %d", 4, got)
	}
}

func TestFetchPanelSections_HeadingResolutionFallsBackToLLM(t *testing.T) {
	useTempSummaryCache(t, 16)
	// No heading is an exact candidate match for any section; the article
	// carries its tourism content under "周辺の宿", which only the LLM path
	// can map to the tourism section.
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{
			{Line: "泉質", Level: 2},
			{Line: "周辺の宿", Level: 2},
		},
		"概要\n\n泉質\n\n単純泉。\n\n周辺の宿\n\n周辺には温泉旅館が多数建ち並ぶ。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `周辺には温泉旅館が多数建ち並ぶ。`)
	fakeOllama.headingBody = `{
  "history": "",
  "food": "",
  "access": "",
  "tourism": "周辺の宿"
	}`
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	hist, food, _, access, tourism, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("did not expect a transient failure")
	}

	// The LLM mapped 周辺の宿 -> tourism, so this section must carry content.
	if tourism.Summary == "" {
		t.Errorf("tourism: expected LLM summary, got %q", tourism.Summary)
	}
	if len(tourism.Blocks) == 0 {
		t.Error("tourism: expected blocks extracted under 周辺の宿")
	}

	// The other sections have neither an exact candidate nor an LLM mapping.
	if hist.Summary != "" || len(hist.Blocks) != 0 {
		t.Errorf("history: expected empty, got %#v", hist)
	}
	if food.Summary != "" || len(food.Blocks) != 0 {
		t.Errorf("food: expected empty, got %#v", food)
	}
	if access.Summary != "" || len(access.Blocks) != 0 {
		t.Errorf("access: expected empty, got %#v", access)
	}

	// One heading-resolution call + one summary call.
	if got := fakeOllama.calls; got != 2 {
		t.Errorf("expected 2 Ollama calls (1 heading + 1 summary), got %d", got)
	}

	// Second open: heading map and summary both served from cache.
	if _, _, _, _, _, _, err := FetchPanelSections(t.Context(), "テスト温泉", ""); err != nil {
		t.Fatal(err)
	}
	if got := fakeOllama.calls; got != 2 {
		t.Errorf("expected cache hits on second call (still %d), got %d", 2, got)
	}
}

func TestFetchPanelSections_HeadingResolutionFailureKeepsExactMatch(t *testing.T) {
	useTempSummaryCache(t, 16)
	// 食文化 and 周辺の宿 match no exact candidate; the LLM path is the only
	// way those sections could be filled. The LLM returns 500, so both
	// sections must come back empty without an error or a transient flag.
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{
			{Line: "食文化", Level: 2},
			{Line: "周辺の宿", Level: 2},
		},
		"概要\n\n食文化\n\n地元のそばが名物です。\n\n周辺の宿\n\n周辺には温泉旅館が多数建ち並ぶ。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `要約`)
	fakeOllama.headingStatus = http.StatusInternalServerError
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	hist, food, _, access, tourism, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("LLM heading failure must not mark the panel transient")
	}
	for _, section := range []struct {
		name string
		got  PanelSection
	}{
		{"history", hist}, {"food", food}, {"access", access}, {"tourism", tourism},
	} {
		if section.got.Summary != "" || len(section.got.Blocks) != 0 {
			t.Errorf("%s: expected empty on LLM failure, got %#v", section.name, section.got)
		}
	}
	// One heading call (failed), no summaries (nothing resolved).
	if got := fakeOllama.calls; got != 1 {
		t.Errorf("expected 1 Ollama call (heading, failed), got %d", got)
	}
}

func TestFetchPanelSections_FallsBackToBlocksWhenOllamaFails(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "歴史", Level: 2}},
		"概要\n\n歴史\n\n開創は明治時代。")
	withWikipediaBase(t, fw)

	// Ollama returns 500 => generateSummary errors => raw blocks, no summary.
	fakeOllama := newFakeOllama(t, `要約`)
	fakeOllama.status = http.StatusInternalServerError
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	hist, _, _, _, _, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		// A 500 from Ollama is a per-section fallback, not a panel-level
		// failure (the article itself resolved), so err should be nil.
		t.Fatalf("expected nil error on Ollama fallback, got %v", err)
	}
	if transient {
		t.Fatal("Ollama failure must not mark the panel transient/unavailable")
	}
	if len(hist.Blocks) == 0 {
		t.Error("expected blocks to be returned as fallback")
	}
	if hist.Summary != "" {
		t.Errorf("expected empty summary on Ollama failure, got %q", hist.Summary)
	}
}

func TestFetchPanelSections_DisabledSkipsLLMEntirely(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "歴史", Level: 2}},
		"概要\n\n歴史\n\n開創は明治時代。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `要約`)
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "1")

	hist, _, _, _, _, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatal(err)
	}
	if transient {
		t.Fatal("did not expect transient failure")
	}
	if hist.Summary != "" {
		t.Errorf("summary must stay empty when disabled, got %q", hist.Summary)
	}
	if len(hist.Blocks) == 0 {
		t.Error("expected raw blocks even when summarization is disabled")
	}
	if fakeOllama.calls != 0 {
		t.Errorf("expected no Ollama calls when disabled, got %d", fakeOllama.calls)
	}
}

func TestFetchPanelSections_EfficacyStructuredItems(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "効能", Level: 2}},
		"概要\n\n効能\n\n美肌、切り傷、やけど、神経痛、疲労回復があるとされる。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `効能`)
	fakeOllama.summaryBody = `{"summary":"入浴による美肌・疲労回復に用いられる。",` +
		`"items":[{"label":"美肌","value":"美白・美肌効果"},{"label":"疲労回復","value":"全身の疲労軽減"}]}`
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	var efficacy PanelSection
	_, _, efficacy, _, _, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("did not expect a transient failure")
	}
	if efficacy.Summary == "" {
		t.Errorf("efficacy: expected a non-empty summary, got %q", efficacy.Summary)
	}
	if len(efficacy.Items) != 2 {
		t.Fatalf("efficacy: expected 2 items, got %d", len(efficacy.Items))
	}
	if efficacy.Items[0].Label != "美肌" || efficacy.Items[1].Label != "疲労回復" {
		t.Errorf("efficacy items labels = %#v", efficacy.Items)
	}
	if len(efficacy.Blocks) == 0 {
		t.Error("efficacy: expected raw blocks alongside the structured answer")
	}
}

func TestFetchPanelSections_AccessStructuredItems(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "アクセス", Level: 2}},
		"概要\n\nアクセス\n\nJR松山駅から予讃線で道後温泉駅へ、約20分。駅前から徒歩約15分。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `要約`)
	fakeOllama.summaryBody = `{"summary":"JR松山駅から電車約20分、駅前から徒歩約15分。",` +
		`"items":[{"label":"電車","value":"予讃線で約20分","from":"JR松山駅","to":"道後温泉駅"},` +
		`{"label":"徒歩","value":"約15分","from":"道後温泉駅","to":"施設"}]}`
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	_, _, _, access, _, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("did not expect a transient failure")
	}
	if access.Summary != "JR松山駅から電車約20分、駅前から徒歩約15分。" {
		t.Errorf("access summary = %q", access.Summary)
	}
	if len(access.Items) != 2 {
		t.Fatalf("expected 2 items, got %d", len(access.Items))
	}
	if access.Items[0].Label != "電車" || access.Items[0].Value == "" {
		t.Errorf("items[0] = %#v", access.Items[0])
	}
	if access.Items[0].From != "JR松山駅" || access.Items[0].To != "道後温泉駅" {
		t.Errorf("items[0] from/to = %q / %q", access.Items[0].From, access.Items[0].To)
	}
	if len(access.Blocks) == 0 {
		t.Error("expected raw blocks alongside the structured answer")
	}

	// Second open: the structured answer and the heading map are served from
	// cache, so no additional Ollama round-trips.
	_, _, _, access2, _, _, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatal(err)
	}
	if len(access2.Items) != 2 {
		t.Errorf("expected cached items to persist, got %d", len(access2.Items))
	}
	// 1 heading-resolution call (access is the only exact-match section, the
	// other three sections are unresolved) + 1 access structured call.
	if got := fakeOllama.calls; got != 2 {
		t.Errorf("expected 2 Ollama calls with a cache hit on the second open, got %d", got)
	}
}

func TestFetchPanelSections_AccessEmptyFallsBackToBlocks(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "アクセス", Level: 2}},
		"概要\n\nアクセス\n\nJR松山駅から予讃線で道後温泉駅へ、約20分。駅前から徒歩約15分。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `要約`)
	fakeOllama.summaryBody = `JR松山駅から電車約20分、駅前から徒歩約15分。`
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	_, _, _, access, _, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("did not expect a transient failure")
	}
	// An unstructured answer surfaces as a plain summary over the raw blocks.
	if access.Summary != "JR松山駅から電車約20分、駅前から徒歩約15分。" {
		t.Errorf("access summary = %q", access.Summary)
	}
	if len(access.Items) != 0 {
		t.Errorf("expected no structured items, got %#v", access.Items)
	}
	if len(access.Blocks) == 0 {
		t.Error("expected raw blocks with an unstructured access answer")
	}
}

func TestFetchPanelSections_AccessSummaryNoneShowsBlocksOnly(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "アクセス", Level: 2}},
		"概要\n\nアクセス\n\nJR松山駅から予讃線で道後温泉駅へ、約20分。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `要約`)
	fakeOllama.summaryBody = `{"summary":"` + SummaryNone + `","items":[]}`
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	_, _, _, access, _, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("did not expect a transient failure")
	}
	// A "no relevant access text" verdict surfaces as blocks only, mirroring the
	// non-structured path. Summary must be empty (front-end renders the
	// "no content" placeholder when both summary and items are empty).
	if access.Summary != "" {
		t.Errorf("access summary must be empty for a SummaryNone verdict, got %q", access.Summary)
	}
	if len(access.Items) != 0 {
		t.Errorf("access items must be empty for a SummaryNone verdict, got %#v", access.Items)
	}
	if len(access.Blocks) == 0 {
		t.Error("expected raw blocks for a SummaryNone verdict")
	}

	// Second open: the SummaryNone marker is cached, so no re-query.
	_, _, _, access2, _, _, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatal(err)
	}
	if access2.Summary != "" || len(access2.Items) != 0 {
		t.Errorf("cached SummaryNone verdict must still be blocks-only, got %+v", access2)
	}
}

func TestFetchPanelSections_AccessLLMErrorFallsBackToBlocks(t *testing.T) {
	useTempSummaryCache(t, 16)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "アクセス", Level: 2}},
		"概要\n\nアクセス\n\nJR松山駅から予讃線で道後温泉駅へ、約20分。")
	withWikipediaBase(t, fw)

	fakeOllama := newFakeOllama(t, `要約`)
	fakeOllama.status = http.StatusInternalServerError
	withFakeOllama(t, fakeOllama)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")

	_, _, _, access, _, transient, err := FetchPanelSections(t.Context(), "テスト温泉", "")
	if err != nil {
		t.Fatalf("FetchPanelSections error: %v", err)
	}
	if transient {
		t.Fatal("did not expect a transient failure")
	}
	if access.Summary != "" {
		t.Errorf("access summary must be empty on LLM failure, got %q", access.Summary)
	}
	if len(access.Items) != 0 {
		t.Errorf("access items must be empty on LLM failure, got %#v", access.Items)
	}
	if len(access.Blocks) == 0 {
		t.Error("expected raw blocks on LLM failure")
	}
}
