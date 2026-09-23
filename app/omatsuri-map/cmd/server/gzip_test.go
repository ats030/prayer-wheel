package main

import (
	"compress/gzip"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestGzipMiddlewareCompressesJSON(t *testing.T) {
	body := strings.Repeat(`{"label_ja":"祭り"},`, 500)
	h := gzipMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Length", "999")
		io.WriteString(w, body)
	}))
	req := httptest.NewRequest(http.MethodGet, "/api/festivals/", nil)
	req.Header.Set("Accept-Encoding", "br, gzip")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Header().Get("Content-Encoding") != "gzip" || rec.Header().Get("Content-Length") != "" {
		t.Fatalf("headers = %v", rec.Header())
	}
	zr, err := gzip.NewReader(rec.Body)
	if err != nil {
		t.Fatal(err)
	}
	got, _ := io.ReadAll(zr)
	if string(got) != body {
		t.Fatalf("decompressed body mismatch")
	}
}

func TestGzipMiddlewarePassThrough(t *testing.T) {
	cases := []struct {
		name, encoding, contentType string
		status                      int
	}{
		{"no accept", "", "application/json", http.StatusOK},
		{"q zero", "gzip;q=0", "application/json", http.StatusOK},
		{"binary", "gzip", "image/png", http.StatusOK},
		{"not modified", "gzip", "application/json", http.StatusNotModified},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			h := gzipMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", tc.contentType)
				w.WriteHeader(tc.status)
				io.WriteString(w, "plain")
			}))
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.Header.Set("Accept-Encoding", tc.encoding)
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Header().Get("Content-Encoding") != "" || rec.Body.String() != "plain" {
				t.Fatalf("encoding=%q body=%q", rec.Header().Get("Content-Encoding"), rec.Body.String())
			}
		})
	}
}
