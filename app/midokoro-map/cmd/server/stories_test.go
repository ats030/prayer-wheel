package main

import (
	"bytes"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestStoryPageIsReadableWithoutJavaScript(t *testing.T) {
	mux := http.NewServeMux()
	registerStoryRoutes(mux, "../../frontend")
	for _, method := range []string{"GET", "HEAD"} {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest(method, "/stories/arita-porcelain?from=shared&place=izumiyama", nil))
		if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" || !strings.Contains(w.Header().Get("Content-Type"), "text/html") {
			t.Fatalf("%s: %d %v", method, w.Code, w.Header())
		}
		if method == "HEAD" {
			if w.Body.Len() != 0 {
				t.Fatal("HEAD returned a body")
			}
			continue
		}
		for _, text := range []string{"泉山磁石場", "天狗谷窯跡", "トンバイ塀", "陶山神社", "有田陶磁美術館", "伝承を含む関係", "未確認", "data-site=\"midokoro-map\"", "rel=\"canonical\"", "https://www.town.arita.lg.jp/"} {
			if !strings.Contains(w.Body.String(), text) {
				t.Fatalf("missing static content: %s", text)
			}
		}
	}
	for _, path := range []string{"/stories/arita-porcelain/", "/stories/arita-porcelain/unknown", "/stories/missing"} {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
		if w.Code != 404 {
			t.Fatalf("%s: %d", path, w.Code)
		}
	}
}

func TestStoryEventsRejectArbitraryInput(t *testing.T) {
	mux := http.NewServeMux()
	registerStoryRoutes(mux, "../../frontend")
	var output bytes.Buffer
	previous := log.Writer()
	log.SetOutput(&output)
	defer log.SetOutput(previous)
	const prefix = "/api/story-events/arita-porcelain/"
	cases := []struct {
		method, path, site, body string
		want                     int
	}{
		{"POST", "follow", "same-origin", "", 204},
		{"GET", "view", "same-origin", "", 405},
		{"OPTIONS", "view", "cross-site", "", 405},
		{"POST", "unknown", "same-origin", "", 404},
		{"POST", "view?email=private@example.com", "same-origin", "", 404},
		{"POST", "view", "cross-site", "", 403},
		{"POST", "view", "same-site", "", 403},
		{"POST", "view", "same-origin", "private body", 400},
		{"POST", "view/other", "same-origin", "", 404},
	}
	for _, tc := range cases {
		r := httptest.NewRequest(tc.method, prefix+tc.path, strings.NewReader(tc.body))
		r.Header.Set("Sec-Fetch-Site", tc.site)
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		if w.Code != tc.want {
			t.Fatalf("%s %s: %d want %d", tc.method, tc.path, w.Code, tc.want)
		}
		if w.Header().Get("Cache-Control") != "no-store" {
			t.Fatal("events must not be cached")
		}
	}
	if strings.Count(output.String(), "story_event") != 1 || !strings.Contains(output.String(), "event=follow") || strings.Contains(output.String(), "private") {
		t.Fatalf("unexpected application logs: %s", output.String())
	}
}

func TestAdditionalStoryThemes(t *testing.T) {
	mux := http.NewServeMux()
	registerStoryRoutes(mux, "../../frontend")
	for _, slug := range storySlugs {
		t.Run(slug, func(t *testing.T) {
			w := httptest.NewRecorder()
			mux.ServeHTTP(w, httptest.NewRequest("GET", "/stories/"+slug, nil))
			body := w.Body.String()
			if w.Code != 200 || strings.Count(body, "data-number=") != 5 || strings.Count(body, "data-from=") != 5 || !strings.Contains(body, `data-story="`+slug+`"`) {
				t.Fatalf("invalid theme %s: status=%d", slug, w.Code)
			}
			w = httptest.NewRecorder()
			mux.ServeHTTP(w, httptest.NewRequest("POST", "/api/story-events/"+slug+"/view", nil))
			if w.Code != 204 {
				t.Fatalf("event status=%d", w.Code)
			}
			w = httptest.NewRecorder()
			mux.ServeHTTP(w, httptest.NewRequest("POST", "/stories/"+slug, nil))
			if w.Code != 405 {
				t.Fatalf("page POST status=%d", w.Code)
			}
		})
	}
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, httptest.NewRequest("GET", "/stories", nil))
	for _, slug := range storySlugs {
		if !strings.Contains(w.Body.String(), "/stories/"+slug+"?from=home") {
			t.Fatal("missing theme entry: " + slug)
		}
	}
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, httptest.NewRequest("POST", "/api/story-events/unknown/view", nil))
	if w.Code != 404 {
		t.Fatalf("unknown story status=%d", w.Code)
	}
}
