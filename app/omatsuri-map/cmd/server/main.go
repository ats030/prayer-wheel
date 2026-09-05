package main

import (
	"log"
	"net/http"

	"omatsuri-map/internal/handlers"
	"omatsuri-map/internal/services"
)

func main() {
	// Initialize the festival service
	dataDir := "/home/ats030/app/omatsuri-map/data"
	service, err := services.NewFestivalService(dataDir)
	if err != nil {
		log.Fatalf("Failed to initialize festival service: %v", err)
	}

	// Create handlers
	handler := handlers.NewFestivalHandler(service)

	// Set up routes
	http.HandleFunc("/api/festivals", handler.HandleFestivals)
	http.HandleFunc("/api/festivals/prefecture/", handler.HandleFestivalsByPrefecture)
	http.HandleFunc("/api/festivals/", handler.HandleFestivalByID)

	// Start server
	log.Println("Starting server on :8080")
	if err := http.ListenAndServe(":8080", nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
