package services

import (
	"context"
	"net/http"
	"net/http/httptest"
	"regexp"
	"sync/atomic"
	"testing"
	"time"
)

func withCommonsBase(t *testing.T, s *httptest.Server) {
	t.Helper()
	orig := commonsAPIBase
	origBackoff := initialBackoff
	commonsAPIBase = s.URL
	initialBackoff = time.Millisecond
	t.Cleanup(func() {
		commonsAPIBase = orig
		initialBackoff = origBackoff
	})
}

func withWikidataBase(t *testing.T, s *httptest.Server) {
	t.Helper()
	orig := wikidataAPIBase
	origBackoff := initialBackoff
	wikidataAPIBase = s.URL
	initialBackoff = time.Millisecond
	t.Cleanup(func() {
		wikidataAPIBase = orig
		initialBackoff = origBackoff
	})
}

func TestFetchWikidataLinks_ExtractsAllProperties(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"entities":{"Q1":{"claims":{
			"P856":[{"mainsnak":{"datavalue":{"value":"https://example.com/"}}}],
			"P2013":[{"mainsnak":{"datavalue":{"value":"examplepage"}}}],
			"P2002":[{"mainsnak":{"datavalue":{"value":"examplehandle"}}}],
			"P2003":[{"mainsnak":{"datavalue":{"value":"exampleinsta"}}}],
			"P2397":[{"mainsnak":{"datavalue":{"value":"UCabc123"}}}]
		}}}}`))
	}))
	defer s.Close()
	withWikidataBase(t, s)

	links, err := FetchWikidataLinks("Q1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if links.OfficialSite != "https://example.com/" {
		t.Errorf("OfficialSite = %q", links.OfficialSite)
	}
	if links.Facebook != "https://www.facebook.com/examplepage" {
		t.Errorf("Facebook = %q", links.Facebook)
	}
	if links.Twitter != "https://x.com/examplehandle" {
		t.Errorf("Twitter = %q", links.Twitter)
	}
	if links.Instagram != "https://www.instagram.com/exampleinsta" {
		t.Errorf("Instagram = %q", links.Instagram)
	}
	if links.YouTube != "https://www.youtube.com/channel/UCabc123" {
		t.Errorf("YouTube = %q", links.YouTube)
	}
}

func TestFetchWikidataLinks_NoLinksReturnsError(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"entities":{"Q2":{"claims":{}}}}`))
	}))
	defer s.Close()
	withWikidataBase(t, s)

	if _, err := FetchWikidataLinks("Q2"); err == nil {
		t.Fatal("expected error when no links are present")
	}
}

func TestFetchWikidataEntity_RetriesOn429ThenSucceeds(t *testing.T) {
	var calls int32
	mux := http.NewServeMux()
	mux.HandleFunc("/w/api.php", func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n <= 2 {
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"entities":{"Q1":{"claims":{"P18":[{"mainsnak":{"datavalue":{"value":"f.jpg"}}}]}}}}`))
	})
	s := httptest.NewServer(mux)
	defer s.Close()
	withWikidataBase(t, s)

	body, err := fetchWikidataEntity(context.Background(), "Q1")
	if err != nil {
		t.Fatalf("expected success after retry, got err: %v", err)
	}
	fileName, err := extractP18FileName(body, "Q1")
	if err != nil || fileName != "f.jpg" {
		t.Errorf("unexpected extracted filename: %q, err: %v", fileName, err)
	}
	if got := atomic.LoadInt32(&calls); got != 3 {
		t.Errorf("expected 3 calls (2 retries + 1 success), got %d", got)
	}
}

func TestFetchWikidataEntity_StopsRetryingOnNonRetryableError(t *testing.T) {
	var calls int32
	mux := http.NewServeMux()
	mux.HandleFunc("/w/api.php", func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, "not found", http.StatusNotFound)
	})
	s := httptest.NewServer(mux)
	defer s.Close()
	withWikidataBase(t, s)

	_, err := fetchWikidataEntity(context.Background(), "Q1")
	if err == nil {
		t.Fatal("expected error for 404, got nil")
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Errorf("404 must not be retried, expected 1 call, got %d", got)
	}
}

func TestFetchWikidataImage_EntityLegTimeoutLeavesBudgetForCommonsLeg(t *testing.T) {
	// The Wikidata leg is permanently rate-limited, so fetchWikidataEntity would retry
	// for up to client.Timeout*4 + backoff on its own. stepTimeout must cut that leg
	// off well before it can eat into the overall budget.
	wikidataServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "rate limited", http.StatusTooManyRequests)
	}))
	defer wikidataServer.Close()
	withWikidataBase(t, wikidataServer)

	origStep := stepTimeout
	stepTimeout = 200 * time.Millisecond
	defer func() { stepTimeout = origStep }()

	origOverall := overallBudget
	overallBudget = 2 * time.Second
	defer func() { overallBudget = origOverall }()

	// withWikidataBase already shrank initialBackoff to 1ms so unrelated retry tests run
	// fast, but that also means the retry loop's own backoff would exhaust all retries
	// well before stepTimeout ever elapses, letting this test pass even with stepTimeout
	// removed entirely. Override it here to something much larger than stepTimeout so the
	// select in fetchWikidataEntity's retry loop can only return via ctx.Done(), which is
	// exactly the behavior stepTimeout is supposed to cause.
	origBackoff := initialBackoff
	initialBackoff = time.Second
	defer func() { initialBackoff = origBackoff }()

	start := time.Now()
	_, _, err := FetchWikidataImage("Q1")
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected error since the Wikidata entity fetch never succeeds")
	}
	// With initialBackoff (1s) far larger than stepTimeout (200ms), fetchWikidataEntity
	// can only return this fast because its ctx.Done() branch fired -- i.e. stepTimeout
	// cut the leg off. Without the per-leg sub-context (ctx bound only to overallBudget),
	// the retry loop would instead ride out the 1s/2s backoffs until overallBudget (2s)
	// itself expired, so this assertion would fail if stepTimeout were removed.
	if elapsed >= overallBudget/2 {
		t.Errorf("FetchWikidataImage took %v, want close to stepTimeout (%v) and well under overallBudget (%v): stepTimeout should have cut off the stuck entity leg via ctx.Done(), not run out the retry backoff", elapsed, stepTimeout, overallBudget)
	}
}

func TestFetchWikidataEntity_RetriesExhausted(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, "rate limited", http.StatusTooManyRequests)
	}))
	defer s.Close()
	withWikidataBase(t, s)

	_, err := fetchWikidataEntity(context.Background(), "Q1")
	if err == nil {
		t.Fatal("expected error after retries exhausted")
	}
	if got := atomic.LoadInt32(&calls); got != maxRetries+1 {
		t.Errorf("expected %d calls (initial + %d retries), got %d", maxRetries+1, maxRetries, got)
	}
}

func TestFetchCommonsImageInfo_RetriesOn429ThenSucceeds(t *testing.T) {
	var calls int32
	mux := http.NewServeMux()
	mux.HandleFunc("/w/api.php", func(w http.ResponseWriter, r *http.Request) {
		n := atomic.AddInt32(&calls, 1)
		if n <= 2 {
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"query":{"pages":{"42":{"imageinfo":[{"thumburl":"https://commons.wikimedia.org/thumb/x/y/f.jpg","url":"https://commons.wikimedia.org/x/y/f.jpg","extmetadata":{"License":{"value":"cc-by-4.0"}}}]}}}}`))
	})
	s := httptest.NewServer(mux)
	defer s.Close()
	withCommonsBase(t, s)

	u, license, err := fetchCommonsImageInfo(context.Background(), "f.jpg")
	if err != nil {
		t.Fatalf("expected success after retry, got err: %v", err)
	}
	if u != "https://commons.wikimedia.org/thumb/x/y/f.jpg" {
		t.Errorf("unexpected thumburl: %q", u)
	}
	if license != "cc-by-4.0" {
		t.Errorf("unexpected license: %q", license)
	}
	if got := atomic.LoadInt32(&calls); got != 3 {
		t.Errorf("expected 3 calls (2 retries + 1 success), got %d", got)
	}
}

func TestFetchCommonsImageInfo_ToleratesArrayExtmetadataValue(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"query":{"pages":{"42":{"imageinfo":[{"thumburl":"https://commons.wikimedia.org/thumb/x/y/f.jpg","url":"https://commons.wikimedia.org/x/y/f.jpg","extmetadata":{"License":[]}}]}}}}`))
	}))
	defer s.Close()
	withCommonsBase(t, s)

	u, license, err := fetchCommonsImageInfo(context.Background(), "f.jpg")
	if err != nil {
		t.Fatalf("expected success despite array-shaped extmetadata, got err: %v", err)
	}
	if u != "https://commons.wikimedia.org/thumb/x/y/f.jpg" {
		t.Errorf("unexpected thumburl: %q", u)
	}
	if license != "" {
		t.Errorf("expected empty license for array-shaped extmetadata, got %q", license)
	}
}

func TestFetchCommonsImageInfo_StopsRetryingOnNonRetryableError(t *testing.T) {
	var calls int32
	mux := http.NewServeMux()
	mux.HandleFunc("/w/api.php", func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, "not found", http.StatusNotFound)
	})
	s := httptest.NewServer(mux)
	defer s.Close()
	withCommonsBase(t, s)

	_, _, err := fetchCommonsImageInfo(context.Background(), "missing.jpg")
	if err == nil {
		t.Fatal("expected error for 404, got nil")
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Errorf("404 must not be retried, expected 1 call, got %d", got)
	}
}

func TestFetchCommonsImageInfo_RetriesExhausted(t *testing.T) {
	var calls int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, "rate limited", http.StatusTooManyRequests)
	}))
	defer s.Close()
	withCommonsBase(t, s)

	_, _, err := fetchCommonsImageInfo(context.Background(), "f.jpg")
	if err == nil {
		t.Fatal("expected error after retries exhausted")
	}
	if got := atomic.LoadInt32(&calls); got != maxRetries+1 {
		t.Errorf("expected %d calls (initial + %d retries), got %d", maxRetries+1, maxRetries, got)
	}
}

func TestParseRetryAfter(t *testing.T) {
	if got := parseRetryAfter(""); got != 0 {
		t.Errorf("empty header: got %v, want 0", got)
	}
	if got := parseRetryAfter("5"); got != 5*time.Second {
		t.Errorf("delta-seconds: got %v, want 5s", got)
	}
	if got := parseRetryAfter(time.Now().Add(3*time.Second).UTC().Format(http.TimeFormat)); got <= 0 || got > 4*time.Second {
		t.Errorf("http-date: got %v, want ~3s", got)
	}
	if got := parseRetryAfter("not-a-number"); got != 0 {
		t.Errorf("garbage: got %v, want 0", got)
	}
	if got := parseRetryAfter("-3"); got != 0 {
		t.Errorf("negative: got %v, want 0", got)
	}
}

func TestStripUTMPreservesPath(t *testing.T) {
	in := "https://commons.wikimedia.org/thumb/x/y/f.jpg?utm_source=web&utm_medium=referral"
	got := stripUTM(in)
	if got != "https://commons.wikimedia.org/thumb/x/y/f.jpg" {
		t.Errorf("stripUTM(%q) = %q", in, got)
	}
	if match, _ := regexp.MatchString("utm_", got); match {
		t.Errorf("unexpected utm param in %q", got)
	}
}
