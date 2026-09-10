package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

var client = &http.Client{Timeout: 10 * time.Second}

// FetchWikidataImage resolves a Wikidata QID to a Commons thumbnail URL and its SPDX license.
//
// It first pulls the P18 (image) claim from Wikidata, then asks the Commons API for the
// authoritative thumbnail URL and license. Building the thumbnail URL by hand is incorrect
// because the /thumb/<dir1>/<dir2>/ path is an MD5 hash of the filename, so the URL must be
// read from the API response instead of recomputed.
func FetchWikidataImage(qid string) (string, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	wikidataURL := fmt.Sprintf(
		"https://www.wikidata.org/w/api.php?action=wbgetentities&ids=%s&props=claims&format=json",
		url.QueryEscape(qid),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, wikidataURL, nil)
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("User-Agent", "omatsuri-map/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("failed to fetch from Wikidata: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", "", fmt.Errorf("Wikidata API returned status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to read response: %w", err)
	}

	fileName, err := extractP18FileName(body, qid)
	if err != nil {
		return "", "", err
	}

	thumbURL, license := fetchCommonsImageInfo(fileName)
	if thumbURL == "" {
		return "", "", fmt.Errorf("no usable image for %s", qid)
	}
	return thumbURL, license, nil
}

func extractP18FileName(body []byte, qid string) (string, error) {
	var data map[string]interface{}
	if err := json.Unmarshal(body, &data); err != nil {
		return "", fmt.Errorf("failed to parse Wikidata response: %w", err)
	}
	var entity map[string]interface{}
	if entities, ok := data["entities"].(map[string]interface{}); ok {
		entity, _ = entities[qid].(map[string]interface{})
	}
	if entity == nil {
		return "", fmt.Errorf("QID %s not found in Wikidata", qid)
	}
	claims, _ := entity["claims"].(map[string]interface{})
	stmts, _ := claims["P18"].([]interface{})
	for _, s := range stmts {
		stmt, _ := s.(map[string]interface{})
		mainsnak, _ := stmt["mainsnak"].(map[string]interface{})
		datavalue, _ := mainsnak["datavalue"].(map[string]interface{})
		if v, _ := datavalue["value"].(string); v != "" {
			return v, nil
		}
	}
	return "", fmt.Errorf("no image found for QID %s", qid)
}

// fetchCommonsImageInfo asks the Commons API for the thumbnail URL (at 800px width) and the
// SPDX license id in a single call. The thumbnail URL is authoritative: the /thumb/ subpath
// is an MD5 hash of the filename that cannot be derived locally. The UTM query params the
// API appends are stripped so downstream <img src> and onerror swaps stay clean.
func fetchCommonsImageInfo(fileName string) (string, string) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	apiURL := fmt.Sprintf(
		"https://commons.wikimedia.org/w/api.php?action=query&titles=File:%s&prop=imageinfo&iiprop=url|extmetadata|size&iiextmetadatafilter=License&iiurlwidth=800&format=json",
		url.QueryEscape(strings.ReplaceAll(fileName, " ", "_")),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL, nil)
	if err != nil {
		return "", ""
	}
	req.Header.Set("User-Agent", "omatsuri-map/1.0")

	resp, err := client.Do(req)
	if err != nil {
		return "", ""
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", ""
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", ""
	}

	var data struct {
		Query struct {
			Pages map[string]struct {
				Missing   bool `json:"missing"`
				ImageInfo []struct {
					ThumbURL    string `json:"thumburl"`
					URL         string `json:"url"`
					Extmetadata map[string]struct {
						Value string `json:"value"`
					} `json:"extmetadata"`
				} `json:"imageinfo"`
			} `json:"pages"`
		} `json:"query"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return "", ""
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
			return stripUTM(u), license
		}
	}
	return "", ""
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
