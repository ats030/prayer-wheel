package shared

import (
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func TestAdPermissionAndDataDirectory(t *testing.T) {
	t.Setenv("MIDOKORO_PUBLIC_ORIGIN", "https://maps.example")
	t.Setenv("MIDOKORO_AFFILIATE_ORIGINS", "https://other.example,http://maps.example,https://maps.example/path")
	t.Setenv("JALAN_A8MAT", "fallback")
	if AdsEnabled() || TrackingID("onsen") != "" {
		t.Fatal("unregistered origin must use ordinary links")
	}
	t.Setenv("MIDOKORO_AFFILIATE_ORIGINS", "https://maps.example")
	if !AdsEnabled() || TrackingID("onsen") != "fallback" {
		t.Fatal("registered origin should use its configured ID")
	}
	t.Setenv("MIDOKORO_ONSEN_A8MAT", "specific")
	if TrackingID("onsen") != "specific" {
		t.Fatal("category-specific ID must take priority")
	}
	root := t.TempDir()
	t.Setenv("MIDOKORO_DATA_DIR", root)
	if DataPath("onsen", "summaries.json") != filepath.Join(root, "onsen", "summaries.json") {
		t.Fatal("cache path ignores data root")
	}
}

func TestAdOriginCannotOverrideRequestHostname(t *testing.T) {
	t.Setenv("MIDOKORO_PUBLIC_ORIGIN", "https://maps.example")
	t.Setenv("MIDOKORO_AFFILIATE_ORIGINS", "https://maps.example")
	request := httptest.NewRequest("GET", "https://unregistered.example/api/tokusan/tokusan/", nil)
	request.Header.Set("Origin", "https://maps.example")
	if RequestAdsEnabled(request) {
		t.Fatal("Origin header must not override unregistered request host")
	}
}
