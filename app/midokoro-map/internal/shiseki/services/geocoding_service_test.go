package services

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestReverseGeocodeUsesConfiguredEndpointAndIdentity(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/reverse" {
			t.Fatalf("path = %q, want /reverse", r.URL.Path)
		}
		if got := r.Header.Get("User-Agent"); !strings.Contains(got, "shiseki-map") {
			t.Fatalf("User-Agent = %q, want application identity", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"address":{"city":"青森市","state":"青森県","road":"県道16号"},"display_name":"青森県青森市"}`))
	}))
	defer server.Close()

	service := NewGeocodingService()
	service.endpoint = server.URL
	service.rateLimitDelay = 0
	result, err := service.ReverseGeocode(40.822342, 140.74739)
	if err != nil {
		t.Fatal(err)
	}
	if result.Address.City != "青森市" || result.Address.Road != "県道16号" {
		t.Fatalf("unexpected address: %+v", result.Address)
	}
}
