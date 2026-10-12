// Package geo serves photos and section summaries for the geo tab's natural
// monuments. The point and area data themselves are static files under /geo/.
package geo

import (
	"net/http"

	"midokoro-map/internal/shiseki/handlers"
)

// NewHandler reuses the shiseki Wikidata image lookup and the Wikipedia section
// pipeline with the geo section profile.
func NewHandler(string) (http.Handler, error) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/wiki/image", handlers.NewWikidataHandler().GetWikidataImage)
	mux.HandleFunc("/api/wiki/content", handlers.NewGeoWikipediaContentHandler().GetWikipediaContent)
	return mux, nil
}
