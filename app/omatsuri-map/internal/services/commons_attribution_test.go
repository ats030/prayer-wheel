package services

import "testing"

func TestCommonsFileNameFromSVGThumbnail(t *testing.T) {
	got, err := commonsFileName("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Festival_poster.svg/800px-Festival_poster.svg.png")
	if err != nil || got != "Festival_poster.svg" {
		t.Fatalf("got %q, %v", got, err)
	}
}

func TestParseCommonsAttribution(t *testing.T) {
	body := []byte(`{"query":{"pages":{"1":{"imageinfo":[{"descriptionurl":"https://commons.wikimedia.org/wiki/File:Festival.svg","extmetadata":{"Artist":{"value":"<a href=\"/wiki/User:Creator\">Creator</a>"},"LicenseShortName":{"value":"CC BY-SA 4.0"},"LicenseUrl":{"value":"https://creativecommons.org/licenses/by-sa/4.0/"},"AttributionRequired":{"value":"true"}}}]}}}}`)
	got, err := parseCommonsAttribution(body)
	if err != nil {
		t.Fatal(err)
	}
	if got.Artist != `<a href="/wiki/User:Creator">Creator</a>` || got.License != "CC BY-SA 4.0" || !got.AttributionRequired {
		t.Fatalf("unexpected attribution: %+v", got)
	}
}

func TestCommonsFileNameRejectsOtherHosts(t *testing.T) {
	if _, err := commonsFileName("https://example.com/image.jpg"); err == nil {
		t.Fatal("expected non-Commons URL to be rejected")
	}
}
