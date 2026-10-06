package shared

import (
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

const WikimediaUserAgent = "midokoro-map/1.0 (https://github.com/ats030/ikimono-note)"

// Origins are configured only after the corresponding advertising sites are registered.
func AffiliateOrigins() []string {
	result := []string{}
	for _, value := range strings.Split(os.Getenv("MIDOKORO_AFFILIATE_ORIGINS"), ",") {
		value = strings.TrimSpace(value)
		u, err := url.Parse(value)
		if err == nil && u.Scheme == "https" && u.Host != "" && u.User == nil && u.RawQuery == "" && u.Fragment == "" && (u.Path == "" || u.Path == "/") {
			result = append(result, u.Scheme+"://"+u.Host)
		}
	}
	return result
}

func AdsEnabled() bool {
	origin := strings.TrimSuffix(os.Getenv("MIDOKORO_PUBLIC_ORIGIN"), "/")
	if origin == "" {
		return false
	}
	for _, registered := range AffiliateOrigins() {
		if registered == origin {
			return true
		}
	}
	return false
}

// RequestAdsEnabled prevents an alternate hostname from inheriting advertising
// permission granted to the configured public hostname. Cloud Run supplies the
// original scheme through X-Forwarded-Proto; Host remains the visitor's hostname.
func RequestAdsEnabled(r *http.Request) bool {
	if !AdsEnabled() {
		return false
	}
	scheme := "http"
	if r.TLS != nil || r.URL.Scheme == "https" || r.Header.Get("X-Forwarded-Proto") == "https" {
		scheme = "https"
	}
	origin := scheme + "://" + r.Host
	// A cross-origin consumer must not inherit another site's registration.
	if source := r.Header.Get("Origin"); source != "" && source != origin {
		return false
	}

	for _, registered := range AffiliateOrigins() {
		if origin == registered {
			return true
		}
	}
	return false
}

func TrackingID(kind string) string {
	if !AdsEnabled() {
		return ""
	}
	if value := os.Getenv("MIDOKORO_" + strings.ToUpper(kind) + "_A8MAT"); value != "" {
		return value
	}
	return os.Getenv("JALAN_A8MAT")
}

func DataPath(kind, name string) string {
	root := os.Getenv("MIDOKORO_DATA_DIR")
	if root == "" {
		root = "data"
	}
	return filepath.Join(root, kind, name)
}
