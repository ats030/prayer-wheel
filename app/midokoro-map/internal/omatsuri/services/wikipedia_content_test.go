package services

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestParseWikipediaContent(t *testing.T) {
	body := []byte(`{"query":{"pages":[{"title":"長崎くんち","extract":"祭りの概要です。","pageprops":{"wikibase_item":"Q114712"}}]}}`)
	got, err := parseWikipediaContent(context.Background(), body, "Q114712")
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
	if _, err := parseWikipediaContent(context.Background(), []byte(`{"query":{"pages":[{"title":"不明","missing":true}]}}`), "Q1"); err == nil {
		t.Fatal("expected missing content error")
	}
}

func TestParseWikipediaContentRejectsDifferentWikidataItem(t *testing.T) {
	body := []byte(`{"query":{"pages":[{"title":"同名記事","extract":"別の記事です。","pageprops":{"wikibase_item":"Q2"}}]}}`)
	if _, err := parseWikipediaContent(context.Background(), body, "Q1"); err == nil {
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

func TestFetchWikipediaContentRetriesRateLimit(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if requests.Add(1) == 1 {
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"query":{"pages":[{"title":"長崎くんち","extract":"祭りの概要です。","pageprops":{"wikibase_item":"Q114712"}}]}}`))
	}))
	defer server.Close()
	previousBase := wikipediaAPIBase
	wikipediaAPIBase = server.URL
	t.Cleanup(func() { wikipediaAPIBase = previousBase })

	got, err := FetchWikipediaContent(context.Background(), "長崎くんち", "Q114712")
	if err != nil {
		t.Fatalf("fetch error: %v (requests=%d)", err, requests.Load())
	}
	if requests.Load() != 2 {
		t.Fatalf("expected 2 requests after rate limit retry, got %d", requests.Load())
	}
	if got.Description != "祭りの概要です。" {
		t.Fatalf("description = %q", got.Description)
	}
}

func TestFetchWikipediaContentDoesNotRetryOtherErrors(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		requests.Add(1)
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()
	previousBase := wikipediaAPIBase
	wikipediaAPIBase = server.URL
	t.Cleanup(func() { wikipediaAPIBase = previousBase })

	if _, err := FetchWikipediaContent(context.Background(), "存在しない記事", "Q1"); err == nil {
		t.Fatal("expected 404 error")
	}
	if requests.Load() != 1 {
		t.Fatalf("non-retryable status must not be retried, got %d requests", requests.Load())
	}
}
