package services

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// withFakeJawiki points both the Wikidata sitelinks endpoint and the Japanese Wikipedia
// wikitext endpoint at a local test server.
func withFakeJawiki(t *testing.T, s *httptest.Server) {
	t.Helper()
	origWikidata, origJa := wikidataAPIBase, jaWikipediaBase
	origBackoff := initialBackoff
	wikidataAPIBase = s.URL
	jaWikipediaBase = s.URL
	initialBackoff = time.Millisecond
	t.Cleanup(func() {
		wikidataAPIBase = origWikidata
		jaWikipediaBase = origJa
		initialBackoff = origBackoff
	})
}

func TestExtractOfficialSite_InfoboxBracketed(t *testing.T) {
	wt := "{{Infobox|...}}\n|外部リンク = [http://www.hakone.or.jp/ 箱根町観光協会公式サイト]\n"
	if got := extractOfficialSite(wt); got != "http://www.hakone.or.jp/" {
		t.Fatalf("got %q", got)
	}
}

func TestExtractOfficialSite_InfoboxPlainURL(t *testing.T) {
	wt := "{{Infobox|...}}\n|外部リンク = https://www.kawatana.com/\n"
	if got := extractOfficialSite(wt); got != "https://www.kawatana.com/" {
		t.Fatalf("got %q", got)
	}
}

func TestExtractOfficialSite_WikilinkOnly(t *testing.T) {
	wt := "{{Infobox|...}}\n|外部リンク = [伊予の三湯 本谷温泉館]\n"
	if got := extractOfficialSite(wt); got != "" {
		t.Fatalf("expected no URL, got %q", got)
	}
}

func TestExtractOfficialSite_FallsBackToSection(t *testing.T) {
	wt := "概要\n...\n\n== 外部リンク ==\n* [https://example-onsen.example/ 公式]\n* [https://commons.wikimedia.org/wiki/x その他]\n"
	if got := extractOfficialSite(wt); got != "https://example-onsen.example/" {
		t.Fatalf("got %q", got)
	}
}

func TestExtractOfficialSite_IgnoresWikimediaSectionLinks(t *testing.T) {
	wt := "概要\n\n== 外部リンク ==\n* [https://commons.wikimedia.org/wiki/x その他]\n"
	if got := extractOfficialSite(wt); got != "" {
		t.Fatalf("should skip wikimedia hosts, got %q", got)
	}
}

func TestResolveJawikiTitle_NoArticle(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"entities":{"Q1":{"sitelinks":{"enwiki":{"title":"Foo"}}}}}`))
	}))
	defer s.Close()
	withFakeJawiki(t, s)

	title, err := resolveJawikiTitle(context.Background(), "Q1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if title != "" {
		t.Fatalf("expected empty title, got %q", title)
	}
}

func TestResolveJawikiTitle_Resolves(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"entities":{"Q1":{"sitelinks":{"jawiki":{"title":"箱根温泉"}}}}}`))
	}))
	defer s.Close()
	withFakeJawiki(t, s)

	title, err := resolveJawikiTitle(context.Background(), "Q1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if title != "箱根温泉" {
		t.Fatalf("got %q", title)
	}
}

// withFakeWikidata returns a testserver that answers both wbgetentities (sitelinks) and
// the parse/wikitext endpoint with the supplied article wikitext.
func withFakeWikidataAndJawiki(t *testing.T, sitelinksJSON string, wikitext string) {
	t.Helper()
	origWikidata, origJa := wikidataAPIBase, jaWikipediaBase
	origBackoff := initialBackoff
	initialBackoff = time.Millisecond
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Query().Get("action") == "wbgetentities" {
			w.Write([]byte(sitelinksJSON))
			return
		}
		b, _ := json.Marshal(wikitext)
		w.Write([]byte(`{"parse":{"wikitext":` + string(b) + `}}`))
	}))
	wikidataAPIBase = s.URL
	jaWikipediaBase = s.URL
	t.Cleanup(func() {
		s.Close()
		wikidataAPIBase = origWikidata
		jaWikipediaBase = origJa
		initialBackoff = origBackoff
	})
}

func TestFallbackOfficialSite_EndToEnd(t *testing.T) {
	withFakeWikidataAndJawiki(t,
		`{"entities":{"Q1":{"sitelinks":{"jawiki":{"title":"箱根温泉"}}}}}`,
		"{{Infobox|...}}\n|外部リンク = [http://www.hakone.or.jp/ 箱根町観光協会公式サイト]\n",
	)
	url, err := fallbackOfficialSite(context.Background(), "Q1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if url != "http://www.hakone.or.jp/" {
		t.Fatalf("got %q", url)
	}
}

func TestFallbackOfficialSite_NoArticle(t *testing.T) {
	withFakeWikidataAndJawiki(t,
		`{"entities":{"Q1":{"sitelinks":{}}}}`,
		"",
	)
	url, err := fallbackOfficialSite(context.Background(), "Q1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if url != "" {
		t.Fatalf("expected empty, got %q", url)
	}
}

func TestFetchWikidataLinks_FallsBackToWikipediaSource(t *testing.T) {
	// Wikidata has no P856; Japanese article provides one.
	withFakeWikidataAndJawiki(t,
		`{"entities":{"Q1":{"claims":{"P2013":[{"mainsnak":{"datavalue":{"value":"foo"}}}]},"sitelinks":{"jawiki":{"title":"箱根温泉"}}}}}`,
		"|外部リンク = [http://www.hakone.or.jp/ 箱根町観光協会]\n",
	)
	links, err := FetchWikidataLinks("Q1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if links.OfficialSite != "http://www.hakone.or.jp/" {
		t.Fatalf("OfficialSite = %q", links.OfficialSite)
	}
	if links.OfficialSiteSource != "wikipedia" {
		t.Fatalf("source = %q", links.OfficialSiteSource)
	}
	if links.Facebook != "https://www.facebook.com/foo" {
		t.Fatalf("Facebook = %q", links.Facebook)
	}
}

func TestFetchWikidataLinks_PreferencesWikidataP856(t *testing.T) {
	// Wikidata provides P856; Wikipedia should not be consulted.
	withFakeWikidataAndJawiki(t,
		`{"entities":{"Q1":{"claims":{"P856":[{"mainsnak":{"datavalue":{"value":"https://example.com/"}}}]},"sitelinks":{}}}}`,
		"",
	)
	links, err := FetchWikidataLinks("Q1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if links.OfficialSite != "https://example.com/" {
		t.Fatalf("OfficialSite = %q", links.OfficialSite)
	}
	if links.OfficialSiteSource != "wikidata" {
		t.Fatalf("source = %q", links.OfficialSiteSource)
	}
}

func TestFetchWikidataLinks_NoLinksAnywhere(t *testing.T) {
	withFakeWikidataAndJawiki(t,
		`{"entities":{"Q1":{"claims":{},"sitelinks":{}}}}`,
		"",
	)
	if _, err := FetchWikidataLinks("Q1"); err == nil {
		t.Fatal("expected error when nothing is found anywhere")
	}
}
