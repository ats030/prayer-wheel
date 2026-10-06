package services

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func useWarmedTestCache(t *testing.T) {
	t.Helper()
	old := summaryCache
	summaryCache = newSummaryCache(filepath.Join(t.TempDir(), "summaries.json"), 10)
	t.Cleanup(func() { summaryCache = old })
}
func TestDisabledPathServesWarmedSummaries(t *testing.T) {
	useWarmedTestCache(t)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "1")
	title := "テスト遺跡"
	fullText := "冒頭\n発掘の経緯\n縄文時代に集落が営まれた。\n"
	headings := []wikipediaHeading{{Line: "発掘の経緯", Level: 2}}
	mapping, _ := json.Marshal(map[string]string{"history": "発掘の経緯"})
	summaryCache.Put(headingMapCacheKey(title, []string{"発掘の経緯"}), string(mapping))
	summaryCache.Put(summaryCacheKey(title, sectionSpecs[0].label+" v3"), "縄文集落の要約")

	headingMap := resolveSectionHeadings(context.Background(), title, headings)
	if headingMap["history"] != "発掘の経緯" {
		t.Fatalf("cached heading map ignored when disabled: %v", headingMap)
	}
	got := resolvePanelSection(context.Background(), title, fullText, headings, "src", sectionSpecs[0], headingMap)
	if got.Summary != "縄文集落の要約" {
		t.Fatalf("cached summary ignored when disabled: %+v", got)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Query().Get("action") == "parse" {
			w.Write([]byte(`{"parse":{"sections":[{"line":"発掘の経緯","level":"2"}]}}`))
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"query": map[string]any{"pages": []map[string]string{{"title": title, "extract": fullText}}}})
	}))
	defer server.Close()
	oldBase := wikipediaAPIBase
	wikipediaAPIBase = server.URL
	t.Cleanup(func() { wikipediaAPIBase = oldBase })
	history, _, _, _, _, err := resolveSectionsNoSummary(title)
	if err != nil {
		t.Fatal(err)
	}
	if history.Summary != "縄文集落の要約" {
		t.Fatalf("disabled endpoint pipeline lost warmed summary: %+v", history)
	}

}
