package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
)

// municipalityTypes are the Wikidata P31 (instance of) classes that identify a
// Japanese municipality whose article can back the 名物/観光 fallback. Wards of
// designated cities (Q137773), 大字, prefectures and regions are deliberately
// absent: wards are climbed through to their city, and the rest never match.
var municipalityTypes = map[string]bool{
	"Q494721":  true, // 市
	"Q1059478": true, // 町
	"Q4174776": true, // 村
	"Q5327704": true, // 特別区
	"Q1137833": true, // 中核市
	"Q1145012": true, // 特例市
	"Q1749269": true, // 政令指定都市
}

// maxMunicipalityHops bounds how many P131 links are followed from the spring
// item before giving up (spring → 大字 → 区 → 市 is the deepest observed chain).
const maxMunicipalityHops = 3

// municipalityTitleCache memoizes QID → municipality article title ("" when
// unresolvable). Only successful lookups are stored so transient API failures
// are retried on the next request.
var municipalityTitleCache sync.Map

// MunicipalityFallbackDisabled reports whether ONSEN_MUNICIPALITY_FALLBACK_DISABLE
// turns off filling empty 名物/観光 sections from the municipality article.
func MunicipalityFallbackDisabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("ONSEN_MUNICIPALITY_FALLBACK_DISABLE"))) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

// wikidataPlace is the subset of a Wikidata item needed to climb P131 towards a
// municipality: its P31 classes, P131 targets, and jawiki sitelink title.
type wikidataPlace struct {
	instanceOf []string
	partOf     []string
	jawiki     string
}

// resolveMunicipalityTitle resolves a hot-spring Wikidata QID to the Japanese
// Wikipedia article title of the municipality it lies in. It follows P131 up
// to maxMunicipalityHops items and accepts the first one whose P31 is a
// municipality class, taking the title from its jawiki sitelink (labels can
// differ from article titles, e.g. disambiguated town names). Returns "" when
// no municipality with a jawiki article is reached, which callers treat as "no
// fallback article" rather than an error.
func resolveMunicipalityTitle(ctx context.Context, qid string) (string, error) {
	if cached, ok := municipalityTitleCache.Load(qid); ok {
		return cached.(string), nil
	}
	title, err := walkToMunicipality(ctx, qid)
	if err != nil {
		return "", err
	}
	municipalityTitleCache.Store(qid, title)
	return title, nil
}

// walkToMunicipality searches the P131 graph breadth-first. Items often carry
// several P131 statements in no useful order (e.g. 宮城県, 柴田郡, 川崎町), so
// every target of a level is checked before climbing further; within a level
// the first municipality in statement order wins. An ancestor that cannot be
// read for a permanent reason is skipped rather than failing the whole walk.
func walkToMunicipality(ctx context.Context, qid string) (string, error) {
	place, err := fetchWikidataPlace(ctx, qid)
	if err != nil {
		return "", err
	}
	visited := map[string]bool{qid: true}
	frontier := place.partOf
	for hop := 0; hop < maxMunicipalityHops && len(frontier) > 0; hop++ {
		var next []string
		for _, id := range frontier {
			if visited[id] {
				continue
			}
			visited[id] = true
			place, err := fetchWikidataPlace(ctx, id)
			if err != nil {
				// A transient failure must not be cached as "no municipality";
				// a permanent one (e.g. a P131 target merged into another
				// item) only rules out this branch, not its siblings.
				if IsTransientWikimediaError(err) {
					return "", err
				}
				continue
			}
			for _, class := range place.instanceOf {
				if municipalityTypes[class] && place.jawiki != "" {
					return place.jawiki, nil
				}
			}
			next = append(next, place.partOf...)
		}
		frontier = next
	}
	return "", nil
}

func fetchWikidataPlace(ctx context.Context, qid string) (wikidataPlace, error) {
	return withRetry(ctx, "Wikidata place", func() (wikidataPlace, error) {
		return fetchWikidataPlaceOnce(ctx, qid)
	})
}

// fetchWikidataPlaceOnce fetches claims and the jawiki sitelink of one item via
// wbgetentities.
func fetchWikidataPlaceOnce(ctx context.Context, qid string) (wikidataPlace, error) {
	params := url.Values{
		"action":     {"wbgetentities"},
		"ids":        {qid},
		"props":      {"claims|sitelinks"},
		"sitefilter": {"jawiki"},
		"format":     {"json"},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, wikidataAPIBase+"/w/api.php?"+params.Encode(), nil)
	if err != nil {
		return wikidataPlace{}, err
	}
	req.Header.Set("User-Agent", wikimediaUserAgent)
	resp, err := client.Do(req)
	if err != nil {
		return wikidataPlace{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return wikidataPlace{}, &apiStatusError{status: resp.StatusCode, retryAfter: parseRetryAfter(resp.Header.Get("Retry-After"))}
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return wikidataPlace{}, fmt.Errorf("failed to read response: %w", err)
	}
	return parseWikidataPlace(body, qid)
}

// parseWikidataPlace returns a zero place, not an error, when the response has
// no entity under qid (a merged item answered under its redirect target, for
// instance): that is a permanent dead end the walk skips, and an error here
// would be treated as retryable and never cached.
func parseWikidataPlace(body []byte, qid string) (wikidataPlace, error) {
	var data struct {
		Entities map[string]struct {
			Sitelinks map[string]struct {
				Title string `json:"title"`
			} `json:"sitelinks"`
		} `json:"entities"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return wikidataPlace{}, fmt.Errorf("failed to parse Wikidata sitelinks: %w", err)
	}
	entity, ok := data.Entities[qid]
	if !ok {
		return wikidataPlace{}, nil
	}
	claims, err := extractClaims(body, qid)
	if err != nil {
		return wikidataPlace{}, err
	}
	return wikidataPlace{
		instanceOf: claimEntityIDs(claims, "P31"),
		partOf:     claimEntityIDs(claims, "P131"),
		jawiki:     entity.Sitelinks["jawiki"].Title,
	}, nil
}

// claimEntityIDs returns the Wikibase-entity target IDs (e.g. "Q123") of the
// statements for the given property, in statement order. It complements
// firstClaimString, which only reads string-typed values.
func claimEntityIDs(claims map[string]interface{}, property string) []string {
	var ids []string
	stmts, _ := claims[property].([]interface{})
	for _, s := range stmts {
		stmt, _ := s.(map[string]interface{})
		mainsnak, _ := stmt["mainsnak"].(map[string]interface{})
		datavalue, _ := mainsnak["datavalue"].(map[string]interface{})
		if dvType, _ := datavalue["type"].(string); dvType != "wikibase-entityid" {
			continue
		}
		value, _ := datavalue["value"].(map[string]interface{})
		if id, _ := value["id"].(string); id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}
