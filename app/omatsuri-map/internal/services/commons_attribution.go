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

var commonsAttributionAPIBase = "https://commons.wikimedia.org"

type CommonsAttribution struct {
	Artist              string
	License             string
	LicenseURL          string
	SourceURL           string
	AttributionRequired bool
}

func FetchCommonsAttribution(imageURL string) (CommonsAttribution, error) {
	fileName, err := commonsFileName(imageURL)
	if err != nil {
		return CommonsAttribution{}, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	apiURL := fmt.Sprintf(
		"%s/w/api.php?action=query&titles=File:%s&prop=imageinfo&iiprop=url|extmetadata&iiextmetadatafilter=Artist|License|LicenseShortName|LicenseUrl|AttributionRequired&format=json",
		commonsAttributionAPIBase,
		url.QueryEscape(fileName),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL, nil)
	if err != nil {
		return CommonsAttribution{}, err
	}
	req.Header.Set("User-Agent", "omatsuri-map/1.0")
	resp, err := client.Do(req)
	if err != nil {
		return CommonsAttribution{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return CommonsAttribution{}, fmt.Errorf("Commons API returned status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return CommonsAttribution{}, err
	}
	return parseCommonsAttribution(body)
}

func commonsFileName(imageURL string) (string, error) {
	u, err := url.Parse(imageURL)
	if err != nil || (u.Hostname() != "upload.wikimedia.org" && u.Hostname() != "thumb.wikimedia.org") {
		return "", fmt.Errorf("not a Wikimedia Commons image URL")
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(parts) == 0 {
		return "", fmt.Errorf("missing Commons filename")
	}
	name := parts[len(parts)-1]
	for index, part := range parts {
		if part == "thumb" && len(parts) > index+3 {
			name = parts[len(parts)-2]
			break
		}
	}
	name, err = url.PathUnescape(name)
	if err != nil || name == "" {
		return "", fmt.Errorf("invalid Commons filename")
	}
	return name, nil
}

func parseCommonsAttribution(body []byte) (CommonsAttribution, error) {
	var data struct {
		Query struct {
			Pages map[string]struct {
				ImageInfo []struct {
					DescriptionURL string `json:"descriptionurl"`
					Extmetadata    map[string]struct {
						Value string `json:"value"`
					} `json:"extmetadata"`
				} `json:"imageinfo"`
			} `json:"pages"`
		} `json:"query"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return CommonsAttribution{}, err
	}
	for _, page := range data.Query.Pages {
		for _, info := range page.ImageInfo {
			value := func(key string) string { return strings.TrimSpace(info.Extmetadata[key].Value) }
			license := value("LicenseShortName")
			if license == "" {
				license = value("License")
			}
			return CommonsAttribution{
				Artist:              value("Artist"),
				License:             license,
				LicenseURL:          value("LicenseUrl"),
				SourceURL:           info.DescriptionURL,
				AttributionRequired: strings.EqualFold(value("AttributionRequired"), "true"),
			}, nil
		}
	}
	return CommonsAttribution{}, fmt.Errorf("Commons attribution metadata not found")
}
