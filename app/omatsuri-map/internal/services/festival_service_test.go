package services

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNewFestivalService(t *testing.T) {
	// Use the test data directory
	dataDir := "/home/ats030/app/omatsuri-map/data"
	
	service, err := NewFestivalService(dataDir)
	if err != nil {
		t.Fatalf("Failed to create festival service: %v", err)
	}
	
	if service == nil {
		t.Fatal("Festival service is nil")
	}
	
	// Verify we have festivals
	festivals := service.GetAll()
	if len(festivals) == 0 {
		t.Fatal("No festivals loaded")
	}
	
	t.Logf("Loaded %d festivals", len(festivals))
}

func TestGetAll(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"
	service, err := NewFestivalService(dataDir)
	if err != nil {
		t.Fatal(err)
	}
	
	festivals := service.GetAll()
	
	// Verify structure of first festival
	if len(festivals) > 0 {
		f := festivals[0]
		if f.QID == "" {
			t.Error("First festival has empty QID")
		}
		if f.LabelJA == "" {
			t.Error("First festival has empty label_ja")
		}
		if f.Prefecture == "" {
			t.Error("First festival has empty prefecture")
		}
		if f.Latitude == 0 {
			t.Error("First festival has zero latitude")
		}
		if f.Longitude == 0 {
			t.Error("First festival has zero longitude")
		}
	}
}

func TestGetByPrefecture(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"
	service, err := NewFestivalService(dataDir)
	if err != nil {
		t.Fatal(err)
	}
	
	// Test with Tokyo
	tokyoFestivals := service.GetByPrefecture("東京都")
	if len(tokyoFestivals) == 0 {
		t.Error("No festivals found for Tokyo")
	}
	
	// Verify all are Tokyo
	for _, f := range tokyoFestivals {
		if f.Prefecture != "東京都" {
			t.Errorf("Expected Tokyo, got %s", f.Prefecture)
		}
	}
}

func TestGetByID(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"
	service, err := NewFestivalService(dataDir)
	if err != nil {
		t.Fatal(err)
	}
	
	// Get first festival's QID
	festivals := service.GetAll()
	if len(festivals) == 0 {
		t.Fatal("No festivals to test")
	}
	
	qid := festivals[0].QID
	f, err := service.GetByID(qid)
	if err != nil {
		t.Errorf("GetByID failed for %s: %v", qid, err)
	}
	
	if f == nil {
		t.Errorf("GetByID returned nil for %s", qid)
	} else if f.QID != qid {
		t.Errorf("Expected QID %s, got %s", qid, f.QID)
	}
}

func TestGetByIDNotFound(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"
	service, err := NewFestivalService(dataDir)
	if err != nil {
		t.Fatal(err)
	}
	
	_, err = service.GetByID("NONEXISTENT")
	if err != nil {
		t.Errorf("GetByID should return nil, not error for non-existent ID")
	}
}

func TestPrefectureCoverage(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"
	service, err := NewFestivalService(dataDir)
	if err != nil {
		t.Fatal(err)
	}
	
	prefectures := make(map[string]bool)
	for _, f := range service.GetAll() {
		prefectures[f.Prefecture] = true
	}
	
	t.Logf("Found festivals in %d prefectures", len(prefectures))
	
	// Verify we have coverage across different regions
	neededRegions := []string{"北海道", "東京都", "大阪府", "宮城県", "広島県", "長崎県"}
	for _, region := range neededRegions {
		if !prefectures[region] {
			t.Logf("Warning: No festivals found for %s", region)
		}
	}
}

func TestDataIntegrity(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"
	service, err := NewFestivalService(dataDir)
	if err != nil {
		t.Fatal(err)
	}
	
	festivals := service.GetAll()
	
	for i, f := range festivals {
		if f.QID == "" {
			t.Errorf("Festival %d has empty QID", i)
		}
		if f.LabelJA == "" {
			t.Errorf("Festival %d (QID: %s) has empty label_ja", i, f.QID)
		}
		if f.Prefecture == "" {
			t.Errorf("Festival %d (QID: %s) has empty prefecture", i, f.QID)
		}
		if f.Latitude < -90 || f.Latitude > 90 {
			t.Errorf("Festival %d (QID: %s) has invalid latitude: %f", i, f.QID, f.Latitude)
		}
		if f.Longitude < -180 || f.Longitude > 180 {
			t.Errorf("Festival %d (QID: %s) has invalid longitude: %f", i, f.QID, f.Longitude)
		}
		// Verify coordinates are for Japan (roughly 24-45 lat, 122-153 lon)
		if f.Latitude < 30 || f.Latitude > 46 {
			t.Logf("Warning: Festival %s (QID: %s) latitude %.4f seems outside Japan", f.LabelJA, f.QID, f.Latitude)
		}
	}
}

func TestFileExists(t *testing.T) {
	dataPath := "/home/ats030/app/omatsuri-map/data/festivals.json"
	if _, err := os.Stat(dataPath); os.IsNotExist(err) {
		t.Fatalf("Data file does not exist: %s", dataPath)
	}
	
	// Check file size
	info, err := os.Stat(dataPath)
	if err != nil {
		t.Fatal(err)
	}
	
	if info.Size() < 1000 {
		t.Errorf("Data file seems too small: %d bytes", info.Size())
	}
	
	t.Logf("Data file size: %d bytes", info.Size())
}
