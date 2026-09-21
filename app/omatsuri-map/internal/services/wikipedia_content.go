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

var wikipediaAPIBase = "https://ja.wikipedia.org"
var wikipediaClient = &http.Client{Timeout: 12 * time.Second}

type WikipediaContent struct {
	Description string
	SourceURL   string
	ImageURL    string
	Attribution CommonsAttribution
	ImageTitles []string
}

func FetchWikipediaContent(ctx context.Context, title, expectedQID string) (WikipediaContent, error) {
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	params := url.Values{
		"action":        {"query"},
		"format":        {"json"},
		"formatversion": {"2"},
		"redirects":     {"1"},
		"prop":          {"extracts|pageimages|pageprops|images"},
		"exintro":       {"1"},
		"explaintext":   {"1"},
		"exchars":       {"700"},
		"piprop":        {"thumbnail"},
		"pithumbsize":   {"1200"},
		"pilicense":     {"free"},
		"imlimit":       {"20"},
		"titles":        {title},
	}
	apiURL := wikipediaAPIBase + "/w/api.php?" + params.Encode()

	var lastErr error
	var body []byte
	for attempt := 0; attempt < 3; attempt++ {
		respBody, status, delay, err := fetchWikipediaContentOnce(ctx, apiURL)
		if err == nil {
			body = respBody
			lastErr = nil
			break
		}
		lastErr = err
		if !retryableStatus(status) || attempt == 2 {
			break
		}
		select {
		case <-time.After(delay):
		case <-ctx.Done():
			return WikipediaContent{}, ctx.Err()
		}
	}
	if lastErr != nil {
		return WikipediaContent{}, lastErr
	}


	content, err := parseWikipediaContent(ctx, body, expectedQID)
	if err != nil {
		return WikipediaContent{}, err
	}
	if content.ImageURL == "" {
		for _, title := range usableArticleImageTitles(content.ImageTitles) {
			fileName := strings.TrimPrefix(strings.TrimPrefix(title, "ファイル:"), "File:")
			candidateURL := "https://upload.wikimedia.org/" + url.PathEscape(fileName)
			attribution, err := FetchCommonsAttribution(ctx, candidateURL)
			if err == nil && attribution.ImageURL != "" && attribution.License != "" {
				content.ImageURL = attribution.ImageURL
				content.Attribution = attribution
				break
			}
		}
	}
	return content, nil
}

func usableArticleImageTitles(titles []string) []string {
	result := make([]string, 0, len(titles))
	for _, title := range titles {
		lower := strings.ToLower(title)
		if strings.Contains(lower, "logo") || strings.Contains(lower, "icon") || strings.Contains(lower, "wiki letter") || strings.Contains(lower, "camera-photo") || strings.HasSuffix(lower, ".svg") {
			continue
		}
		result = append(result, title)
	}
	return result
}

func fetchWikipediaContentOnce(ctx context.Context, apiURL string) ([]byte, int, time.Duration, error) {
	base := 250 * time.Millisecond
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL, nil)
	if err != nil {
		return nil, 0, base, err
	}
	req.Header.Set("User-Agent", "omatsuri-map/1.0")
	resp, err := wikipediaClient.Do(req)
	if err != nil {
		return nil, 0, base, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		delay := 0 * time.Second
		if retryableStatus(resp.StatusCode) {
			delay = retryDelayFor(resp, base)
		}
		return nil, resp.StatusCode, delay, fmt.Errorf("Wikipedia API returned status %d", resp.StatusCode)
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, base, err
	}
	return data, resp.StatusCode, 0, nil
}

func parseWikipediaContent(ctx context.Context, body []byte, expectedQID string) (WikipediaContent, error) {
	var data struct {
		Query struct {
			Pages []struct {
				Missing   bool   `json:"missing"`
				Title     string `json:"title"`
				Extract   string `json:"extract"`
				Thumbnail struct {
					Source string `json:"source"`
				} `json:"thumbnail"`
				PageProps struct {
					WikibaseItem string `json:"wikibase_item"`
				} `json:"pageprops"`
				Images []struct {
					Title string `json:"title"`
				} `json:"images"`
			} `json:"pages"`
		} `json:"query"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return WikipediaContent{}, err
	}
	for _, page := range data.Query.Pages {
		if page.Missing || strings.TrimSpace(page.Extract) == "" || expectedQID == "" || page.PageProps.WikibaseItem != expectedQID {
			continue
		}
		content := WikipediaContent{
			Description: strings.TrimSpace(page.Extract),
			SourceURL:   "https://ja.wikipedia.org/wiki/" + url.PathEscape(strings.ReplaceAll(page.Title, " ", "_")),
			ImageURL:    page.Thumbnail.Source,
		}
		for _, image := range page.Images {
			content.ImageTitles = append(content.ImageTitles, image.Title)
		}
		if content.ImageURL != "" {
			if attribution, err := FetchCommonsAttribution(ctx, content.ImageURL); err == nil {
				content.Attribution = attribution
			} else {
				content.ImageURL = ""
			}
		}
		return content, nil
	}
	return WikipediaContent{}, fmt.Errorf("Wikipedia article content not found")
}
