package shared

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"
)

func TestSnapshotIncludesCommittedWALWithoutIDChange(t *testing.T) {
	path := filepath.Join(t.TempDir(), "source.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	for _, query := range []string{"PRAGMA journal_mode=WAL", "PRAGMA wal_autocheckpoint=0", "CREATE TABLE source (id TEXT,value TEXT)", "INSERT INTO source VALUES ('Q1','before')", "PRAGMA wal_checkpoint(TRUNCATE)"} {
		if _, err = db.Exec(query); err != nil {
			t.Fatal(err)
		}
	}
	beforeFile, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	before, ids, err := summaryDatabaseSnapshot(path, "SELECT id FROM source")
	if err != nil {
		t.Fatal(err)
	}
	if len(ids) != 1 || ids[0] != "Q1" {
		t.Fatal("wrong snapshot IDs")
	}
	if _, err = db.Exec("UPDATE source SET value='after'"); err != nil {
		t.Fatal(err)
	}
	afterFile, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if SourceHash(string(beforeFile)) != SourceHash(string(afterFile)) {
		t.Fatal("fixture update did not stay in WAL")
	}
	after, _, err := summaryDatabaseSnapshot(path, "SELECT id FROM source")
	if err != nil {
		t.Fatal(err)
	}
	if before == after {
		t.Fatal("committed WAL content change missed")
	}
	again, _, err := summaryDatabaseSnapshot(path, "SELECT id FROM source")
	if err != nil {
		t.Fatal(err)
	}
	if after != again {
		t.Fatal("unchanged database hash is not stable")
	}
}
