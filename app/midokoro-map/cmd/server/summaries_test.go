package main

import (
	"encoding/json"
	"midokoro-map/internal/shared"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestPublishedSummaryGateAndResponse(t *testing.T) {
	dir := t.TempDir()
	if registerPublishedSummaries(http.NewServeMux(), dir) == nil {
		t.Fatal("missing artifact enabled summary-only mode")
	}
	p := shared.PublishedSummaries{Version: 6, CheckedAt: time.Now(), Rosters: map[string]string{}, Counts: map[string]int{}, Items: map[string]map[string]map[string]shared.PreparedSection{}}
	for kind, keys := range shared.SummarySections {
		p.Rosters[kind] = "hash"
		p.Counts[kind] = 1
		sections := map[string]shared.PreparedSection{}
		for _, key := range keys {
			sections[key] = shared.Prepared("", nil, false, "", "", true)
		}
		sections["about"] = shared.Prepared("生成した要約", nil, false, "https://ja.wikipedia.org/wiki/例", "原文", true)
		p.Items[kind] = map[string]map[string]shared.PreparedSection{"Q1": sections}
	}
	write := func() {
		b, _ := json.Marshal(p)
		if err := os.WriteFile(filepath.Join(dir, "published-summaries.json"), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	write()
	mux := http.NewServeMux()
	if err := registerPublishedSummaries(mux, dir); err != nil {
		t.Fatal(err)
	}
	for kind := range shared.SummarySections {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("GET", "/api/"+kind+"/summary/Q1", nil))
		if w.Code != 200 || !strings.Contains(w.Body.String(), "生成した要約") || strings.Contains(w.Body.String(), "原文") || strings.Contains(w.Body.String(), "blocks") {
			t.Fatalf("unsafe %s response: %s", kind, w.Body.String())
		}
	}
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, httptest.NewRequest("GET", "/api/onsen/summary/missing", nil))
	if w.Code != 404 {
		t.Fatal("missing ID must not fall back to prose")
	}
	delete(p.Items["onsen"]["Q1"], "about")
	write()
	if registerPublishedSummaries(http.NewServeMux(), dir) == nil {
		t.Fatal("incomplete artifact accepted")
	}
}
