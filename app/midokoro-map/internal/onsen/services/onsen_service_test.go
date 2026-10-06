package services

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

func testOnsenDataPath(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	return filepath.Join(root, "frontend", "onsen.db")
}

// makeTestDB creates a temp sqlite database from baseSchema and inserts rows.
func makeTestDB(t *testing.T, rows ...Onsen) string {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(baseSchema); err != nil {
		t.Fatal(err)
	}
	for _, o := range rows {
		status := o.OperatingStatus
		if status == "" {
			status = "unknown"
		}
		if _, err := db.Exec(
			"INSERT INTO onsen (qid,label_ja,label_en,prefecture,latitude,longitude,description,title_ja,spring_type_raw,spring_type_source,operating_status,operating_status_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
			o.QID, o.LabelJA, o.LabelEN, o.Prefecture, o.Latitude, o.Longitude, o.Description, o.TitleJA, o.SpringTypeRaw, o.SpringTypeSource, status, o.OperatingStatusNote); err != nil {
			t.Fatal(err)
		}
		row := db.QueryRow("SELECT id FROM onsen WHERE qid=?", o.QID)
		var onsenID int
		if err := row.Scan(&onsenID); err != nil {
			t.Fatal(err)
		}
		for _, tag := range o.SpringTypes {
			var tid int
			c, err := db.Exec("INSERT OR IGNORE INTO spring_types (name) VALUES (?)", tag)
			if err != nil {
				t.Fatal(err)
			}
			last, _ := c.LastInsertId()
			trow := db.QueryRow("SELECT id FROM spring_types WHERE name=?", tag)
			if err := trow.Scan(&tid); err != nil {
				tid = int(last)
			}
			if _, err := db.Exec("INSERT OR IGNORE INTO onsen_springs (onsen_id,type_id) VALUES (?,?)", onsenID, tid); err != nil {
				t.Fatal(err)
			}
		}
	}
	return dbPath
}

func loadTestService(t *testing.T, dbPath string) *OnsenService {
	t.Helper()
	service, err := NewOnsenService(dbPath)
	if err != nil {
		t.Fatalf("Failed to create onsen service: %v", err)
	}
	return service
}

func TestNewOnsenService(t *testing.T) {
	dataPath := testOnsenDataPath(t)
	if _, err := os.Stat(dataPath); os.IsNotExist(err) {
		t.Skipf("data file not yet generated: %s", dataPath)
	}
	service := loadTestService(t, dataPath)
	if service == nil {
		t.Fatal("Onsen service is nil")
	}
	if len(service.GetAll()) == 0 {
		t.Fatal("No onsens loaded")
	}
	t.Logf("Loaded %d onsens", len(service.GetAll()))
}

func TestGetByPrefecture(t *testing.T) {
	dbPath := makeTestDB(t,
		Onsen{QID: "Q1", LabelJA: "湯の山温泉", LabelEN: "Yunoyama", Prefecture: "静岡県", Latitude: 34.8196, Longitude: 138.7535},
		Onsen{QID: "Q2", LabelJA: "由布院温泉", LabelEN: "Yufuin", Prefecture: "大分県", Latitude: 33.2650, Longitude: 131.3546},
	)
	service := loadTestService(t, dbPath)

	got := service.GetByPrefecture("静岡県")
	if len(got) != 1 {
		t.Fatalf("Expected 1 onsen for Shizuoka, got %d", len(got))
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
		Onsen{QID: "Q1", LabelJA: "由布院温泉", LabelEN: "Yufuin", Prefecture: "大分県", Latitude: 33.2650, Longitude: 131.3546},
	)
	service := loadTestService(t, dbPath)

	o := service.GetByID("Q1")
	if o == nil {
		t.Fatal("GetByID returned nil")
	}
	if o.LabelJA != "由布院温泉" {
		t.Errorf("Expected 由布院温泉, got %s", o.LabelJA)
	}
	if service.GetByID("Q999") != nil {
		t.Error("GetByID should return nil for non-existent ID")
	}
}

func TestSpringTypesTag(t *testing.T) {
	dbPath := makeTestDB(t,
		Onsen{QID: "Q1", LabelJA: "テスト", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0, SpringTypes: []string{"塩化物泉", "単純温泉", "硫黄泉"}},
	)
	service := loadTestService(t, dbPath)
	o := service.GetByID("Q1")
	if o == nil {
		t.Fatal("GetByID nil")
	}
	sortTags(o.SpringTypes)
	if len(o.SpringTypes) != 3 {
		t.Fatalf("Expected 3 spring types, got %v", o.SpringTypes)
	}
	if !o.HasSpringType("塩化物泉") {
		t.Error("Expected contains 塩化物泉")
	}
	if !o.HasSpringType("硫黄泉") {
		t.Error("Expected contains 硫黄泉")
	}
}

func TestSpringTypeRawPreserved(t *testing.T) {
	dbPath := makeTestDB(t,
		Onsen{QID: "Q1", LabelJA: "テスト", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0,
			SpringTypeRaw: "ナトリウム・カルシウム-硫酸塩・塩化物泉", SpringTypeSource: "heading", SpringTypes: []string{"硫酸塩泉", "塩化物泉"}},
		Onsen{QID: "Q2", LabelJA: "未分類", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0,
			SpringTypeRaw: "泉質はナトリウム-塩化物泉", SpringTypeSource: "inline"},
	)
	service := loadTestService(t, dbPath)

	with := service.GetByID("Q1")
	if with == nil || with.SpringTypeRaw != "ナトリウム・カルシウム-硫酸塩・塩化物泉" || with.SpringTypeSource != "heading" {
		t.Errorf("Expected raw string and source round-trip, got %v", with)
	}
	// インライン抽出の source と正規化されなかった原文は保持される。
	unmatched := service.GetByID("Q2")
	if unmatched == nil || unmatched.SpringTypeRaw != "泉質はナトリウム-塩化物泉" || unmatched.SpringTypeSource != "inline" || len(unmatched.SpringTypes) != 0 {
		t.Errorf("Unexpected unmatched onsen: %#v", unmatched)
	}
}

func TestOperatingStatusRoundTrip(t *testing.T) {
	dbPath := makeTestDB(t,
		Onsen{QID: "Q1", LabelJA: "営業中", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0,
			OperatingStatus: "open", OperatingStatusNote: "現在の温泉として記事が立っている"},
		Onsen{QID: "Q2", LabelJA: "閉鎖済み", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0,
			OperatingStatus: "closed", OperatingStatusNote: "2023年11月26日をもって営業終了"},
		Onsen{QID: "Q3", LabelJA: "不明", Prefecture: "宮城県", Latitude: 38.0, Longitude: 141.0},
	)
	service := loadTestService(t, dbPath)

	open := service.GetByID("Q1")
	if open == nil || open.OperatingStatus != "open" || open.OperatingStatusNote != "現在の温泉として記事が立っている" {
		t.Errorf("open round-trip failed: %#v", open)
	}
	closed := service.GetByID("Q2")
	if closed == nil || closed.OperatingStatus != "closed" || closed.OperatingStatusNote != "2023年11月26日をもって営業終了" {
		t.Errorf("closed round-trip failed: %#v", closed)
	}
	unknown := service.GetByID("Q3")
	if unknown == nil || unknown.OperatingStatus != "unknown" || unknown.OperatingStatusNote != "" {
		t.Errorf("expected unknown default, got: %#v", unknown)
	}
}

func sortTags(list []string) {
	for i := 1; i < len(list); i++ {
		for j := i; j > 0 && list[j] < list[j-1]; j-- {
			list[j], list[j-1] = list[j-1], list[j]
		}
	}
}

func TestDataIntegrity(t *testing.T) {
	dataPath := testOnsenDataPath(t)
	if _, err := os.Stat(dataPath); os.IsNotExist(err) {
		t.Skipf("data file not yet generated: %s", dataPath)
	}
	service := loadTestService(t, dataPath)
	emptyPrefecture := 0
	for i, o := range service.GetAll() {
		if o.QID == "" {
			t.Errorf("Onsen %d has empty QID", i)
		}
		if o.LabelJA == "" {
			t.Errorf("Onsen %d (QID: %s) has empty label_ja", i, o.QID)
		}
		if o.Prefecture == "" {
			emptyPrefecture++
		}
		if o.Latitude < 20 || o.Latitude > 46 {
			t.Errorf("Onsen %d (QID: %s) latitude %.4f outside Japan", i, o.QID, o.Latitude)
		}
		if o.Longitude < 122 || o.Longitude > 154 {
			t.Errorf("Onsen %d (QID: %s) longitude %.4f outside Japan", i, o.QID, o.Longitude)
		}
	}
	// 境界 GeoJSON の網羅性限界で数件は prefecture が空になるのが既知。
	// 大半が空という壊れたデータセットの検出のため、5%超は失敗とする。
	total := len(service.GetAll())
	if emptyPrefecture > total/20 {
		t.Errorf("%d/%d onsens have empty prefecture (threshold 5%%)", emptyPrefecture, total)
	}
}
