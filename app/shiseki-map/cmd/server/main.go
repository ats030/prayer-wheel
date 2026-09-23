// shiseki-map: 史跡マップ表示アプリ (port 8530)
// Go言語のREST APIサーバー
// 開発・デモ用に簡易HTML/JSマップページを含む

package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"shiseki-map/internal/handlers"
	"shiseki-map/internal/services"
)

func main() {
	// Initialize service
	service, err := services.NewShisekiService("frontend/shiseki.db")
	if err != nil {
		fmt.Printf("Failed to load shisekis: %v\n", err)
		os.Exit(1)
	}

	// Initialize handlers
	shisekiHandler := handlers.NewShisekiHandler(service)
	wikidataHandler := handlers.NewWikidataHandler()

	geocodingService := services.NewGeocodingService()
	geocodingHandler := handlers.NewGeocodingHandler(geocodingService)

	jalanService := services.NewJalanService() // nil when JALAN_API_KEY is unset
	jalanHandler := handlers.NewJalanHandler(jalanService)

	hotelAreaService := services.NewHotelAreaService() // nil when JALAN_A8MAT is unset
	hotelAreaHandler := handlers.NewHotelAreaHandler(hotelAreaService)
	// Create mux
	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/shiseki/prefecture/", shisekiHandler.GetShisekiByPrefecture)
	mux.HandleFunc("/api/shiseki/descriptions", shisekiHandler.GetAllShisekiWithDescriptions)
	mux.HandleFunc("/api/shiseki/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/shiseki/" {
			shisekiHandler.GetAllShiseki(w, r)
			return
		}
		shisekiHandler.GetShisekiByQID(w, r)
	})
	mux.HandleFunc("/api/shiseki", shisekiHandler.GetAllShiseki)
	mux.HandleFunc("/api/wiki/image", wikidataHandler.GetWikidataImage)
	mux.HandleFunc("/api/wiki/links", wikidataHandler.GetWikidataLinks)
	mux.HandleFunc("/api/wiki/content", handlers.GetWikipediaContent)
	mux.HandleFunc("/api/geocoding/reverse", geocodingHandler.ReverseGeocode)
	mux.HandleFunc("/api/jalan/nearby", jalanHandler.NearbyHotels)
	mux.HandleFunc("/api/hotel-area/nearby", hotelAreaHandler.NearbyHotels)

	// CORS middleware wrapper
	muxWithCORS := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		mux.ServeHTTP(w, r)
	})

	// Static file server for frontend, with revalidation headers so new
	// deploys are picked up without heuristic caching.
	staticFS := http.FileServer(http.Dir("frontend"))
	setCacheHeaders := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			path := strings.TrimPrefix(r.URL.Path, "/")
			if path == "" || strings.HasSuffix(path, ".html") {
				w.Header().Set("Cache-Control", "no-store")
			} else {
				w.Header().Set("Cache-Control", "no-cache, must-revalidate")
			}
			next.ServeHTTP(w, r)
		})
	}
	mux.Handle("/", setCacheHeaders(staticFS))

	// Port for cloud platforms (Cloud Run, App Engine) via PORT env var, defaulting to 8530.
	port := os.Getenv("PORT")
	if port == "" {
		port = "8530"
	}

	// Create server
	server := &http.Server{
		Addr:    ":" + port,
		Handler: muxWithCORS,
	}

	// Start server in goroutine
	go func() {
		fmt.Println("Starting server on :" + port)
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			fmt.Printf("Server error: %v\n", err)
			os.Exit(1)
		}
	}()

	// Wait for SIGTERM or SIGINT
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)

	// Wait for signal
	<-stop
	fmt.Println("Shutting down server...")

	// Create shutdown context with timeout
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Graceful shutdown
	if err := server.Shutdown(ctx); err != nil {
		fmt.Printf("Server forced to shutdown: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Server stopped gracefully")
}
