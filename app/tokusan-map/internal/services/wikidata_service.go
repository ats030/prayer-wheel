package services

import (
	"bytes"
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
	"unicode"
)

var client = &http.Client{Timeout: 10 * time.Second}

const maxRetries = 3

var initialBackoff = time.Second
var overallBudget = 45 * time.Second
var stepTimeout = 22 * time.Second
var commonsAPIBase = "https://commons.wikimedia.org"
var wikidataAPIBase = "https://www.wikidata.org"

// FetchWikidataImage resolves a Wikidata QID to a Commons thumbnail URL and its SPDX license.
//
// It first pulls the P18 (image) claim from Wikidata, then asks the Commons API for the
// authoritative thumbnail URL and license. The /thumb/<dir1>/<dir2>/ path is an MD5 hash of
// the filename, so the URL must be read from the API response instead of recomputed.
func FetchWikidataImage(qid string) (string, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), overallBudget)
	defer cancel()

	entityCtx, entityCancel := context.WithTimeout(ctx, stepTimeout)
	defer entityCancel()
	body, err := fetchWikidataEntity(entityCtx, qid)
	if err != nil {
		return "", "", err
	}

	fileName := ""
	if p18, perr := extractP18FileName(body, qid); perr == nil && p18 != "" {
		fileName = p18
	} else if cat, cerr := extractP373Category(body, qid); cerr == nil && cat != "" {
		fctx, fcancel := context.WithTimeout(ctx, stepTimeout)
		defer fcancel()
		fileName = pickCommonsCategoryFile(fctx, cat)
	}
	if fileName == "" {
		return "", "", fmt.Errorf("no image found for QID %s (P18 and P373 fallback both empty)", qid)
	}

	commonsCtx, commonsCancel := context.WithTimeout(ctx, stepTimeout)
	defer commonsCancel()
	thumbURL, license, err := fetchCommonsImageInfo(commonsCtx, fileName)
	if err != nil {
		return "", "", fmt.Errorf("no usable image for %s: %w", qid, err)
	}
	if thumbURL == "" {
		return "", "", fmt.Errorf("no usable image for %s: Commons returned no image info", qid)
	}
	return thumbURL, license, nil
}

func fetchWikidataEntity(ctx context.Context, qid string) ([]byte, error) {
	backoff := initialBackoff
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			log.Printf("tokusan-map: Wikidata API retry %d/%d for %s (last error: %v)", attempt, maxRetries, qid, lastErr)
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

	log.Printf("tokusan-map: Wikidata API retries exhausted for %s: %v", qid, lastErr)
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
	req.Header.Set("User-Agent", wikimediaUserAgent)

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

// extractP373Category returns the P373 (Commons category) claim value if present.
func extractP373Category(body []byte, qid string) (string, error) {
	claims, err := extractClaims(body, qid)
	if err != nil {
		return "", err
	}
	if v := firstClaimString(claims, "P373"); v != "" {
		return v, nil
	}
	return "", fmt.Errorf("no P373 category found for QID %s", qid)
}

// imageExtensions are the file extensions we consider usable as a product photo.
var imageExtensions = []string{".jpg", ".jpeg", ".png", ".svg", ".webp", ".gif"}

func isImageFile(title string) bool {
	lower := strings.ToLower(title)
	for _, ext := range imageExtensions {
		if strings.HasSuffix(lower, ext) {
			return true
		}
	}
	return false
}

// categoryWords extracts lowercase Latin word tokens from a Commons category name,
// dropping short tokens that carry no identifying signal (e.g. "of", "in").
func categoryWords(category string) []string {
	var words []string
	for _, w := range strings.FieldsFunc(strings.ToLower(category), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	}) {
		if len(w) < 3 {
			continue
		}
		words = append(words, w)
	}
	return words
}

// pickCommonsCategoryFile picks the image in the given Commons category whose name
// best matches the category. Files matching none of the category's tokens are
// rejected so we never surface an unrelated photo (e.g. the wrong building).
func pickCommonsCategoryFile(ctx context.Context, category string) string {
	u := fmt.Sprintf(
		"%s/w/api.php?action=query&list=categorymembers&cmtitle=%s&cmtype=file&cmlimit=100&format=json&subcats=1",
		commonsAPIBase,
		url.QueryEscape("Category:"+category),
	)
	var candidates []string
	backoff := initialBackoff
	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			log.Printf("tokusan-map: Commons category lookup retry %d/%d for %s", attempt, maxRetries, category)
			select {
			case <-time.After(backoff):
			case <-ctx.Done():
				return ""
			}
			backoff *= 2
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
		if err != nil {
			return ""
		}
		req.Header.Set("User-Agent", wikimediaUserAgent)
		resp, err := client.Do(req)
		if err != nil {
			continue
		}
		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			continue
		}
		if resp.StatusCode != http.StatusOK {
			if !isRetryableAPIError(&apiStatusError{status: resp.StatusCode}) {
				return ""
			}
			continue
		}
		var data struct {
			Query struct {
				CategoryMembers []struct {
					Title string `json:"title"`
				} `json:"categorymembers"`
			} `json:"query"`
		}
		if err := json.Unmarshal(body, &data); err != nil {
			continue
		}
		candidates = make([]string, 0, len(data.Query.CategoryMembers))
		for _, m := range data.Query.CategoryMembers {
			if !isImageFile(m.Title) {
				continue
			}
			candidates = append(candidates, strings.TrimPrefix(m.Title, "File:"))
		}
		break
	}
	if len(candidates) == 0 {
		return ""
	}

	words := categoryWords(category)
	bestName := ""
	bestScore := 0
	for _, name := range candidates {
		score := 0
		lower := strings.ToLower(name)
		for _, w := range words {
			if strings.Contains(lower, w) {
				score++
			}
		}
		if score > bestScore {
			bestScore = score
			bestName = name
		}
	}
	if bestScore == 0 {
		// No file reliably associated with this category; refuse to guess.
		return ""
	}
	return bestName
}

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

func fetchCommonsImageInfo(ctx context.Context, fileName string) (string, string, error) {
	backoff := initialBackoff
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			log.Printf("tokusan-map: Commons API retry %d/%d for %s (last error: %v)", attempt, maxRetries, fileName, lastErr)
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

	log.Printf("tokusan-map: Commons API retries exhausted for %s: %v", fileName, lastErr)
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
// ([]) for a missing field; UnmarshalJSON tolerates that shape.
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

// decodeExtmetadata parses the raw "extmetadata" value of an imageinfo entry into
// a Go map of field name to value. The Commons API usually returns an object keyed
// by field name, but when the requested filter matches no field it returns an
// empty array ([]); both shapes are tolerated and normalized to an empty map.
func decodeExtmetadata(raw json.RawMessage) map[string]extValue {
	out := map[string]extValue{}
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || trimmed[0] != '{' {
		return out
	}
	if err := json.Unmarshal(trimmed, &out); err != nil {
		return out
	}
	return out
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
	req.Header.Set("User-Agent", wikimediaUserAgent)

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
					ThumbURL    string          `json:"thumburl"`
					URL         string          `json:"url"`
					Extmetadata json.RawMessage `json:"extmetadata"`
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
			if lic, ok := decodeExtmetadata(info.Extmetadata)["License"]; ok {
				license = lic.Value
			}
			return stripUTM(u), license, nil
		}
	}
	return "", "", nil
}

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
