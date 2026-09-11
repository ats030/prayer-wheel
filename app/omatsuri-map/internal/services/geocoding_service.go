package services

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

// ReverseGeoResult represents the Nominatim API response
type ReverseGeoResult struct {
	Address struct {
		City          string `json:"city"`
		Town          string `json:"town"`
		Village       string `json:"village"`
		Suburb        string `json:"suburb"`
		CityDistrict  string `json:"city_district"`
		Quarter       string `json:"quarter"`
		Neighbourhood string `json:"neighbourhood"`
		Road          string `json:"road"`
		State         string `json:"state"`
		Country       string `json:"country"`
		CountryCode   string `json:"countrycode"`
	} `json:"address"`
	DisplayName string `json:"display_name"`
}

// GeocodingService provides reverse geocoding via Nominatim API
type GeocodingService struct {
	client          *http.Client
	mu              *sync.Mutex
	lastRequestTime time.Time
	rateLimitDelay  time.Duration
	userAgent       string
	endpoint        string
}

// NewGeocodingService creates a new geocoding service
func NewGeocodingService() *GeocodingService {
	endpoint := os.Getenv("NOMINATIM_BASE_URL")
	if endpoint == "" {
		endpoint = "https://nominatim.openstreetmap.org"
	}
	userAgent := os.Getenv("NOMINATIM_USER_AGENT")
	if userAgent == "" {
		userAgent = "omatsuri-map/1.0 (https://github.com/ats030/ikimono-note)"
	}
	return &GeocodingService{
		client: &http.Client{
			Timeout: 10 * time.Second,
		},
		mu:              &sync.Mutex{},
		lastRequestTime: time.Now(),
		rateLimitDelay:  time.Second, // 1 req/sec limit
		userAgent:       userAgent,
		endpoint:        endpoint,
	}
}

// ReverseGeocode fetches detailed location from Nominatim API
func (s *GeocodingService) ReverseGeocode(lat, lon float64) (*ReverseGeoResult, error) {
	s.mu.Lock()
	elapsed := time.Since(s.lastRequestTime)
	if elapsed < s.rateLimitDelay {
		time.Sleep(s.rateLimitDelay - elapsed)
	}
	s.lastRequestTime = time.Now()
	s.mu.Unlock()

	endpoint := strings.TrimRight(s.endpoint, "/") + "/reverse"
	params := url.Values{}
	params.Set("format", "json")
	params.Set("lat", fmt.Sprintf("%.6f", lat))
	params.Set("lon", fmt.Sprintf("%.6f", lon))
	params.Set("addressdetails", "1")
	params.Set("zoom", "16")

	reqURL := endpoint + "?" + params.Encode()

	req, err := http.NewRequest("GET", reqURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("User-Agent", s.userAgent)

	resp, err := s.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("API request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("Nominatim API error: %d %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	var result ReverseGeoResult
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	return &result, nil
}
