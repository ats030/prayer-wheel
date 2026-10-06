package handlers

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"midokoro-map/internal/onsen/services"

	_ "modernc.org/sqlite"
)

// baseSchema is the schema onsen service expects to find on open.
const baseSchema = `
CREATE TABLE IF NOT EXISTS onsen (
	id         INTEGER PRIMARY KEY,
	qid        TEXT NOT NULL UNIQUE,
	label_ja   TEXT NOT NULL,
	label_en   TEXT NOT NULL DEFAULT '',
	prefecture TEXT NOT NULL DEFAULT '',
	latitude   REAL NOT NULL,
	longitude  REAL NOT NULL,
	description TEXT NOT NULL DEFAULT '',
	title_ja   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS spring_types (
	id   INTEGER PRIMARY KEY,
	name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS onsen_springs (
	onsen_id INTEGER NOT NULL REFERENCES onsen(id),
	type_id  INTEGER NOT NULL REFERENCES spring_types(id),
	PRIMARY KEY (onsen_id, type_id)
);
`

type row struct {
	qid, labelJA, labelEN, prefecture string
	lat, lon                          float64
	desc                              string
	springTypes                       []string
}

func makeOnsenService(t *testing.T, rows ...row) *services.OnsenService {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "onsen.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(baseSchema); err != nil {
		db.Close()
		t.Fatal(err)
	}
	for _, r := range rows {
		if _, err := db.Exec(
			"INSERT INTO onsen (qid,label_ja,label_en,prefecture,latitude,longitude,description) VALUES (?,?,?,?,?,?,?)",
			r.qid, r.labelJA, r.labelEN, r.prefecture, r.lat, r.lon, r.desc); err != nil {
			db.Close()
			t.Fatal(err)
		}
		var onsenID int64
		if err := db.QueryRow("SELECT id FROM onsen WHERE qid=?", r.qid).Scan(&onsenID); err != nil {
			db.Close()
			t.Fatal(err)
		}
		for _, tag := range r.springTypes {
			if _, err := db.Exec("INSERT OR IGNORE INTO spring_types (name) VALUES (?)", tag); err != nil {
				db.Close()
				t.Fatal(err)
			}
			var tid int64
			if err := db.QueryRow("SELECT id FROM spring_types WHERE name=?", tag).Scan(&tid); err != nil {
				db.Close()
				t.Fatal(err)
			}
			if _, err := db.Exec("INSERT OR IGNORE INTO onsen_springs (onsen_id,type_id) VALUES (?,?)", onsenID, tid); err != nil {
				db.Close()
				t.Fatal(err)
			}
		}
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	svc, err := services.NewOnsenService(path)
	if err != nil {
		t.Fatal(err)
	}
	return svc
}

func TestGetAllOnsen(t *testing.T) {
	svc := makeOnsenService(t,
		row{qid: "Q1", labelJA: "湯の山温泉", labelEN: "Yunoyama", prefecture: "静岡県", lat: 34.8196, lon: 138.7535, desc: "富士山の東麓にある温泉地", springTypes: []string{"単純温泉"}},
		row{qid: "Q2", labelJA: "由布院温泉", labelEN: "Yufuin", prefecture: "大分県", lat: 33.2650, lon: 131.3546, desc: "大分県北東部の温泉街", springTypes: []string{"塩化物泉", "炭酸水素塩泉"}},
	)
	h := NewOnsenHandler(svc)

	req := httptest.NewRequest(http.MethodGet, "/api/onsen", nil)
	w := httptest.NewRecorder()
	h.GetAllOnsen(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected status %d, got %d", http.StatusOK, w.Code)
	}

	var onsens []services.Onsen
	if err := json.NewDecoder(w.Body).Decode(&onsens); err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}
	if len(onsens) != 2 {
		t.Fatalf("Expected 2 onsens, got %d", len(onsens))
	}
}

func TestGetOnsenByPrefecture(t *testing.T) {
	svc := makeOnsenService(t,
		row{qid: "Q1", labelJA: "湯の山温泉", prefecture: "静岡県", lat: 34.8196, lon: 138.7535, springTypes: []string{"単純温泉"}},
		row{qid: "Q2", labelJA: "由布院温泉", prefecture: "大分県", lat: 33.2650, lon: 131.3546, springTypes: []string{"塩化物泉"}},
	)
	h := NewOnsenHandler(svc)

	req := httptest.NewRequest(http.MethodGet, "/api/onsen/prefecture/静岡県", nil)
	w := httptest.NewRecorder()
	h.GetOnsenByPrefecture(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected status %d, got %d", http.StatusOK, w.Code)
	}

	var onsens []services.Onsen
	if err := json.NewDecoder(w.Body).Decode(&onsens); err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}
	if len(onsens) != 1 {
		t.Fatalf("Expected 1 onsen for Shizuoka, got %d", len(onsens))
	}
	if onsens[0].Prefecture != "静岡県" {
		t.Errorf("Expected 静岡県, got %s", onsens[0].Prefecture)
	}
}

func TestGetOnsenByQID(t *testing.T) {
	svc := makeOnsenService(t,
		row{qid: "Q99", labelJA: "有馬温泉", prefecture: "兵庫県", lat: 34.8646, lon: 135.3179, springTypes: []string{"単純温泉", "塩化物泉"}},
	)
	h := NewOnsenHandler(svc)

	req := httptest.NewRequest(http.MethodGet, "/api/onsen/Q99", nil)
	w := httptest.NewRecorder()
	h.GetOnsenByQID(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected status %d, got %d", http.StatusOK, w.Code)
	}

	var o services.Onsen
	if err := json.NewDecoder(w.Body).Decode(&o); err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}
	if o.QID != "Q99" {
		t.Errorf("Expected Q99, got %s", o.QID)
	}
}

func TestGetOnsenByQIDNotFound(t *testing.T) {
	svc := makeOnsenService(t,
		row{qid: "Q1", labelJA: "Test", prefecture: "東京都", lat: 35.68, lon: 139.69, springTypes: []string{"単純温泉"}},
	)
	h := NewOnsenHandler(svc)

	req := httptest.NewRequest(http.MethodGet, "/api/onsen/NOTEXIST", nil)
	w := httptest.NewRecorder()
	h.GetOnsenByQID(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("Expected status %d, got %d", http.StatusNotFound, w.Code)
	}
}
