package services

import (
	"context"
	"encoding/json"
	"midokoro-map/internal/shared"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPreparedPositiveCacheRequiresMatchingSource(t *testing.T) {
	useTempSummaryCache(t, 100)
	t.Setenv("ONSEN_SUMMARY_DISABLE", "")
	lines := []string{"概要の原文。"}
	headings := []map[string]string{}
	for _, spec := range sectionSpecs {
		lines = append(lines, spec.candidates[0], "原文A。")
		headings = append(headings, map[string]string{"line": spec.candidates[0], "level": "2"})
	}
	text := strings.Join(lines, "\n")
	wiki := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("action") == "parse" {
			_ = json.NewEncoder(w).Encode(map[string]any{"parse": map[string]any{"sections": headings}})
		} else {
			_ = json.NewEncoder(w).Encode(map[string]any{"query": map[string]any{"pages": []map[string]string{{"title": "温泉", "extract": text}}}})
		}
	}))
	defer wiki.Close()
	withWikipediaBase(t, wiki)
	calls := 0
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		_ = json.NewEncoder(w).Encode(map[string]any{"message": map[string]string{"content": `{"summary":"現在の原文に基づく要約。","items":[]}`}})
	}))
	defer model.Close()
	old := OllamaBaseURL
	OllamaBaseURL = model.URL
	defer func() { OllamaBaseURL = old }()
	for i, spec := range sectionSpecs {
		key := summaryCacheKey("温泉", spec.label+" v3")
		saveSummary(key, "以前の要約。")
		if i > 0 {
			saveSummary("midokoro-source-v1:"+key, shared.SourceHash(text))
		}
	}
	saveSummary("midokoro-about-v1::"+shared.SourceHash(lines[0]), "概要の要約。")
	sections, err := PrepareSummary(context.Background(), "温泉", "", "", "")
	if err != nil || calls != 1 || sections["history"].Summary != "現在の原文に基づく要約。" {
		t.Fatalf("unknown-source cache reused: %v calls=%d %+v", err, calls, sections)
	}
	text = strings.ReplaceAll(text, "原文A。", "原文B。")
	sections, err = PrepareSummary(context.Background(), "温泉", "", "", "")
	if err != nil || calls != 6 || sections["history"].CheckedSourceHash != shared.SourceHash(text) {
		t.Fatalf("changed source not regenerated: %v calls=%d %+v", err, calls, sections)
	}
}
