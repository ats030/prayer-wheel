package services

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

func testFestivalDBPath(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	return filepath.Join(root, "frontend", "festivals.db")
}

// makeTestDB creates a temp sqlite database from festivalBaseSchema and inserts rows.
func makeTestDB(t *testing.T, rows ...Festival) string {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(festivalBaseSchema); err != nil {
		t.Fatal(err)
	}
	for _, f := range rows {
		if _, err := db.Exec(
			"INSERT INTO festival (qid,label_ja,label_en,prefecture,latitude,longitude,date,description,wikipedia_title) VALUES (?,?,?,?,?,?,?,?,?)",
			f.QID, f.LabelJA, f.LabelEN, f.Prefecture, f.Latitude, f.Longitude, f.Date, f.Description, f.WikipediaTitle); err != nil {
			t.Fatal(err)
		}
		row := db.QueryRow("SELECT id FROM festival WHERE qid=?", f.QID)
		var festivalID int
		if err := row.Scan(&festivalID); err != nil {
			t.Fatal(err)
		}
		for _, tag := range f.Categories {
			c, err := db.Exec("INSERT OR IGNORE INTO category_types (name) VALUES (?)", tag)
			if err != nil {
				t.Fatal(err)
			}
			last, _ := c.LastInsertId()
			trow := db.QueryRow("SELECT id FROM category_types WHERE name=?", tag)
			var tid int
			if err := trow.Scan(&tid); err != nil {
				tid = int(last)
			}
			if _, err := db.Exec("INSERT OR IGNORE INTO festival_categories (festival_id,type_id) VALUES (?,?)", festivalID, tid); err != nil {
				t.Fatal(err)
			}
		}
	}
	return dbPath
}

func loadTestService(t *testing.T, dbPath string) *FestivalService {
	t.Helper()
	service, err := NewFestivalService(dbPath)
	if err != nil {
		t.Fatalf("Failed to create festival service: %v", err)
	}
	return service
}

func TestNewFestivalService(t *testing.T) {
	dbPath := testFestivalDBPath(t)
	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		t.Skipf("data file not yet generated: %s", dbPath)
	}
	service := loadTestService(t, dbPath)
	if service == nil {
		t.Fatal("Festival service is nil")
	}
	if len(service.GetAll()) == 0 {
		t.Fatal("No festivals loaded")
	}
	t.Logf("Loaded %d festivals", len(service.GetAll()))
}

func TestGetByPrefecture(t *testing.T) {
	dbPath := makeTestDB(t,
		Festival{QID: "Q1", LabelJA: "テスト祭A", Prefecture: "東京都", Latitude: 35.68, Longitude: 139.69},
		Festival{QID: "Q2", LabelJA: "テスト祭B", Prefecture: "大阪府", Latitude: 34.69, Longitude: 135.50},
	)
	service := loadTestService(t, dbPath)

	got := service.GetByPrefecture("東京都")
	if len(got) != 1 {
		t.Fatalf("Expected 1 festival for Tokyo, got %d", len(got))
	}
	if got[0].QID != "Q1" {
		t.Errorf("Expected Q1, got %s", got[0].QID)
	}
	if len(service.GetByPrefecture("沖縄県")) != 0 {
		t.Error("Expected empty list for missing prefecture")
	}
}

func TestGetByID(t *testing.T) {
	dbPath := makeTestDB(t,
		Festival{QID: "Q1", LabelJA: "由布の祭り", Prefecture: "大分県", Latitude: 33.27, Longitude: 131.35},
	)
	service := loadTestService(t, dbPath)

	f := service.GetByID("Q1")
	if f == nil {
		t.Fatal("GetByID returned nil")
	}
	if f.LabelJA != "由布の祭り" {
		t.Errorf("Expected 由布の祭り, got %s", f.LabelJA)
	}
	if service.GetByID("Q999") != nil {
		t.Error("GetByID should return nil for non-existent ID")
	}
}

func TestCategoriesTag(t *testing.T) {
	dbPath := makeTestDB(t,
		Festival{QID: "Q1", LabelJA: "テスト", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0,
			Categories: []string{"山車・屋台", "演舞・盆踊り", "行事"}},
	)
	service := loadTestService(t, dbPath)
	f := service.GetByID("Q1")
	if f == nil {
		t.Fatal("GetByID nil")
	}
	if len(f.Categories) != 3 {
		t.Fatalf("Expected 3 categories, got %v", f.Categories)
	}
	if !f.HasCategory("山車・屋台") {
		t.Error("Expected contains 山車・屋台")
	}
	if !f.HasCategory("行事") {
		t.Error("Expected contains 行事")
	}
}

func TestGetCategories(t *testing.T) {
	dbPath := makeTestDB(t,
		Festival{QID: "Q1", LabelJA: "A", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0,
			Categories: []string{"花火", "行事"}},
		Festival{QID: "Q2", LabelJA: "B", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0,
			Categories: []string{"行列・渡御"}},
	)
	service := loadTestService(t, dbPath)
	got := service.GetCategories()
	set := map[string]bool{}
	for _, c := range got {
		set[c] = true
	}
	for _, want := range []string{"花火", "行事", "行列・渡御"} {
		if !set[want] {
			t.Errorf("GetCategories missing %q (got %v)", want, got)
		}
	}
}

func TestDataIntegrity(t *testing.T) {
	dbPath := testFestivalDBPath(t)
	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		t.Skipf("data file not yet generated: %s", dbPath)
	}
	service := loadTestService(t, dbPath)
	emptyPrefecture := 0
	for i, f := range service.GetAll() {
		if f.QID == "" {
			t.Errorf("Festival %d has empty QID", i)
		}
		if f.LabelJA == "" {
			t.Errorf("Festival %d (QID: %s) has empty label_ja", i, f.QID)
		}
		if f.Prefecture == "" {
			emptyPrefecture++
		}
		if f.Latitude < 24 || f.Latitude > 46 {
			t.Errorf("Festival %d (QID: %s) latitude %.4f outside Japan", i, f.QID, f.Latitude)
		}
		if f.Longitude < 122 || f.Longitude > 154 {
			t.Errorf("Festival %d (QID: %s) longitude %.4f outside Japan", i, f.QID, f.Longitude)
		}
	}
	total := len(service.GetAll())
	if emptyPrefecture > total/20 {
		t.Errorf("%d/%d festivals have empty prefecture (threshold 5%%)", emptyPrefecture, total)
	}
}
