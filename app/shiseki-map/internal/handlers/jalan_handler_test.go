package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"shiseki-map/internal/services"
)

func TestJalanNearbyHotels_ServiceNotConfiguredReturns503(t *testing.T) {
	h := NewJalanHandler(nil)
	req := httptest.NewRequest(http.MethodGet, "/api/jalan/nearby?lat=35.0&lng=135.0", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("Expected status %d, got %d", http.StatusServiceUnavailable, w.Code)
	}
}

func TestJalanNearbyHotels_MissingLatReturns400(t *testing.T) {
	h := NewJalanHandler(&services.JalanService{})
	req := httptest.NewRequest(http.MethodGet, "/api/jalan/nearby?lng=135.0", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("Expected status %d, got %d", http.StatusBadRequest, w.Code)
	}
}

func TestJalanNearbyHotels_MissingLngReturns400(t *testing.T) {
	h := NewJalanHandler(&services.JalanService{})
	req := httptest.NewRequest(http.MethodGet, "/api/jalan/nearby?lat=35.0", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("Expected status %d, got %d", http.StatusBadRequest, w.Code)
	}
}

func TestJalanNearbyHotels_MethodNotAllowed(t *testing.T) {
	h := NewJalanHandler(&services.JalanService{})
	req := httptest.NewRequest(http.MethodPost, "/api/jalan/nearby?lat=35.0&lng=135.0", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("Expected status %d, got %d", http.StatusMethodNotAllowed, w.Code)
	}
}

func TestJalanNearbyHotels_SuccessReturnsHotelsJSON(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/xml")
		w.Write([]byte(`<Results>
			<Hotel>
				<HotelName>テスト旅館</HotelName>
				<HotelDetailURL>https://www.jalan.net/yad000001/</HotelDetailURL>
				<Address>テスト県テスト市1-2-3</Address>
			</Hotel>
		</Results>`))
	}))
	defer server.Close()

	svc := services.NewJalanServiceForTest(server.URL, "test-key", "")
	h := NewJalanHandler(svc)

	req := httptest.NewRequest(http.MethodGet, "/api/jalan/nearby?lat=35.0&lng=135.0&range=2", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected status %d, got %d, body=%s", http.StatusOK, w.Code, w.Body.String())
	}

	var body struct {
		Hotels []services.JalanNearbyHotel `json:"hotels"`
	}
	if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
		t.Fatalf("Failed to decode response: %v", err)
	}
	if len(body.Hotels) != 1 {
		t.Fatalf("Expected 1 hotel, got %d", len(body.Hotels))
	}
	if body.Hotels[0].Name != "テスト旅館" {
		t.Errorf("Name = %q, want %q", body.Hotels[0].Name, "テスト旅館")
	}
}

func TestJalanNearbyHotels_UpstreamErrorReturns502(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	svc := services.NewJalanServiceForTest(server.URL, "test-key", "")
	h := NewJalanHandler(svc)

	req := httptest.NewRequest(http.MethodGet, "/api/jalan/nearby?lat=35.0&lng=135.0", nil)
	w := httptest.NewRecorder()

	h.NearbyHotels(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("Expected status %d, got %d", http.StatusBadGateway, w.Code)
	}
}
