package main

import (
	"encoding/json"
	"os"
)

// Festival represents the input JSON structure
type Festival struct {
	QID        string  `json:"qid"`
	LabelJA    string  `json:"label_ja"`
	LabelEN    string  `json:"label_en"`
	Prefecture string  `json:"prefecture"`
	Latitude   float64 `json:"latitude"`
	Longitude  float64 `json:"longitude"`
}

// GeoJSON Feature
type Feature struct {
	Type       string      `json:"type"`
	Geometry   Geometry    `json:"geometry"`
	Properties Properties  `json:"properties"`
}

// GeoJSON Geometry (Point)
type Geometry struct {
	Type        string    `json:"type"`
	Coordinates []float64 `json:"coordinates"`
}

// GeoJSON Properties (all fields except coordinates)
type Properties struct {
	QID        string  `json:"qid"`
	LabelJA    string  `json:"label_ja"`
	LabelEN    string  `json:"label_en"`
	Prefecture string  `json:"prefecture"`
	Latitude   float64 `json:"latitude"`
	Longitude  float64 `json:"longitude"`
}

// GeoJSON FeatureCollection
type FeatureCollection struct {
	Type     string   `json:"type"`
	Features []Feature `json:"features"`
}

func main() {
	// Read input file
	inputPath := "/home/ats030/app/omatsuri-map/data/festivals.json"
	outputPath := "/home/ats030/app/omatsuri-map/data/festivals.geojson"

	data, err := os.ReadFile(inputPath)
	if err != nil {
		panic(err)
	}

	var festivals []Festival
	if err := json.Unmarshal(data, &festivals); err != nil {
		panic(err)
	}

	// Convert to GeoJSON FeatureCollection
	features := make([]Feature, len(festivals))
	for i, f := range festivals {
		features[i] = Feature{
			Type: "Feature",
			Geometry: Geometry{
				Type:        "Point",
				Coordinates: []float64{f.Longitude, f.Latitude},
			},
			Properties: Properties{
				QID:        f.QID,
				LabelJA:    f.LabelJA,
				LabelEN:    f.LabelEN,
				Prefecture: f.Prefecture,
				Latitude:   f.Latitude,
				Longitude:  f.Longitude,
			},
		}
	}

	featureCollection := FeatureCollection{
		Type:     "FeatureCollection",
		Features: features,
	}

	// Write output file
	outputData, err := json.MarshalIndent(featureCollection, "", "  ")
	if err != nil {
		panic(err)
	}

	if err := os.WriteFile(outputPath, outputData, 0644); err != nil {
		panic(err)
	}

	println("Converted", len(festivals), "festivals to GeoJSON")
}
