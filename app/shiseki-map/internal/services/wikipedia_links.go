package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

// jaWikipediaBase is the prefix for Japanese Wikipedia API requests. Tests replace it
// with a local httptest server.
var jaWikipediaBase = "https://ja.wikipedia.org"

var (
	extLinkBracketRE = regexp.MustCompile(`\|\s*外部リンク\s*=\s*\[\s*(https?://[^\s\[\]\|]+)`)
	extLinkPlainRE   = regexp.MustCompile(`\|\s*外部リンク\s*=\s*(https?://[^\s\|\n]+)`)
	httpURLRE        = regexp.MustCompile(`https?://[^\s\[\]\|>]+`)
)

// fallbackOfficialSite returns the first official-site candidate URL found in the
// Japanese Wikipedia article that is linked from the given Wikidata item, or "" when the
// item has no Japanese article or the article exposes no usable external link. It is used
// as a last resort when the item carries no P856 (official website) claim.
func fallbackOfficialSite(ctx context.Context, qid string) (string, error) {
	title, err := resolveJawikiTitle(ctx, qid)
	if err != nil {
		return "", err
	}
	if title == "" {
		return "", nil
	}
	wikitext, err := fetchJawikiWikitext(ctx, title)
	if err != nil {
		return "", err
	}
	return extractOfficialSite(wikitext), nil
}

// resolveJawikiTitle returns the Japanese Wikipedia article title for a Wikidata item by
// reading its sitelinks, or "" when no Japanese article exists. Reading the title from the
// item's own sitelinks guarantees the resolved article is the one that item points to,
// avoiding label/alias mismatches.
func resolveJawikiTitle(ctx context.Context, qid string) (string, error) {
	apiURL := fmt.Sprintf("%s/w/api.php?action=wbgetentities&ids=%s&props=sitelinks&format=json",
		wikidataAPIBase, url.QueryEscape(qid))
	body, err := fetchAPI(ctx, apiURL)
	if err != nil {
		return "", err
	}
	var data struct {
		Entities map[string]struct {
			Sitelinks map[string]struct {
				Title string `json:"title"`
			} `json:"sitelinks"`
		} `json:"entities"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return "", fmt.Errorf("failed to parse sitelinks response: %w", err)
	}
	if entity, ok := data.Entities[qid]; ok {
		if sl, ok := entity.Sitelinks["jawiki"]; ok {
			return strings.TrimSpace(sl.Title), nil
		}
	}
	return "", nil
}

// fetchJawikiWikitext fetches the raw wikitext of a Japanese Wikipedia article.
func fetchJawikiWikitext(ctx context.Context, title string) (string, error) {
	apiURL := fmt.Sprintf("%s/w/api.php?action=parse&page=%s&prop=wikitext&format=json&formatversion=2&redirects=1",
		jaWikipediaBase, url.QueryEscape(title))
	body, err := fetchAPI(ctx, apiURL)
	if err != nil {
		return "", err
	}
	var data struct {
		Parse struct {
			Wikitext string `json:"wikitext"`
		} `json:"parse"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return "", fmt.Errorf("failed to parse wikitext response: %w", err)
	}
	return data.Parse.Wikitext, nil
}

// extractOfficialSite pulls the first official-site URL candidate out of a wikitext body.
// It prefers the infobox 外部リンク field (bracketed or plain URL form) and falls back to
// the first plausible link in an 外部リンク section. Non-official hosts (Wikipedia,
// Wikimedia, Wikivoyage) are ignored.
func extractOfficialSite(wikitext string) string {
	if m := extLinkBracketRE.FindStringSubmatch(wikitext); len(m) == 2 && isOfficialHost(m[1]) {
		return strings.TrimRight(m[1], ",;")
	}
	if m := extLinkPlainRE.FindStringSubmatch(wikitext); len(m) == 2 && isOfficialHost(m[1]) {
		return strings.TrimRight(m[1], ",;")
	}
	if idx := strings.Index(wikitext, "外部リンク"); idx >= 0 {
		rest := wikitext[idx:]
		if len(rest) > 600 {
			rest = rest[:600]
		}
		if m := httpURLRE.FindStringSubmatch(rest); len(m) == 1 && isOfficialHost(m[0]) {
			return strings.TrimRight(m[0], ",;")
		}
	}
	return ""
}

func isOfficialHost(rawURL string) bool {
	u, err := url.Parse(rawURL)
	if err != nil {
		return false
	}
	host := strings.ToLower(u.Hostname())
	if host == "" {
		return false
	}
	if host == "wikipedia.org" || strings.HasSuffix(host, ".wikipedia.org") {
		return false
	}
	if host == "wikimedia.org" || strings.HasSuffix(host, ".wikimedia.org") {
		return false
	}
	if host == "wikivoyage.org" || strings.HasSuffix(host, ".wikivoyage.org") {
		return false
	}
	return true
}

// fetchAPI performs a GET and reads the body, retrying transient failures (HTTP 429, 5xx,
// and network errors) with exponential backoff identical to the other wikimedia-family
// callers in this package.
func fetchAPI(ctx context.Context, rawURL string) ([]byte, error) {
	backoff := initialBackoff
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			log.Printf("shiseki-map: links API retry %d/%d (last error: %v)", attempt, maxRetries, lastErr)
		}

		body, err := fetchAPIOnce(ctx, rawURL)
		if err == nil {
			return body, nil
		}
		lastErr = err

		if !isRetryableAPIError(err) {
			return nil, err
		}
		if attempt == maxRetries {
			break
		}
		if _, retryAfter, ok := statusFromError(err); ok && retryAfter > 0 {
			backoff = retryAfter
		}
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return nil, err
		}
		backoff *= 2
	}
	return nil, lastErr
}

func fetchAPIOnce(ctx context.Context, rawURL string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("User-Agent", wikimediaUserAgent)

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch link source: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, &apiStatusError{status: resp.StatusCode, retryAfter: parseRetryAfter(resp.Header.Get("Retry-After"))}
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}
	return body, nil
}
