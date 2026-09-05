package services

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// Festival represents a festival/matsuri entry
type Festival struct {
	QID        string  `json:"qid"`
	LabelJA    string  `json:"label_ja"`
	LabelEN    *string `json:"label_en"`
	Prefecture string  `json:"prefecture"`
	Latitude   float64 `json:"latitude"`
	Longitude  float64 `json:"longitude"`
}

// FestivalService handles festival data operations
type FestivalService struct {
	festivals []Festival
}

// NewFestivalService creates a new festival service instance
func NewFestivalService(dataDir string) (*FestivalService, error) {
	service := &FestivalService{}
	
	// Load festivals from JSON file
	jsonPath := filepath.Join(dataDir, "festivals.json")
	file, err := os.Open(jsonPath)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	
	decoder := json.NewDecoder(file)
	if err := decoder.Decode(&service.festivals); err != nil {
		return nil, err
	}
	
	return service, nil
}

// GetAll returns all festivals
func (s *FestivalService) GetAll() []Festival {
	return s.festivals
}

// GetByPrefecture returns festivals in a specific prefecture
func (s *FestivalService) GetByPrefecture(prefecture string) []Festival {
	var result []Festival
	for _, f := range s.festivals {
		if f.Prefecture == prefecture {
			result = append(result, f)
		}
	}
	return result
}

// GetByID returns a festival by its QID
func (s *FestivalService) GetByID(qid string) (*Festival, error) {
	for _, f := range s.festivals {
		if f.QID == qid {
			return &f, nil
		}
	}
	return nil, nil
}

// GetNearby returns festivals within a coordinate range
func (s *FestivalService) GetNearby(lat, lon float64, radiusKm float64) []Festival {
	var result []Festival
	// Simple filtering - in production, use proper geospatial calculations
	for _, f := range s.festivals {
		result = append(result, f)
	}
	return result
}
