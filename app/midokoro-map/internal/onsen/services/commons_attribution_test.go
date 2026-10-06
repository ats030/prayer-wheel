package services

import (
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestCommonsFileNameFromSVGThumbnail(t *testing.T) {
	got, err := commonsFileName("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Festival_poster.svg/800px-Festival_poster.svg.png")
	if err != nil || got != "Festival_poster.svg" {
		t.Fatalf("got %q, %v", got, err)
	}
}

func TestCommonsFileNameFromThumbnailHost(t *testing.T) {
	got, err := commonsFileName("https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2e/Asakusa.jpg/960px-Asakusa.jpg")
	if err != nil || got != "Asakusa.jpg" {
		t.Fatalf("got %q, %v", got, err)
	}
}

func TestParseCommonsAttribution(t *testing.T) {
	body := []byte(`{"query":{"pages":{"1":{"imageinfo":[{"descriptionurl":"https://commons.wikimedia.org/wiki/File:Festival.jpg","mime":"image/jpeg","extmetadata":{"Artist":{"value":"<a href=\"/wiki/User:Creator\">Creator</a>"},"LicenseShortName":{"value":"CC BY-SA 4.0"},"LicenseUrl":{"value":"https://creativecommons.org/licenses/by-sa/4.0/"},"AttributionRequired":{"value":"true"}}}]}}}}`)
	got, err := parseCommonsAttribution(body)
	if err != nil {
		t.Fatal(err)
	}
	if got.Artist != `<a href="/wiki/User:Creator">Creator</a>` || got.License != "CC BY-SA 4.0" || !got.AttributionRequired || got.Mime != "image/jpeg" {
		t.Fatalf("unexpected attribution: %+v", got)
	}
}

func TestParseCommonsAttributionRejectsNonPhotoMime(t *testing.T) {
	for _, mime := range []string{"image/svg+xml", "video/mp4", "application/pdf", ""} {
		body := []byte(`{"query":{"pages":{"1":{"imageinfo":[{"descriptionurl":"https://commons.wikimedia.org/wiki/File:Thing.jpg","mime":"` + mime + `","extmetadata":{"LicenseShortName":{"value":"CC0"}}}]}}}}`)
		if _, err := parseCommonsAttribution(body); err == nil {
			t.Errorf("mime %q should be rejected, got nil error", mime)
		}
	}
}

func TestIsAllowedPhotoMime(t *testing.T) {
	for mime, want := range map[string]bool{
		"image/jpeg": true, "image/png": true, "image/webp": true,
		"IMAGE/JPEG": true, " image/jpeg ": true,
		"image/svg+xml": false, "video/mp4": false, "": false,
	} {
		if got := isAllowedPhotoMime(mime); got != want {
			t.Errorf("isAllowedPhotoMime(%q) = %v, want %v", mime, got, want)
		}
	}
}

func TestParseCommonsAttributionUsesCreditForCC3(t *testing.T) {
	body := []byte(`{"query":{"pages":{"1":{"imageinfo":[{"descriptionurl":"https://commons.wikimedia.org/wiki/File:Festival.jpg","mime":"image/jpeg","extmetadata":{"Credit":{"value":"Festival archive"},"LicenseShortName":{"value":"CC BY-SA 3.0"},"LicenseUrl":{"value":"https://creativecommons.org/licenses/by-sa/3.0/"},"AttributionRequired":{"value":"true"}}}]}}}}`)
	got, err := parseCommonsAttribution(body)
	if err != nil || got.Credit != "Festival archive" || got.License != "CC BY-SA 3.0" || !got.AttributionRequired {
		t.Fatalf("unexpected CC 3.0 attribution: %+v, %v", got, err)
	}
}

func TestParseCommonsAttributionAllowsPublicDomainWithoutArtist(t *testing.T) {
	body := []byte(`{"query":{"pages":{"1":{"imageinfo":[{"descriptionurl":"https://commons.wikimedia.org/wiki/File:Historic.jpg","mime":"image/png","extmetadata":{"LicenseShortName":{"value":"Public domain"},"AttributionRequired":{"value":"false"}}}]}}}}`)
	got, err := parseCommonsAttribution(body)
	if err != nil || got.Artist != "" || got.Credit != "" || got.License != "Public domain" || got.AttributionRequired {
		t.Fatalf("unexpected public-domain attribution: %+v, %v", got, err)
	}
}

func TestCommonsFileNameRejectsOtherHosts(t *testing.T) {
	if _, err := commonsFileName("https://example.com/image.jpg"); err == nil {
		t.Fatal("expected non-Commons URL to be rejected")
	}
}

func TestFetchCommonsAttributionRetriesRateLimit(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if requests.Add(1) == 1 {
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"query":{"pages":{"1":{"imageinfo":[{"descriptionurl":"https://commons.wikimedia.org/wiki/File:Festival.jpg","mime":"image/jpeg","extmetadata":{"LicenseShortName":{"value":"CC0"}}}]}}}}`))
	}))
	defer server.Close()
	previousBase := commonsAttributionAPIBase
	commonsAttributionAPIBase = server.URL
	t.Cleanup(func() { commonsAttributionAPIBase = previousBase })

	got, err := FetchCommonsAttribution("https://upload.wikimedia.org/wikipedia/commons/a/ab/Festival.jpg")
	if err != nil || got.License != "CC0" || requests.Load() != 2 {
		t.Fatalf("got %+v after %d requests: %v", got, requests.Load(), err)
	}
}
