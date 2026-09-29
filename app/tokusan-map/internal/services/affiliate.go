package services

import (
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
)

// The configured search template is public link metadata, never an API credential.
// An explicitly empty TOKUSAN_AMAZON_URL disables the links, including local fallback.
func affiliateTemplate() string {
	if value, ok := os.LookupEnv("TOKUSAN_AMAZON_URL"); ok {
		return value
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	body, err := os.ReadFile(filepath.Join(home, ".config", "ikimono-note", "settings.json"))
	if err != nil {
		return ""
	}
	var config struct {
		Affiliate struct {
			Enabled bool   `json:"enabled"`
			URL     string `json:"url"`
		} `json:"affiliate"`
	}
	if json.Unmarshal(body, &config) != nil || !config.Affiliate.Enabled {
		return ""
	}
	return config.Affiliate.URL
}

var affiliateTag = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

func amazonSearchURL(template, label string) string {
	u, err := url.Parse(template)
	if err != nil || u.Scheme != "https" || u.Host != "www.amazon.co.jp" || u.Path != "/s" || u.User != nil || u.Fragment != "" || label == "" {
		return ""
	}
	q := u.Query()
	if q.Get("k") != "{query}" || !affiliateTag.MatchString(q.Get("tag")) {
		return ""
	}
	q.Set("k", label)
	u.RawQuery = q.Encode()
	return u.String()
}
