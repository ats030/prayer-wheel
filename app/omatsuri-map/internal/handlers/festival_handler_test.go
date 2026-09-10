package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"omatsuri-map/internal/services"
)

func TestGetAllFestivals(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"

	service, err := services.NewFestivalService(dataDir + "/festivals-with-date.json")
	if err != nil {
		t.Fatalf("Failed to create service: %v", err)
	}

	handler := NewFestivalHandler(service)

	req := httptest.NewRequest(http.MethodGet, "/api/festivals", nil)
	w := httptest.NewRecorder()

	handler.GetAllFestivals(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("Expected status %d, got %d", http.StatusOK, w.Code)
	}

	var festivals []services.Festival
	err = json.NewDecoder(w.Body).Decode(&festivals)
	if err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}

	if len(festivals) == 0 {
		t.Error("Expected at least one festival, got 0")
	}

	// Check that date field is present
	if festivals[0].Date == "" {
		t.Error("Date field is missing from response")
	}
}

func TestGetFestivalsByPrefecture(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"

	service, err := services.NewFestivalService(dataDir + "/festivals-with-date.json")
	if err != nil {
		t.Fatalf("Failed to create service: %v", err)
	}

	handler := NewFestivalHandler(service)

	req := httptest.NewRequest(http.MethodGet, "/api/festivals/prefecture/東京都", nil)
	w := httptest.NewRecorder()

	handler.GetFestivalsByPrefecture(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("Expected status %d, got %d", http.StatusOK, w.Code)
	}

	var festivals []services.Festival
	err = json.NewDecoder(w.Body).Decode(&festivals)
	if err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}

	if len(festivals) == 0 {
		t.Error("Expected Tokyo festivals, got 0")
	}

	for _, f := range festivals {
		if f.Prefecture != "東京都" {
			t.Errorf("Expected Tokyo, got %s", f.Prefecture)
		}
	}
}

func TestGetFestivalByQID(t *testing.T) {
	dataDir := "/home/ats030/app/omatsuri-map/data"

	service, err := services.NewFestivalService(dataDir + "/festivals-with-date.json")
	if err != nil {
		t.Fatalf("Failed to create service: %v", err)
	}

	handler := NewFestivalHandler(service)

	festivals := service.GetAll()
	if len(festivals) == 0 {
		t.Fatal("No festivals to test")
	}

	qid := festivals[0].QID
	req := httptest.NewRequest(http.MethodGet, "/api/festivals/"+qid, nil)
	w := httptest.NewRecorder()

	handler.GetFestivalByQID(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("Expected status %d, got %d", http.StatusOK, w.Code)
	}

	var festival services.Festival
	err = json.NewDecoder(w.Body).Decode(&festival)
	if err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}

	if festival.QID != qid {
		t.Errorf("Expected QID %s, got %s", qid, festival.QID)
	}

	if festival.Date == "" {
		t.Error("Date field is missing from response")
	}
}

func TestGetFestivalByQIDNotFound(t *testing.T) {
	testData := `[{"qid": "Q1", "label_ja": "Test", "label_en": "Test", "prefecture": "東京都", "latitude": 35.68, "longitude": 139.69, "date": "日付未定"}]`
	testPath := "/tmp/test-festivals-handler.json"
	if err := os.WriteFile(testPath, []byte(testData), 0644); err != nil {
		t.Fatal(err)
	}
	defer os.Remove(testPath)

	service, err := services.NewFestivalService(testPath)
	if err != nil {
		t.Fatal(err)
	}
	handler := NewFestivalHandler(service)

	req := httptest.NewRequest(http.MethodGet, "/api/festivals/NOTEXIST", nil)
	w := httptest.NewRecorder()

	handler.GetFestivalByQID(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("Expected status %d, got %d", http.StatusNotFound, w.Code)
	}
}
