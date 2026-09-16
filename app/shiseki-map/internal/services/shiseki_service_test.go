package services

import (
	"database/sql"
	_ "modernc.org/sqlite"
	"path/filepath"
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
	result, err := db.Exec(`INSERT INTO shiseki(qid,label_ja,prefecture,latitude,longitude,era,designation,designation_label,designation_source,source_url) VALUES('Q1','登呂遺跡','静岡県',34.9,138.4,'弥生時代','special','特別史跡','https://example.test/designation','https://example.test/item')`)
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
	if len(item.Categories) != 1 || item.Categories[0] != "遺跡" {
		t.Fatalf("unexpected categories: %#v", item.Categories)
	}
}
