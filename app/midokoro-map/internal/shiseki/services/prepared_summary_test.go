package services

import (
	"context"
	"fmt"
	"midokoro-map/internal/shared"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPreparedMissingArticleIsCompleteButHTTPFailureIsNot(t *testing.T) {
	useTempSummaryCache(t, 100)
	t.Setenv("SHISEKI_SUMMARY_DISABLE", "")
	for _, test := range []struct {
		name    string
		status  int
		body    string
		missing bool
	}{
		{"confirmed_missing", 200, `{"query":{"pages":[{"missing":true}]}}`, true},
		{"http_failure", 403, `forbidden`, false},
		{"malformed", 200, `broken`, false},
		{"api_error", 200, `{"error":{"code":"maxlag","info":"retry"}}`, false},
		{"missing_pages", 200, `{"query":{}}`, false},
		{"missing_extract", 200, `{"query":{"pages":[{"title":"史跡"}]}}`, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(test.status); fmt.Fprint(w, test.body) }))
			defer server.Close()
			withWikipediaBase(t, server)
			sections, err := PrepareSummary(context.Background(), "史跡", "Q1", "", "")
			if test.missing {
				if err != nil || !shared.SummaryComplete(sections, []string{"about", "history", "remains", "access", "highlights"}) {
					t.Fatalf("confirmed absence is not complete: %v %+v", err, sections)
				}
			} else if err == nil {
				t.Fatal("retrieval failure incorrectly completed")
			}
		})
	}
}

func TestPreparedReusesCacheAndDoesNotPublishRawBlocks(t *testing.T) {
	useTempSummaryCache(t, 100)
	t.Setenv("SHISEKI_SUMMARY_DISABLE", "")
	text := "元の概要。\n歴史\n元の歴史。\n遺構\n元の遺構。\nアクセス\n元のアクセス。\n文化財\n元の指定。"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("action") == "parse" {
			fmt.Fprint(w, `{"parse":{"sections":[{"line":"歴史","level":"2"},{"line":"遺構","level":"2"},{"line":"アクセス","level":"2"},{"line":"文化財","level":"2"}]}}`)
		} else {
			fmt.Fprintf(w, `{"query":{"pages":[{"title":"史跡","extract":%q}]}}`, text)
		}
	}))
	defer server.Close()
	withWikipediaBase(t, server)
	llm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("warmed summaries called model")
		w.WriteHeader(503)
	}))
	defer llm.Close()
	orig := OllamaBaseURL
	OllamaBaseURL = llm.URL
	defer func() { OllamaBaseURL = orig }()
	for _, spec := range sectionSpecs {
		saveSummary(summaryCacheKey("史跡", spec.label, text), spec.label+"の要約。")
	}
	saveSummary("midokoro-about-v1:Q1:"+shared.SourceHash("元の概要。"), "概要の要約。")
	sections, err := PrepareSummary(context.Background(), "史跡", "Q1", "", "")
	if err != nil || !shared.SummaryComplete(sections, []string{"about", "history", "remains", "access", "highlights"}) {
		t.Fatalf("cache not reused: %v %+v", err, sections)
	}
	if sections["about"].Summary != "概要の要約。" || sections["history"].CheckedSourceHash != shared.SourceHash(text) {
		t.Fatalf("summary/provenance lost: %+v", sections)
	}
	// A missed section with source text must remain pending even though the old
	// FetchPanelSections path would have returned nil error and raw blocks.
	summaryCache = newSummaryCache(t.TempDir()+"/summaries.json", 100)
	saveSummary("midokoro-about-v1:Q1:"+shared.SourceHash("元の概要。"), "概要の要約。")
	llm.Config.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) })
	sections, _ = PrepareSummary(context.Background(), "史跡", "Q1", "", "")
	if sections["history"].Status != "retry" {
		t.Fatalf("model failure marked complete: %+v", sections)
	}
	llm.Config.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, `{"message":{"content":"{}"}}`) })
	saveSummary(summaryCacheKey("史跡", sectionSpecs[0].label, text), "{}")
	sections, _ = PrepareSummary(context.Background(), "史跡", "Q1", "", "")
	if sections["history"].Status != "retry" || sections["history"].Summary != "" {
		t.Fatalf("JSON object accepted as prose: %+v", sections)
	}
}

func TestStrictHeadingsRejectsPartialVerdict(t *testing.T) {
	useTempSummaryCache(t, 100)
	old := OllamaBaseURL
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"message":{"content":"{\"history\":\"歴史\"}"}}`)
	}))
	defer model.Close()
	OllamaBaseURL = model.URL
	defer func() { OllamaBaseURL = old }()
	headings := []wikipediaHeading{{Line: "歴史", Level: 2}}
	saveSummary(headingMapCacheKey("史跡", []string{"歴史"}), `{"history":"歴史"}`)
	if _, err := strictHeadingMap(context.Background(), "史跡", headings); err == nil {
		t.Fatal("partial heading verdict accepted as confirmed absence")
	}
	saveSummary(headingMapCacheKey("史跡", []string{"歴史"}), `{"history":"歴史","remains":"","access":"","highlights":""}`)
	if _, err := strictHeadingMap(context.Background(), "史跡", headings); err != nil {
		t.Fatal(err)
	}
}
