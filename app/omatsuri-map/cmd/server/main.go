// omatsuri-map: 神社・お祭りマップ表示アプリ (port 8527)
// Go言語のREST APIサーバー
// 開発・デモ用に簡易HTML/JSマップページを含む

package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"omatsuri-map/internal/handlers"
	"omatsuri-map/internal/services"
)

func main() {
	// Initialize service
	service, err := services.NewFestivalService("frontend/festivals.json")
	if err != nil {
		fmt.Printf("Failed to load festivals: %v\n", err)
		os.Exit(1)
	}

	// Initialize handlers
	festivalHandler := handlers.NewFestivalHandler(service)
	wikidataHandler := handlers.NewWikidataHandler()

	geocodingService := services.NewGeocodingService()
	geocodingHandler := handlers.NewGeocodingHandler(geocodingService)

	hotelAreaService := services.NewHotelAreaService() // nil when JALAN_A8MAT is unset
	hotelAreaHandler := handlers.NewHotelAreaHandler(hotelAreaService)

	// Create mux
	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/festivals/prefecture/", festivalHandler.GetFestivalsByPrefecture)
	mux.HandleFunc("/api/festivals/descriptions", festivalHandler.GetAllFestivalsWithDescriptions)
	mux.HandleFunc("/api/festivals/", festivalHandler.GetAllFestivals)
	mux.HandleFunc("/api/festivals", festivalHandler.GetAllFestivals)
	mux.HandleFunc("/api/wiki/image", wikidataHandler.GetWikidataImage)
	mux.HandleFunc("/api/wiki/links", wikidataHandler.GetWikidataLinks)
	mux.HandleFunc("/api/wiki/content", handlers.GetWikipediaContent)
	mux.HandleFunc("/api/geocoding/reverse", geocodingHandler.ReverseGeocode)
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

	// Static file server for frontend
	fs := http.FileServer(http.Dir("frontend"))
	mux.Handle("/", fs)

	// Port for cloud platforms (Cloud Run, App Engine) via PORT env var, defaulting to 8527.
	port := os.Getenv("PORT")
	if port == "" {
		port = "8527"
	}

	// Create server
	server := &http.Server{
		Addr:    ":" + port,
		Handler: muxWithCORS,
	}

	// Start server in goroutine
	go func() {
		fmt.Printf("Starting server on :%s\n", port)
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
