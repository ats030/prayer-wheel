package services

import (
	"database/sql"
	_ "modernc.org/sqlite"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestShisekiServiceReadsDomainFields(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = db.Exec(baseSchema); err != nil {
		t.Fatal(err)
	}
	result, err := db.Exec(`INSERT INTO shiseki(site_id,qid,label_ja,prefecture,latitude,longitude,era,designation,designation_label,designation_source,source_url) VALUES('Q1','Q1','登呂遺跡','静岡県',34.9,138.4,'弥生時代','special','特別史跡','https://example.test/designation','https://example.test/item')`)
	if err != nil {
		t.Fatal(err)
	}
	id, _ := result.LastInsertId()
	cat, err := db.Exec(`INSERT INTO categories(name) VALUES('遺跡')`)
	if err != nil {
		t.Fatal(err)
	}
	catID, _ := cat.LastInsertId()
	if _, err = db.Exec(`INSERT INTO shiseki_categories(shiseki_id,type_id) VALUES(?,?)`, id, catID); err != nil {
		t.Fatal(err)
	}
	db.Close()

	service, err := NewShisekiService(path)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	item := service.GetByQID("Q1")
	if item == nil || item.Era != "弥生時代" || item.Designation != "special" {
		t.Fatalf("unexpected item: %#v", item)
	}
	if item.ID != "Q1" || service.GetByID("Q1") == nil {
		t.Fatalf("legacy ID lookup failed: %#v", item)
	}
	if len(item.Categories) != 1 || item.Categories[0] != "遺跡" {
		t.Fatalf("unexpected categories: %#v", item.Categories)
	}
}

func TestShisekiServiceReadsSourceScopedID(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(baseSchema); err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`INSERT INTO shiseki(site_id,qid,label_ja,prefecture,latitude,longitude,address,source_name,source_license,visit_url,access_note) VALUES('tokyo:130001:1','','史跡A','東京都',35.0,139.0,'東京都A','東京都教育庁','CC BY 4.0','https://example.test/visit','訪問情報')`)
	if err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`INSERT INTO shiseki(site_id,qid,label_ja,prefecture,latitude,longitude) VALUES('tokyo:130001:2','','史跡B','東京都',35.1,139.1)`)
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
	service, err := NewShisekiService(path)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	item := service.GetByID("tokyo:130001:1")
	if item == nil || item.QID != "" || item.Address != "東京都A" || item.SourceName != "東京都教育庁" || item.SourceLicense != "CC BY 4.0" || item.VisitURL != "https://example.test/visit" || item.AccessNote != "訪問情報" {
		t.Fatalf("unexpected source-scoped record: %#v", item)
	}
	if service.GetByQID("tokyo:130001:1") != nil {
		t.Fatal("source-scoped ID must not resolve as a Wikidata QID")
	}
}

func TestShisekiServiceOpensCurrentDatabaseReadOnly(t *testing.T) {
	path := filepath.Join(t.TempDir(), "readonly.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(baseSchema); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO shiseki(site_id,qid,label_ja,prefecture,latitude,longitude) VALUES('tokyo:130001:1','','史跡A','東京都',35,139)`); err != nil {
		t.Fatal(err)
	}
	db.Close()
	if err := os.Chmod(path, 0444); err != nil {
		t.Fatal(err)
	}
	service, err := NewShisekiService(path)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	if service.GetByID("tokyo:130001:1") == nil {
		t.Fatal("read-only database did not return the source-scoped site")
	}
}

func TestShisekiServiceCompletesInterruptedIDMigration(t *testing.T) {
	for _, backfilled := range []bool{false, true} {
		name := "column_only"
		if backfilled {
			name = "backfilled_without_index"
		}
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "partial.db")
			db, err := sql.Open("sqlite", path)
			if err != nil {
				t.Fatal(err)
			}
			partialSchema := strings.Replace(baseSchema, "site_id         TEXT NOT NULL UNIQUE", "site_id         TEXT NOT NULL DEFAULT ''", 1)
			if partialSchema == baseSchema {
				t.Fatal("test schema did not remove the site_id constraint")
			}
			if _, err := db.Exec(partialSchema); err != nil {
				t.Fatal(err)
			}
			for _, qid := range []string{"Q1", "Q2"} {
				id := ""
				if backfilled {
					id = qid
				}
				if _, err := db.Exec(`INSERT INTO shiseki(site_id,qid,label_ja,prefecture,latitude,longitude) VALUES(?,?,?,'東京都',35,139)`, id, qid, qid); err != nil {
					t.Fatal(err)
				}
			}
			db.Close()
			service, err := NewShisekiService(path)
			if err != nil {
				t.Fatal(err)
			}
			defer service.Close()
			for _, qid := range []string{"Q1", "Q2"} {
				if item := service.GetByID(qid); item == nil || item.QID != qid {
					t.Fatalf("migration did not recover %s: %#v", qid, item)
				}
			}
			if _, err := service.db.Exec(`INSERT INTO shiseki(site_id,qid,label_ja,prefecture,latitude,longitude) VALUES('Q1','Q3','duplicate','東京都',35,139)`); err == nil {
				t.Fatal("site_id uniqueness was not restored")
			}
		})
	}
}
