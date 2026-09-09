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

type WikidataImageResponse struct {
	PropertyPages []PropertyPage `json:"pages"`
}

type PropertyPage struct {
	Title    string            `json:"title"`
	Claims   map[string][]map[string]interface{} `json:"claims"`
}

type WikimediaLicenseInfo struct {
	Query struct {
		Pages map[string]WikimediaPage `json:"pages"`
	} `json:"query"`
}

type WikimediaPage struct {
	Title      string `json:"title"`
	ImageInfo  []struct {
		License string `json:"license"`
	} `json:"imageinfo"`
}

func FetchWikidataImage(qid string) (string, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	wikidataURL := fmt.Sprintf("https://www.wikidata.org/w/api.php?action=wbgetentities&ids=%s&props=claims&format=json", qid)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, wikidataURL, nil)
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("User-Agent", "omatsuri-map/1.0")

	client := &http.Client{Timeout: 10 * time.Second}
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

	var data map[string]interface{}
	if err := json.Unmarshal(body, &data); err != nil {
		return "", "", fmt.Errorf("failed to parse Wikidata response: %w", err)
	}

	entities := data["entities"].(map[string]interface{})
	qidEntity, exists := entities[qid]
	if !exists {
		return "", "", fmt.Errorf("QID %s not found in Wikidata", qid)
	}

	entity := qidEntity.(map[string]interface{})
	claims := entity["claims"].(map[string]interface{})

	var imageUrl string
	if p18Claims, ok := claims["P18"]; ok {
		if len(p18Claims.([]interface{})) > 0 {
			snak := p18Claims.([]interface{})[0].(map[string]interface{})["m"].([]interface{})[1].(map[string]interface{})
			value := snak["text"].(string)
			imageUrl = "https://upload.wikimedia.org/wikipedia/commons/thumb/" + value[:1] + "/" + value[:2] + "/" + url.PathEscape(value) + "/800px-" + url.PathEscape(value)
		}
	}

	if imageUrl == "" {
		return "", "", fmt.Errorf("no image found for QID %s", qid)
	}

	licenseId, err := getWikimediaLicense(imageUrl)
	if err != nil {
		return "", "", err
	}

	return imageUrl, licenseId, nil
}

func getWikimediaLicense(imageUrl string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	imageName := imageUrl[strings.LastIndex(imageUrl, "/")+1:]
	wikimediaURL := fmt.Sprintf("https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=license&titles=%s&format=json", url.PathEscape(imageName))

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, wikimediaURL, nil)
	if err != nil {
		return "", fmt.Errorf("failed to create Wikimedia request: %w", err)
	}

	req.Header.Set("User-Agent", "omatsuri-map/1.0")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to fetch from Wikimedia: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("Wikimedia API returned status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read Wikimedia response: %w", err)
	}

	var data WikimediaLicenseInfo
	if err := json.Unmarshal(body, &data); err != nil {
		return "", fmt.Errorf("failed to parse Wikimedia response: %w", err)
	}

	for _, page := range data.Query.Pages {
		if len(page.ImageInfo) > 0 && page.ImageInfo[0].License != "" {
			return page.ImageInfo[0].License, nil
		}
	}

	return "unknown", nil
}
