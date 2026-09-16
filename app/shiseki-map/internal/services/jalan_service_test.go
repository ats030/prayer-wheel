package services

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

const sampleJalanXML = `<?xml version="1.0" encoding="UTF-8"?>
<Results>
  <Hotel>
    <HotelName>テスト旅館</HotelName>
    <HotelDetailURL>https://www.jalan.net/yad000001/</HotelDetailURL>
    <PlanDetailURL>https://www.jalan.net/yad000001/plan001/</PlanDetailURL>
    <HotelThumbnailURL>https://img.jalan.net/000001.jpg</HotelThumbnailURL>
    <Address>テスト県テスト市1-2-3</Address>
  </Hotel>
  <Hotel>
    <HotelName>詳細URLなし宿</HotelName>
    <HotelDetailURL></HotelDetailURL>
    <Address>テスト県テスト市4-5-6</Address>
  </Hotel>
</Results>`

func newTestJalanService(t *testing.T, handler http.HandlerFunc) (*JalanService, func()) {
	t.Helper()
	server := httptest.NewServer(handler)
	svc := &JalanService{
		client:   &http.Client{Timeout: 5 * time.Second},
		apiKey:   "test-key",
		endpoint: server.URL,
	}
	return svc, server.Close
}

func TestSearchNearby_ParsesHotelsAndSkipsMissingDetailURL(t *testing.T) {
	svc, closeFn := newTestJalanService(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/xml")
		w.Write([]byte(sampleJalanXML))
	})
	defer closeFn()

	hotels, err := svc.SearchNearby(35.0, 135.0, 3.0, 10)
	if err != nil {
		t.Fatalf("SearchNearby returned error: %v", err)
	}
	if len(hotels) != 1 {
		t.Fatalf("expected 1 hotel (one skipped for empty DetailURL), got %d: %+v", len(hotels), hotels)
	}
	got := hotels[0]
	if got.Name != "テスト旅館" {
		t.Errorf("Name = %q, want %q", got.Name, "テスト旅館")
	}
	if got.DetailURL != "https://www.jalan.net/yad000001/" {
		t.Errorf("DetailURL = %q, want plain jalan URL (no a8mat configured)", got.DetailURL)
	}
	if got.Address != "テスト県テスト市1-2-3" {
		t.Errorf("Address = %q, want %q", got.Address, "テスト県テスト市1-2-3")
	}
}

func TestSearchNearby_AppliesAffiliateWrapWhenA8matConfigured(t *testing.T) {
	svc, closeFn := newTestJalanService(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/xml")
		w.Write([]byte(sampleJalanXML))
	})
	defer closeFn()
	svc.a8mat = "abc123"

	hotels, err := svc.SearchNearby(35.0, 135.0, 3.0, 10)
	if err != nil {
		t.Fatalf("SearchNearby returned error: %v", err)
	}
	if len(hotels) != 1 {
		t.Fatalf("expected 1 hotel, got %d", len(hotels))
	}
	if !strings.HasPrefix(hotels[0].DetailURL, "https://px.a8.net/svt/ejp?") {
		t.Errorf("DetailURL = %q, want an A8.net tracking link", hotels[0].DetailURL)
	}
	if !strings.Contains(hotels[0].DetailURL, "a8mat=abc123") {
		t.Errorf("DetailURL = %q, want it to contain a8mat=abc123", hotels[0].DetailURL)
	}
}

func TestSearchNearby_SendsRequestParameters(t *testing.T) {
	var gotQuery = make(map[string]string)
	svc, closeFn := newTestJalanService(t, func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		gotQuery["key"] = q.Get("key")
		gotQuery["range"] = q.Get("range")
		gotQuery["count"] = q.Get("count")
		gotQuery["x"] = q.Get("x")
		gotQuery["y"] = q.Get("y")
		w.Header().Set("Content-Type", "application/xml")
		w.Write([]byte(`<Results></Results>`))
	})
	defer closeFn()

	if _, err := svc.SearchNearby(35.0, 135.0, 3.0, 10); err != nil {
		t.Fatalf("SearchNearby returned error: %v", err)
	}

	if gotQuery["key"] != "test-key" {
		t.Errorf("key = %q, want %q", gotQuery["key"], "test-key")
	}
	if gotQuery["range"] != "3" {
		t.Errorf("range = %q, want %q", gotQuery["range"], "3")
	}
	if gotQuery["count"] != "10" {
		t.Errorf("count = %q, want %q", gotQuery["count"], "10")
	}
	wantX := "486000000" // 135.0 * 3600 * 1000
	wantY := "126000000" // 35.0 * 3600 * 1000
	if gotQuery["x"] != wantX {
		t.Errorf("x = %q, want %q", gotQuery["x"], wantX)
	}
	if gotQuery["y"] != wantY {
		t.Errorf("y = %q, want %q", gotQuery["y"], wantY)
	}
}

func TestSearchNearby_ClampsRadiusAndCount(t *testing.T) {
	var gotQuery = make(map[string]string)
	svc, closeFn := newTestJalanService(t, func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		gotQuery["range"] = q.Get("range")
		gotQuery["count"] = q.Get("count")
		w.Header().Set("Content-Type", "application/xml")
		w.Write([]byte(`<Results></Results>`))
	})
	defer closeFn()

	if _, err := svc.SearchNearby(35.0, 135.0, 0.001, 999); err != nil {
		t.Fatalf("SearchNearby returned error: %v", err)
	}
	if gotQuery["range"] != "0.1" {
		t.Errorf("range = %q, want clamped %q", gotQuery["range"], "0.1")
	}
	if gotQuery["count"] != "10" {
		t.Errorf("count = %q, want fallback default %q", gotQuery["count"], "10")
	}
}

func TestSearchNearby_HTTPErrorStatusReturnsError(t *testing.T) {
	svc, closeFn := newTestJalanService(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("internal error"))
	})
	defer closeFn()

	_, err := svc.SearchNearby(35.0, 135.0, 3.0, 10)
	if err == nil {
		t.Fatal("expected error for non-200 response, got nil")
	}
}

func TestAffiliateWrap_ReturnsPlainURLWithoutA8mat(t *testing.T) {
	svc := &JalanService{}
	dest := "https://www.jalan.net/yad000001/"
	if got := svc.affiliateWrap(dest); got != dest {
		t.Errorf("affiliateWrap() = %q, want unchanged %q", got, dest)
	}
}

func TestAffiliateWrap_ReturnsEmptyForEmptyDest(t *testing.T) {
	svc := &JalanService{a8mat: "abc123"}
	if got := svc.affiliateWrap(""); got != "" {
		t.Errorf("affiliateWrap(\"\") = %q, want empty string", got)
	}
}
