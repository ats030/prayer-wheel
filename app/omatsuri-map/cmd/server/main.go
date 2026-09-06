// omatsuri-map: 神社・お祭りマップ表示アプリ (port 8527)
// Go言語のREST APIサーバー
// 開発・デモ用に簡易HTML/JSマップページを含む

package main

import (
	"fmt"
	"net/http"
	"os"

	"omatsuri-map/internal/handlers"
	"omatsuri-map/internal/services"
)

func main() {
	// Initialize service
	service, err := services.NewFestivalService("data/festivals-with-date.json")
	if err != nil {
		fmt.Printf("Failed to load festivals: %v\n", err)
		os.Exit(1)
	}

	// Initialize handler
	handler := handlers.NewFestivalHandler(service)

	// Create mux
	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/festivals/prefecture/", handler.GetFestivalsByPrefecture)
	mux.HandleFunc("/api/festivals/", handler.GetAllFestivals)
	mux.HandleFunc("/api/festivals", handler.GetAllFestivals)

	// Static file server for frontend
	fs := http.FileServer(http.Dir("frontend"))
	mux.Handle("/", fs)

	// Start server
	fmt.Println("Starting server on :8527")
	if err := http.ListenAndServe(":8527", mux); err != nil {
		fmt.Printf("Server error: %v\n", err)
		os.Exit(1)
	}
}
