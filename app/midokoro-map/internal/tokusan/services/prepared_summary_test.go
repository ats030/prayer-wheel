package services

import (
	"context"
	"database/sql"
	"fmt"
	"midokoro-map/internal/shared"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func TestOfficialPreparationRejectsReadErrorsAndInvalidatesChangedSource(t *testing.T) {
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	_, err = db.Exec("CREATE TABLE tokusan(qid TEXT, history TEXT, production TEXT); INSERT INTO tokusan VALUES('local-1','古い歴史。','')")
	if err != nil {
		t.Fatal(err)
	}
	service := &TokusanService{db: db}
	oldOfficial, oldSummary := officialSummaryCache, summaryCache
	officialSummaryCache = newOfficialSummaryCache(filepath.Join(t.TempDir(), "official.json"))
	summaryCache = newSummaryCache(filepath.Join(t.TempDir(), "summaries.json"), 100)
	defer func() { officialSummaryCache, summaryCache = oldOfficial, oldSummary }()
	officialSummaryCache.Put("local-1", "history", SectionContent{Summary: "既存要約。", Items: []SectionItem{}})
	saveSummary("midokoro-official-source-v2:local-1:history", shared.SourceHash("古い歴史。"))
	calls := 0
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		fmt.Fprint(w, `{"message":{"content":"{\"summary\":\"新しい歴史の要約。\",\"items\":[]}"}}`)
	}))
	defer model.Close()
	orig := OllamaBaseURL
	OllamaBaseURL = model.URL
	defer func() { OllamaBaseURL = orig }()
	item := Tokusan{QID: "local-1", SourceURL: "https://example.com/source"}
	sections, err := PrepareOfficialSummary(context.Background(), service, item)
	if err != nil || sections["history"].Summary != "既存要約。" || calls != 0 {
		t.Fatalf("legacy baseline not reused: %v %+v calls=%d", err, sections, calls)
	}
	if _, err = db.Exec("UPDATE tokusan SET history='新しい歴史。'"); err != nil {
		t.Fatal(err)
	}
	sections, err = PrepareOfficialSummary(context.Background(), service, item)
	if err != nil || sections["history"].Summary != "新しい歴史の要約。" || calls != 1 {
		t.Fatalf("changed source reused stale summary: %v %+v calls=%d", err, sections, calls)
	}
	item.ProductionArea = "長野県の一部地域"
	sections, err = PrepareOfficialSummary(context.Background(), service, item)
	if err != nil || sections["production"].Status != "summarized" || sections["production"].CheckedSourceHash != shared.SourceHash(item.ProductionArea) || calls != 2 {
		t.Fatalf("production-area fallback lost: %v %+v calls=%d", err, sections, calls)
	}
	if _, err = db.Exec("DROP TABLE tokusan"); err != nil {
		t.Fatal(err)
	}
	if _, err = PrepareOfficialSummary(context.Background(), service, item); err == nil {
		t.Fatal("database failure treated as absence")
	}
	if _, err = service.GetAllChecked(); err == nil {
		t.Fatal("roster database failure swallowed")
	}
}
