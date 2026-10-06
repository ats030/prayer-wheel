package main

import (
	"database/sql"
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
	for kind, spec := range map[string]struct{ file, table string }{"shiseki": {"shiseki.db", "shiseki"}, "onsen": {"onsen.db", "onsen"}, "omatsuri": {"festivals.db", "festival"}, "tokusan": {"tokusan.db", "tokusan"}} {
		if err := os.MkdirAll(filepath.Join(dir, kind), 0700); err != nil {
			t.Fatal(err)
		}
		db, err := sql.Open("sqlite", filepath.Join(dir, kind, spec.file))
		if err != nil {
			t.Fatal(err)
		}
		if _, err = db.Exec("CREATE TABLE " + spec.table + " (qid TEXT,site_id TEXT); INSERT INTO " + spec.table + " VALUES ('Q1','Q1')"); err != nil {
			t.Fatal(err)
		}
		db.Close()
	}
	var err error
	p.SourceDBHashes, err = shared.SummaryDatabaseHashes(dir)
	if err != nil {
		t.Fatal(err)
	}
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
	db, err := sql.Open("sqlite", filepath.Join(dir, "onsen", "onsen.db"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = db.Exec("UPDATE onsen SET qid='Q2'"); err != nil {
		t.Fatal(err)
	}
	db.Close()
	if registerPublishedSummaries(http.NewServeMux(), dir) == nil {
		t.Fatal("changed database revision accepted")
	}
	p.SourceDBHashes, err = shared.SummaryDatabaseHashes(dir)
	if err != nil {
		t.Fatal(err)
	}
	write()
	if registerPublishedSummaries(http.NewServeMux(), dir) == nil {
		t.Fatal("changed same-count ID roster accepted")
	}
	delete(p.Items["onsen"]["Q1"], "about")
	write()
	if registerPublishedSummaries(http.NewServeMux(), dir) == nil {
		t.Fatal("incomplete artifact accepted")
	}
}
