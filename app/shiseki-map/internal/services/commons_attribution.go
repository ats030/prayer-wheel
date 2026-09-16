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
	ImageURL            string
	Artist              string
	Credit              string
	License             string
	LicenseURL          string
	SourceURL           string
	AttributionRequired bool
}

func FetchCommonsAttribution(imageURL string) (CommonsAttribution, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		attribution, retry, err := fetchCommonsAttributionOnce(ctx, imageURL)
		if err == nil {
			return attribution, nil
		}
		lastErr = err
		if !retry || attempt == 2 {
			break
		}
		select {
		case <-time.After(time.Duration(250*(1<<attempt)) * time.Millisecond):
		case <-ctx.Done():
			return CommonsAttribution{}, ctx.Err()
		}
	}
	return CommonsAttribution{}, lastErr
}

func fetchCommonsAttributionOnce(ctx context.Context, imageURL string) (CommonsAttribution, bool, error) {
	fileName, err := commonsFileName(imageURL)
	if err != nil {
		return CommonsAttribution{}, false, err
	}
	apiURL := fmt.Sprintf(
		"%s/w/api.php?action=query&titles=File:%s&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=1200&iiextmetadatafilter=Artist|Credit|License|LicenseShortName|LicenseUrl|AttributionRequired&format=json",
		commonsAttributionAPIBase,
		url.QueryEscape(fileName),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL, nil)
	if err != nil {
		return CommonsAttribution{}, false, err
	}
	req.Header.Set("User-Agent", wikimediaUserAgent)
	resp, err := client.Do(req)
	if err != nil {
		return CommonsAttribution{}, true, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return CommonsAttribution{}, resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= http.StatusInternalServerError, fmt.Errorf("Commons API returned status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return CommonsAttribution{}, true, err
	}
	attribution, err := parseCommonsAttribution(body)
	return attribution, false, err
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
					URL            string `json:"url"`
					ThumbURL       string `json:"thumburl"`
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
			imageURL := info.ThumbURL
			if imageURL == "" {
				imageURL = info.URL
			}
			return CommonsAttribution{
				ImageURL:            imageURL,
				Artist:              value("Artist"),
				Credit:              value("Credit"),
				License:             license,
				LicenseURL:          value("LicenseUrl"),
				SourceURL:           info.DescriptionURL,
				AttributionRequired: strings.EqualFold(value("AttributionRequired"), "true"),
			}, nil
		}
	}
	return CommonsAttribution{}, fmt.Errorf("Commons attribution metadata not found")
}
