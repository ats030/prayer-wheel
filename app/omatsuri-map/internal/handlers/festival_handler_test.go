package handlers

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"omatsuri-map/internal/services"

	_ "modernc.org/sqlite"
)

// makeHandlerTestDB builds a temporary SQLite file in the same shape the
// production service requires, then loads the passed tab-separated rows.
//
//	row format: qid<TAB>label_ja<TAB>label_en<TAB>prefecture<TAB>lat<TAB>lng<TAB>date
func makeHandlerTestDB(t *testing.T, rows ...string) string {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`
		CREATE TABLE festival (
			id INTEGER PRIMARY KEY,
			qid TEXT NOT NULL UNIQUE,
			label_ja TEXT NOT NULL,
			label_en TEXT NOT NULL DEFAULT '',
			prefecture TEXT NOT NULL DEFAULT '',
			latitude REAL NOT NULL,
			longitude REAL NOT NULL,
			date TEXT NOT NULL DEFAULT '',
			description TEXT NOT NULL DEFAULT '',
			wikipedia_title TEXT NOT NULL DEFAULT '',
			venue_json TEXT NOT NULL DEFAULT '',
			occurrences_json TEXT NOT NULL DEFAULT '',
			annual_schedule_json TEXT NOT NULL DEFAULT '',
			cultural_relaw_json TEXT NOT NULL DEFAULT '',
			description_source TEXT NOT NULL DEFAULT '',
			coordinate_source TEXT NOT NULL DEFAULT '',
			coordinate_prefecture TEXT NOT NULL DEFAULT '',
			coordinate_validation_source TEXT NOT NULL DEFAULT '',
			jalan_lrg_code TEXT NOT NULL DEFAULT '',
			jalan_lrg_name TEXT NOT NULL DEFAULT '',
			jalan_sml_code TEXT NOT NULL DEFAULT '',
			jalan_sml_name TEXT NOT NULL DEFAULT ''
		);
		CREATE INDEX idx_festival_prefecture ON festival (prefecture);
		CREATE TABLE category_types (
			id INTEGER PRIMARY KEY,
			name TEXT NOT NULL UNIQUE
		);
		CREATE TABLE festival_categories (
			festival_id INTEGER NOT NULL REFERENCES festival(id),
			type_id INTEGER NOT NULL REFERENCES category_types(id),
			PRIMARY KEY (festival_id, type_id)
		);
		CREATE INDEX idx_festival_categories_type ON festival_categories (type_id);
	`); err != nil {
		t.Fatal(err)
	}
	for _, row := range rows {
		fields := strings.Split(row, "\t")
		if len(fields) != 7 {
			t.Fatalf("bad test row %q: want 7 tab-separated fields, got %d", row, len(fields))
		}
		lat, err := strconv.ParseFloat(fields[4], 64)
		if err != nil {
			t.Fatalf("bad lat %q: %v", fields[4], err)
		}
		lng, err := strconv.ParseFloat(fields[5], 64)
		if err != nil {
			t.Fatalf("bad lng %q: %v", fields[5], err)
		}
		if _, err := db.Exec(
			`INSERT INTO festival (qid,label_ja,label_en,prefecture,latitude,longitude,date)
			 VALUES (?,?,?,?,?,?,?)`,
			fields[0], fields[1], fields[2], fields[3], lat, lng, fields[6]); err != nil {
			t.Fatal(err)
		}
	}
	return dbPath
}

func newTestService(t *testing.T, rows ...string) *services.FestivalService {
	t.Helper()
	dbPath := makeHandlerTestDB(t, rows...)
	service, err := services.NewFestivalService(dbPath)
	if err != nil {
		t.Fatalf("NewFestivalService: %v", err)
	}
	return service
}

// shared rows covering 2 prefectures so tests can assert both the
// "list" and "filter" shapes.
const (
	tokyoRow = "Q1\tTest祭A\tTest A\t東京都\t35.68\t139.69\t2026-09-01"
	osakaRow = "Q2\tTest祭B\tTest B\t大阪府\t34.69\t135.50\t2026-09-15"
)

func TestGetAllFestivals(t *testing.T) {
	service := newTestService(t, tokyoRow, osakaRow)
	handler := NewFestivalHandler(service)

	req := httptest.NewRequest(http.MethodGet, "/api/festivals", nil)
	w := httptest.NewRecorder()

	handler.GetAllFestivals(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected %d, got %d", http.StatusOK, w.Code)
	}

	var festivals []services.Festival
	if err := json.NewDecoder(w.Body).Decode(&festivals); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(festivals) == 0 {
		t.Fatal("expected at least one festival")
	}
	if festivals[0].Date == "" {
		t.Error("Date field is missing")
	}
}

func TestGetFestivalsByPrefecture(t *testing.T) {
	service := newTestService(t, tokyoRow, osakaRow)
	handler := NewFestivalHandler(service)

	req := httptest.NewRequest(http.MethodGet, "/api/festivals/prefecture/東京都", nil)
	w := httptest.NewRecorder()

	handler.GetFestivalsByPrefecture(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected %d, got %d", http.StatusOK, w.Code)
	}

	var festivals []services.Festival
	if err := json.NewDecoder(w.Body).Decode(&festivals); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(festivals) == 0 {
		t.Fatal("expected Tokyo festivals")
	}
	for _, f := range festivals {
		if f.Prefecture != "東京都" {
			t.Errorf("Expected 東京都, got %s", f.Prefecture)
		}
	}
}

func TestGetFestivalByQID(t *testing.T) {
	service := newTestService(t, tokyoRow, osakaRow)
	handler := NewFestivalHandler(service)

	festivals := service.GetAll()
	if len(festivals) == 0 {
		t.Fatal("no festivals")
	}
	qid := festivals[0].QID

	req := httptest.NewRequest(http.MethodGet, "/api/festivals/"+qid, nil)
	w := httptest.NewRecorder()

	handler.GetFestivalByQID(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected %d, got %d", http.StatusOK, w.Code)
	}

	var festival services.Festival
	if err := json.NewDecoder(w.Body).Decode(&festival); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if festival.QID != qid {
		t.Errorf("Expected %s, got %s", qid, festival.QID)
	}
	if festival.Date == "" {
		t.Error("Date field is missing")
	}
}

func TestGetFestivalByQIDNotFound(t *testing.T) {
	service := newTestService(t, tokyoRow, osakaRow)
	handler := NewFestivalHandler(service)

	req := httptest.NewRequest(http.MethodGet, "/api/festivals/NOTEXIST", nil)
	w := httptest.NewRecorder()

	handler.GetFestivalByQID(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("Expected %d, got %d", http.StatusNotFound, w.Code)
	}
}
