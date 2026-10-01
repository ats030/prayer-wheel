package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

// maxCommonsCandidates bounds how many exact-name search hits we will probe
// for attribution before giving up. Commons search is relevance-ordered, so
// the first few are the real candidates; probing more only adds latency and
// licence noise.
const maxCommonsCandidates = 3

// FindCommonsImageByName is path C: it searches Wikimedia Commons for a file
// whose name matches the festival's label_ja, then returns the first such
// file that carries usable licence metadata. The licence gate (and the
// artist/credit attribution) is enforced by FetchCommonsAttribution plus the
// caller's effectiveLicense check, so unlicensed files are never returned.
func FindCommonsImageByName(ctx context.Context, name, prefecture string) (CommonsAttribution, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return CommonsAttribution{}, fmt.Errorf("festival name is required")
	}

	query := name
	if p := strings.TrimSpace(prefecture); p != "" {
		query = name + " " + p
	}

	fileNames, err := searchCommonsFileNames(ctx, query)
	if err != nil {
		return CommonsAttribution{}, err
	}

	seen := make(map[string]bool, len(fileNames))
	tried := 0
	for _, fileName := range fileNames {
		if baseName(fileName) != name || seen[fileName] {
			continue
		}
		seen[fileName] = true
		// buildPathCURL keeps the upload.wikimedia.org host so commonsFileName
		// can recover the file title and FetchCommonsAttribution can resolve it.
		candidateURL := "https://upload.wikimedia.org/" + url.PathEscape(fileName)
		attribution, err := FetchCommonsAttribution(ctx, candidateURL)
		if err == nil && attribution.License != "" && attribution.ImageURL != "" {
			return attribution, nil
		}
		tried++
		if tried >= maxCommonsCandidates {
			break
		}
	}
	return CommonsAttribution{}, fmt.Errorf("no licensed Commons image for %q", name)
}

// searchCommonsFileNames runs a Commons generator=search for File: pages and
// returns the matching file titles (without the "File:" namespace prefix),
// relevance-ordered. An API with no hits returns an empty slice, not an error.
func searchCommonsFileNames(ctx context.Context, query string) ([]string, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()

	params := url.Values{
		"action":       {"query"},
		"format":       {"json"},
		"formatversion": {"2"},
		"generator":    {"search"},
		"gsrsearch":    {query},
		"gsrnamespace": {"6"},
		"gsrlimit":     {"50"},
		"gsrsort":      {"relevance"},
		"prop":         {"info"},
		"inprop":       {"url"},
	}
	apiURL := commonsAttributionAPIBase + "/w/api.php?" + params.Encode()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, apiURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", wikimediaUserAgent)
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Commons API returned status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var data struct {
		Query struct {
			GeneratorPages map[string]struct {
				Title string `json:"title"`
			} `json:"generatorpages"`
		} `json:"query"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, err
	}

	var names []string
	for _, page := range data.Query.GeneratorPages {
		title := strings.TrimSpace(page.Title)
		title = strings.TrimPrefix(title, "File:")
		title = strings.TrimPrefix(title, "ファイル:")
		if title != "" {
			names = append(names, title)
		}
	}
	return names, nil
}

// baseName strips a single trailing image extension so "博多祇園山笠.jpg"
// becomes "博多祇園山笠". Only one extension is removed: a thumb path such as
// "山笠 (thumb).png" yields "山笠 (thumb)", which still does not equal the
// bare festival name and so is correctly rejected as an exact match.
func baseName(fileName string) string {
	return imageExtPattern.ReplaceAllString(fileName, "")
}

var imageExtPattern = regexp.MustCompile(`(?i)\.(jpe?g|png|svg|gif|webp)$`)
