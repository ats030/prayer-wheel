package handlers

import (
	"database/sql"
	_ "modernc.org/sqlite"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"shiseki-map/internal/services"
	"strings"
	"testing"
)

func TestGetAllShiseki(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test.db")
	db, _ := sql.Open("sqlite", path)
	db.Exec(`CREATE TABLE shiseki(id INTEGER PRIMARY KEY,qid TEXT UNIQUE,label_ja TEXT,label_en TEXT DEFAULT '',prefecture TEXT DEFAULT '',latitude REAL,longitude REAL,description TEXT DEFAULT '',title_ja TEXT DEFAULT '',era TEXT DEFAULT '',designation TEXT DEFAULT 'unknown',designation_label TEXT DEFAULT '',designation_source TEXT DEFAULT '',heritage_id TEXT DEFAULT '',source_url TEXT DEFAULT '')`)
	db.Exec(`CREATE TABLE categories(id INTEGER PRIMARY KEY,name TEXT UNIQUE)`)
	db.Exec(`CREATE TABLE shiseki_categories(shiseki_id INTEGER,type_id INTEGER,PRIMARY KEY(shiseki_id,type_id))`)
	db.Exec(`INSERT INTO shiseki(qid,label_ja,prefecture,latitude,longitude) VALUES('Q1','登呂遺跡','静岡県',34.9,138.4)`)
	db.Close()
	service, err := services.NewShisekiService(path)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	h := NewShisekiHandler(service)
	recorder := httptest.NewRecorder()
	h.GetAllShiseki(recorder, httptest.NewRequest(http.MethodGet, "/api/shiseki", nil))
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), "登呂遺跡") {
		t.Fatalf("unexpected response: %d %s", recorder.Code, recorder.Body.String())
	}
}
