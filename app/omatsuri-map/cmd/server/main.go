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
	service, err := services.NewFestivalService("data/festivals-with-descriptions.json")
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
	mux.HandleFunc("/api/festivals/descriptions", handler.GetAllFestivalsWithDescriptions)
	mux.HandleFunc("/api/festivals/", handler.GetAllFestivals)
	mux.HandleFunc("/api/festivals", handler.GetAllFestivals)

	// Static file server for frontend
	fs := http.FileServer(http.Dir("frontend"))
	mux.Handle("/", fs)

	// Create server
	server := &http.Server{
		Addr:    ":8527",
		Handler: mux,
	}

	// Start server in goroutine
	go func() {
		fmt.Println("Starting server on :8527")
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
