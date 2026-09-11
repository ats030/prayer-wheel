package services

import "testing"

func TestParseWikipediaContent(t *testing.T) {
	body := []byte(`{"query":{"pages":[{"title":"長崎くんち","extract":"祭りの概要です。","pageprops":{"wikibase_item":"Q114712"},"thumbnail":{"source":"https://upload.wikimedia.org/x.jpg"}}]}}`)
	got, err := parseWikipediaContent(body, "Q114712")
	if err != nil {
		t.Fatal(err)
	}
	if got.Description != "祭りの概要です。" {
		t.Fatalf("description = %q", got.Description)
	}
	if got.SourceURL != "https://ja.wikipedia.org/wiki/%E9%95%B7%E5%B4%8E%E3%81%8F%E3%82%93%E3%81%A1" {
		t.Fatalf("source URL = %q", got.SourceURL)
	}
}

func TestParseWikipediaContentRejectsMissingExtract(t *testing.T) {
	if _, err := parseWikipediaContent([]byte(`{"query":{"pages":[{"title":"不明","missing":true}]}}`), "Q1"); err == nil {
		t.Fatal("expected missing content error")
	}
}

func TestParseWikipediaContentRejectsDifferentWikidataItem(t *testing.T) {
	body := []byte(`{"query":{"pages":[{"title":"同名記事","extract":"別の記事です。","pageprops":{"wikibase_item":"Q2"}}]}}`)
	if _, err := parseWikipediaContent(body, "Q1"); err == nil {
		t.Fatal("expected Wikidata identity mismatch error")
	}
}

func TestUsableArticleImageTitlesSkipsInterfaceArtwork(t *testing.T) {
	got := usableArticleImageTitles([]string{
		"ファイル:Commons-logo.svg",
		"ファイル:Camera-photo Upload.svg",
		"ファイル:Sirotoriodori.jpg",
		"ファイル:白鳥おどり発祥の碑.jpg",
	})
	if len(got) != 2 || got[0] != "ファイル:Sirotoriodori.jpg" || got[1] != "ファイル:白鳥おどり発祥の碑.jpg" {
		t.Fatalf("unexpected candidates: %#v", got)
	}
}
