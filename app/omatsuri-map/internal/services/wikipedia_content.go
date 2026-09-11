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
}

func FetchWikipediaContent(title, expectedQID string) (WikipediaContent, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	params := url.Values{
		"action":        {"query"},
		"format":        {"json"},
		"formatversion": {"2"},
		"redirects":     {"1"},
		"prop":          {"extracts|pageimages|pageprops"},
		"exintro":       {"1"},
		"explaintext":   {"1"},
		"exchars":       {"700"},
		"piprop":        {"thumbnail"},
		"pithumbsize":   {"1200"},
		"pilicense":     {"free"},
		"titles":        {title},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, wikipediaAPIBase+"/w/api.php?"+params.Encode(), nil)
	if err != nil {
		return WikipediaContent{}, err
	}
	req.Header.Set("User-Agent", "omatsuri-map/1.0")
	resp, err := wikipediaClient.Do(req)
	if err != nil {
		return WikipediaContent{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return WikipediaContent{}, fmt.Errorf("Wikipedia API returned status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return WikipediaContent{}, err
	}
	return parseWikipediaContent(body, expectedQID)
}

func parseWikipediaContent(body []byte, expectedQID string) (WikipediaContent, error) {
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
		if content.ImageURL != "" {
			if attribution, err := FetchCommonsAttribution(content.ImageURL); err == nil {
				content.Attribution = attribution
			} else {
				content.ImageURL = ""
			}
		}
		return content, nil
	}
	return WikipediaContent{}, fmt.Errorf("Wikipedia article content not found")
}
