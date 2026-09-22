package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"shiseki-map/internal/services"
)

func TestHotelAreaNearbyHotels_ServiceNotConfiguredReturns503(t *testing.T) {
	h := NewHotelAreaHandler(nil)
	req := httptest.NewRequest(http.MethodGet, "/api/hotel-area/nearby?prefecture=東京都", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("Expected status %d, got %d", http.StatusServiceUnavailable, w.Code)
	}
}

func TestHotelAreaNearbyHotels_MissingPrefectureReturns400(t *testing.T) {
	h := NewHotelAreaHandler(services.NewHotelAreaServiceForTest("test-a8mat"))
	req := httptest.NewRequest(http.MethodGet, "/api/hotel-area/nearby", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("Expected status %d, got %d", http.StatusBadRequest, w.Code)
	}
}

func TestHotelAreaNearbyHotels_UnknownPrefectureReturns400(t *testing.T) {
	h := NewHotelAreaHandler(services.NewHotelAreaServiceForTest("test-a8mat"))
	req := httptest.NewRequest(http.MethodGet, "/api/hotel-area/nearby?prefecture=存在しない県", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("Expected status %d, got %d", http.StatusBadRequest, w.Code)
	}
}

func TestHotelAreaNearbyHotels_MethodNotAllowed(t *testing.T) {
	h := NewHotelAreaHandler(services.NewHotelAreaServiceForTest("test-a8mat"))
	req := httptest.NewRequest(http.MethodPost, "/api/hotel-area/nearby?prefecture=東京都", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("Expected status %d, got %d", http.StatusMethodNotAllowed, w.Code)
	}
}

func TestHotelAreaNearbyHotels_SuccessReturnsHotelJSON(t *testing.T) {
	h := NewHotelAreaHandler(services.NewHotelAreaServiceForTest("test-a8mat"))
	req := httptest.NewRequest(http.MethodGet, "/api/hotel-area/nearby?prefecture=東京都", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected status %d, got %d, body=%s", http.StatusOK, w.Code, w.Body.String())
	}

	var body struct {
		Hotels []struct {
			Name      string `json:"name"`
			DetailURL string `json:"detail_url"`
		} `json:"hotels"`
	}
	if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}
	if len(body.Hotels) != 1 {
		t.Fatalf("Expected 1 hotel entry, got %d", len(body.Hotels))
	}
	if body.Hotels[0].DetailURL == "" {
		t.Error("Expected a non-empty detail_url")
	}
}

func TestHotelAreaNearbyHotels_LargeAreaNameAndFallback(t *testing.T) {
	h := NewHotelAreaHandler(services.NewHotelAreaServiceForTest(""))
	for _, test := range []struct{ query, wantName, wantURL string }{
		{"prefecture=神奈川県&lrg_code=141600&lrg_name=箱根", "箱根の宿を探す（じゃらん）", "https://www.jalan.net/140000/LRG_141600/"},
		{"prefecture=神奈川県&lrg_code=091400&lrg_name=誤った地域", "神奈川県の宿を探す（じゃらん）", "https://www.jalan.net/140000/"},
	} {
		req := httptest.NewRequest(http.MethodGet, "/api/hotel-area/nearby?"+test.query, nil)
		w := httptest.NewRecorder()
		h.NearbyHotels(w, req)
		var body struct {
			Hotels []struct {
				Name      string `json:"name"`
				DetailURL string `json:"detail_url"`
			} `json:"hotels"`
		}
		if err := json.NewDecoder(w.Body).Decode(&body); err != nil || len(body.Hotels) != 1 {
			t.Fatalf("response decode failed: %v body=%s", err, w.Body.String())
		}
		if body.Hotels[0].Name != test.wantName || body.Hotels[0].DetailURL != test.wantURL {
			t.Errorf("hotel = %+v, want name=%q url=%q", body.Hotels[0], test.wantName, test.wantURL)
		}
	}
}
