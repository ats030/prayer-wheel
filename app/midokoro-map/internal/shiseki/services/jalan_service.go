package services

import (
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"
)

// JalanNearbyHotel is a hotel returned by the Jalan Web Service HotelSearch
// Advance API, with an affiliate link already applied.
type JalanNearbyHotel struct {
	Name         string `json:"name"`
	DetailURL    string `json:"detail_url"`
	PlanURL      string `json:"plan_url,omitempty"`
	ThumbnailURL string `json:"thumbnail_url,omitempty"`
	Address      string `json:"address,omitempty"`
}

type jalanHotelXML struct {
	HotelName         string `xml:"HotelName"`
	HotelDetailURL    string `xml:"HotelDetailURL"`
	PlanDetailURL     string `xml:"PlanDetailURL"`
	HotelThumbnailURL string `xml:"HotelThumbnailURL"`
	Address           string `xml:"Address"`
}

type jalanResponseXML struct {
	XMLName xml.Name        `xml:"Results"`
	Hotels  []jalanHotelXML `xml:"Hotel"`
}

// JalanService calls the Jalan Web Service HotelSearch Advance API
// (http://jws.jalan.net/APIAdvance/HotelSearch/V1/) to find hotels near a
// given point.
type JalanService struct {
	client   *http.Client
	apiKey   string
	a8mat    string
	endpoint string
}

// NewJalanService builds a JalanService from JALAN_API_KEY (and optionally
// JALAN_A8MAT) in the environment. It returns nil when JALAN_API_KEY is
// unset so callers can skip wiring the nearby-hotel route when the app runs
// without an API key configured.
func NewJalanService() *JalanService {
	apiKey := os.Getenv("JALAN_API_KEY")
	if apiKey == "" {
		return nil
	}
	return &JalanService{
		client:   &http.Client{Timeout: 10 * time.Second},
		apiKey:   apiKey,
		a8mat:    os.Getenv("JALAN_A8MAT"),
		endpoint: "http://jws.jalan.net/APIAdvance/HotelSearch/V1/",
	}
}

// NewJalanServiceForTest builds a JalanService pointed at a caller-supplied
// endpoint (e.g. an httptest.Server URL), for use by handler tests in other
// packages that cannot set JalanService's unexported fields directly.
func NewJalanServiceForTest(endpoint, apiKey, a8mat string) *JalanService {
	return &JalanService{
		client:   &http.Client{Timeout: 10 * time.Second},
		apiKey:   apiKey,
		a8mat:    a8mat,
		endpoint: endpoint,
	}
}

// degreesToJalanUnit converts a decimal-degree coordinate to the
// arcsecond-times-1000 integer format the Jalan API expects for x
// (longitude) and y (latitude).
func degreesToJalanUnit(deg float64) int64 {
	return int64(deg * 3600 * 1000)
}

// SearchNearby finds up to count hotels within radiusKm of (lat, lng).
// radiusKm is clamped to the API's supported 0.1-50km range.
func (s *JalanService) SearchNearby(lat, lng, radiusKm float64, count int) ([]JalanNearbyHotel, error) {
	if radiusKm < 0.1 {
		radiusKm = 0.1
	}
	if radiusKm > 50 {
		radiusKm = 50
	}
	if count <= 0 || count > 30 {
		count = 10
	}

	params := url.Values{}
	params.Set("key", s.apiKey)
	params.Set("x", strconv.FormatInt(degreesToJalanUnit(lng), 10))
	params.Set("y", strconv.FormatInt(degreesToJalanUnit(lat), 10))
	params.Set("range", strconv.FormatFloat(radiusKm, 'f', -1, 64))
	params.Set("count", strconv.Itoa(count))

	reqURL := s.endpoint + "?" + params.Encode()

	resp, err := s.client.Get(reqURL)
	if err != nil {
		return nil, fmt.Errorf("jalan API request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read jalan API response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("jalan API error: %d %s", resp.StatusCode, string(body))
	}

	var parsed jalanResponseXML
	if err := xml.Unmarshal(body, &parsed); err != nil {
		return nil, fmt.Errorf("failed to parse jalan API response: %w", err)
	}

	hotels := make([]JalanNearbyHotel, 0, len(parsed.Hotels))
	for _, h := range parsed.Hotels {
		if h.HotelDetailURL == "" {
			continue
		}
		hotels = append(hotels, JalanNearbyHotel{
			Name:         h.HotelName,
			DetailURL:    s.affiliateWrap(h.HotelDetailURL),
			PlanURL:      s.affiliateWrap(h.PlanDetailURL),
			ThumbnailURL: h.HotelThumbnailURL,
			Address:      h.Address,
		})
	}
	return hotels, nil
}

// affiliateWrap turns a Jalan destination URL into an A8.net tracking link
// via a8ejpredirect when JALAN_A8MAT is configured. Without it, the plain
// Jalan URL is returned so the feature still works before an A8.net program
// is attached.
func (s *JalanService) affiliateWrap(destURL string) string {
	if destURL == "" || s.a8mat == "" {
		return destURL
	}
	v := url.Values{}
	v.Set("a8mat", s.a8mat)
	v.Set("a8ejpredirect", destURL)
	return "https://px.a8.net/svt/ejp?" + v.Encode()
}
