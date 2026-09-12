package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

var client = &http.Client{Timeout: 10 * time.Second}

const maxRetries = 3

// initialBackoff is the delay before the first Commons API retry. Tests override it with
// a smaller value; the production value is time.Second.
var initialBackoff = time.Second

// commonsAPIBase is the prefix of every Commons API request. Tests replace it with a
// local httptest server.
var commonsAPIBase = "https://commons.wikimedia.org"

// wikidataAPIBase is the prefix of every Wikidata API request. Tests replace it with a
// local httptest server.
var wikidataAPIBase = "https://www.wikidata.org"

// FetchWikidataImage resolves a Wikidata QID to a Commons thumbnail URL and its SPDX license.
//
// It first pulls the P18 (image) claim from Wikidata, then asks the Commons API for the
// authoritative thumbnail URL and license. Building the thumbnail URL by hand is incorrect
// because the /thumb/<dir1>/<dir2>/ path is an MD5 hash of the filename, so the URL must be
// read from the API response instead of recomputed.
func FetchWikidataImage(qid string) (string, string, error) {
	// Wikidata/Commons responses are occasionally slow enough (measured up to ~11s per
	// call) that a single retried leg can approach 20s on its own; since this function
	// makes two such calls sequentially, the overall budget must give both legs enough
	// room even when one of them needs a retry.
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()

	body, err := fetchWikidataEntity(ctx, qid)
	if err != nil {
		return "", "", err
	}

	fileName, err := extractP18FileName(body, qid)
	if err != nil {
		return "", "", err
	}

	thumbURL, license, err := fetchCommonsImageInfo(ctx, fileName)
	if err != nil {
		return "", "", fmt.Errorf("no usable image for %s: %w", qid, err)
	}
	if thumbURL == "" {
		return "", "", fmt.Errorf("no usable image for %s: Commons returned no image info", qid)
	}
	return thumbURL, license, nil
}

// fetchWikidataEntity fetches the raw wbgetentities claims payload for a QID.
//
// Transient failures (HTTP 429 rate limiting, 5xx responses, and network errors) are
// retried up to maxRetries times with exponential backoff, mirroring fetchCommonsImageInfo.
func fetchWikidataEntity(ctx context.Context, qid string) ([]byte, error) {
	backoff := initialBackoff
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			log.Printf("omatsuri-map: Wikidata API retry %d/%d for %s (last error: %v)", attempt, maxRetries, qid, lastErr)
		}

		body, err := fetchWikidataEntityOnce(ctx, qid)
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

		_, retryAfter, _ := statusFromError(err)
		if retryAfter > 0 {
			backoff = retryAfter
		}

		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return nil, err
		}
		backoff *= 2
	}

	log.Printf("omatsuri-map: Wikidata API retries exhausted for %s: %v", qid, lastErr)
	return nil, lastErr
}

func fetchWikidataEntityOnce(ctx context.Context, qid string) ([]byte, error) {
	wikidataURL := fmt.Sprintf(
		"%s/w/api.php?action=wbgetentities&ids=%s&props=claims&format=json",
		wikidataAPIBase,
		url.QueryEscape(qid),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, wikidataURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("User-Agent", "omatsuri-map/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch from Wikidata: %w", err)
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

// WikidataLinks holds official website and social media links resolved from a Wikidata entity.
type WikidataLinks struct {
	OfficialSite string `json:"official_site,omitempty"`
	Facebook     string `json:"facebook,omitempty"`
	Twitter      string `json:"twitter,omitempty"`
	Instagram    string `json:"instagram,omitempty"`
	YouTube      string `json:"youtube,omitempty"`
}

// FetchWikidataLinks resolves a Wikidata QID to its official website (P856) and official
// social media accounts (P2013 Facebook, P2002 X/Twitter, P2003 Instagram, P2397 YouTube
// channel), converting each SNS claim into a direct profile URL.
func FetchWikidataLinks(qid string) (WikidataLinks, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	body, err := fetchWikidataEntity(ctx, qid)
	if err != nil {
		return WikidataLinks{}, err
	}

	claims, err := extractClaims(body, qid)
	if err != nil {
		return WikidataLinks{}, err
	}

	links := WikidataLinks{
		OfficialSite: firstClaimString(claims, "P856"),
	}
	if id := firstClaimString(claims, "P2013"); id != "" {
		links.Facebook = "https://www.facebook.com/" + id
	}
	if id := firstClaimString(claims, "P2002"); id != "" {
		links.Twitter = "https://x.com/" + id
	}
	if id := firstClaimString(claims, "P2003"); id != "" {
		links.Instagram = "https://www.instagram.com/" + id
	}
	if id := firstClaimString(claims, "P2397"); id != "" {
		links.YouTube = "https://www.youtube.com/channel/" + id
	}

	if links == (WikidataLinks{}) {
		return WikidataLinks{}, fmt.Errorf("no official site or social links found for %s", qid)
	}
	return links, nil
}

func extractP18FileName(body []byte, qid string) (string, error) {
	claims, err := extractClaims(body, qid)
	if err != nil {
		return "", err
	}
	if v := firstClaimString(claims, "P18"); v != "" {
		return v, nil
	}
	return "", fmt.Errorf("no image found for QID %s", qid)
}

// extractClaims pulls the "claims" object out of a wbgetentities response for the given QID.
func extractClaims(body []byte, qid string) (map[string]interface{}, error) {
	var data map[string]interface{}
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, fmt.Errorf("failed to parse Wikidata response: %w", err)
	}
	var entity map[string]interface{}
	if entities, ok := data["entities"].(map[string]interface{}); ok {
		entity, _ = entities[qid].(map[string]interface{})
	}
	if entity == nil {
		return nil, fmt.Errorf("QID %s not found in Wikidata", qid)
	}
	claims, _ := entity["claims"].(map[string]interface{})
	return claims, nil
}

// firstClaimString returns the string value of the first statement for the given property,
// or "" if the property has no statements or its value is not a string.
func firstClaimString(claims map[string]interface{}, property string) string {
	stmts, _ := claims[property].([]interface{})
	for _, s := range stmts {
		stmt, _ := s.(map[string]interface{})
		mainsnak, _ := stmt["mainsnak"].(map[string]interface{})
		datavalue, _ := mainsnak["datavalue"].(map[string]interface{})
		if v, _ := datavalue["value"].(string); v != "" {
			return v
		}
	}
	return ""
}

// apiStatusError wraps a non-200 HTTP status so retry policy can be applied based on it.
type apiStatusError struct {
	status     int
	retryAfter time.Duration
}

func (e *apiStatusError) Error() string {
	return fmt.Sprintf("API returned status %d", e.status)
}

func statusFromError(err error) (int, time.Duration, bool) {
	var statusErr *apiStatusError
	if errors.As(err, &statusErr) {
		return statusErr.status, statusErr.retryAfter, true
	}
	return 0, 0, false
}

// fetchCommonsImageInfo asks the Commons API for the thumbnail URL (at 800px width) and the
// SPDX license id in a single call. The thumbnail URL is authoritative: the /thumb/ subpath
// is an MD5 hash of the filename that cannot be derived locally. The UTM query params the
// API appends are stripped so downstream <img src> and onerror swaps stay clean.
//
// Transient failures (HTTP 429 rate limiting, 5xx responses, and network errors) are
// retried up to maxRetries times with exponential backoff. A Retry-After response value
// takes precedence over the calculated backoff.
func fetchCommonsImageInfo(ctx context.Context, fileName string) (string, string, error) {
	backoff := initialBackoff
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			log.Printf("omatsuri-map: Commons API retry %d/%d for %s (last error: %v)", attempt, maxRetries, fileName, lastErr)
		}

		u, license, err := fetchCommonsImageInfoOnce(ctx, fileName)
		if err == nil {
			return u, license, nil
		}
		lastErr = err

		if !isRetryableAPIError(err) {
			return "", "", err
		}
		if attempt == maxRetries {
			break
		}

		_, retryAfter, _ := statusFromError(err)
		if retryAfter > 0 {
			backoff = retryAfter
		}

		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return "", "", err
		}
		backoff *= 2
	}

	log.Printf("omatsuri-map: Commons API retries exhausted for %s: %v", fileName, lastErr)
	return "", "", lastErr
}

func isRetryableAPIError(err error) bool {
	if err == nil {
		return false
	}
	status, _, ok := statusFromError(err)
	if !ok {
		return true
	}
	return status == http.StatusTooManyRequests || status >= http.StatusInternalServerError
}

// extValue holds one extmetadata entry's "value" field. The Commons API normally
// returns an object ({"value": "..."}), but occasionally returns an empty array
// ([]) for a missing field; UnmarshalJSON tolerates that shape by leaving Value empty
// instead of failing the whole response.
type extValue struct {
	Value string
}

func (v *extValue) UnmarshalJSON(data []byte) error {
	var obj struct {
		Value string `json:"value"`
	}
	if err := json.Unmarshal(data, &obj); err == nil {
		v.Value = obj.Value
		return nil
	}
	trimmed := strings.TrimSpace(string(data))
	if strings.HasPrefix(trimmed, "[") {
		v.Value = ""
		return nil
	}
	return fmt.Errorf("extmetadata value: unsupported shape %s", trimmed)
}

func fetchCommonsImageInfoOnce(ctx context.Context, fileName string) (string, string, error) {
	apiURL := fmt.Sprintf(
		"%s/w/api.php?action=query&titles=File:%s&prop=imageinfo&iiprop=url|extmetadata|size&iiextmetadatafilter=License&iiurlwidth=800&format=json",
		commonsAPIBase,
		url.QueryEscape(strings.ReplaceAll(fileName, " ", "_")),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL, nil)
	if err != nil {
		return "", "", err
	}
	req.Header.Set("User-Agent", "omatsuri-map/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", "", &apiStatusError{status: resp.StatusCode, retryAfter: parseRetryAfter(resp.Header.Get("Retry-After"))}
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", err
	}

	var data struct {
		Query struct {
			Pages map[string]struct {
				Missing   bool `json:"missing"`
				ImageInfo []struct {
					ThumbURL    string             `json:"thumburl"`
					URL         string             `json:"url"`
					Extmetadata map[string]extValue `json:"extmetadata"`
				} `json:"imageinfo"`
			} `json:"pages"`
		} `json:"query"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return "", "", err
	}

	for _, page := range data.Query.Pages {
		if page.Missing {
			continue
		}
		for _, info := range page.ImageInfo {
			u := info.ThumbURL
			if u == "" {
				u = info.URL
			}
			if u == "" {
				continue
			}
			license := ""
			if lic, ok := info.Extmetadata["License"]; ok {
				license = lic.Value
			}
			return stripUTM(u), license, nil
		}
	}
	return "", "", nil
}

// parseRetryAfter converts a Retry-After header value (delta-seconds or HTTP-date)
// into a duration. Returns 0 when the header is absent or unparsable.
func parseRetryAfter(value string) time.Duration {
	if value == "" {
		return 0
	}
	if seconds, err := strconv.Atoi(value); err == nil && seconds > 0 {
		return time.Duration(seconds) * time.Second
	}
	if ts, err := http.ParseTime(value); err == nil {
		if d := time.Until(ts); d > 0 {
			return d
		}
	}
	return 0
}

func stripUTM(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return rawURL
	}
	u.RawQuery = ""
	u.Fragment = ""
	return u.String()
}
