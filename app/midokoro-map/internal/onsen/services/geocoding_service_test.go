package services

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestReverseGeocodeRatesBurstWithoutSerializingWaiters(t *testing.T) {
	calls := make(chan struct{}, 6)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls <- struct{}{}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"address":{"city":"青森市"},"display_name":"青森"}`))
	}))
	defer server.Close()

	service := NewGeocodingService()
	service.endpoint = server.URL
	delay := 50 * time.Millisecond
	service.rateLimitDelay = delay

	start := time.Now()
	var wg sync.WaitGroup
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := service.ReverseGeocode(40.82, 140.74); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	elapsed := time.Since(start)

	// 5 gaps between 6 calls, each ~delay, plus headroom for scheduling.
	lower := 4 * delay
	upper := 8 * delay
	if elapsed < lower || elapsed > upper {
		t.Fatalf("6-call burst took %v, want between %v and %v", elapsed, lower, upper)
	}
	if got := len(calls); got != 6 {
		t.Fatalf("server saw %d calls, want 6", got)
	}
}

func TestReverseGeocodeUsesConfiguredEndpointAndIdentity(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/reverse" {
			t.Fatalf("path = %q, want /reverse", r.URL.Path)
		}
		if got := r.Header.Get("User-Agent"); !strings.Contains(got, "onsen-map") {
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
