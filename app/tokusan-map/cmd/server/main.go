// tokusan-map: 日本特産物マップ表示アプリ (port 8531)
// Go言語のREST APIサーバー (静的frontend/配信 + SQLiteバックエンド)

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

	"tokusan-map/internal/handlers"
	"tokusan-map/internal/services"
)

func main() {
	dbPath := os.Getenv("TOKUSAN_DB_PATH")
	if dbPath == "" {
		dbPath = "frontend/tokusan.db"
	}

	service, err := services.NewTokusanService(dbPath)
	if err != nil {
		fmt.Printf("Failed to load tokusan db (%s): %v\n", dbPath, err)
		os.Exit(1)
	}
	defer service.Close()

	tokusanHandler := handlers.NewTokusanHandler(service)

	mux := http.NewServeMux()
	mux.HandleFunc("/api/tokusan/prefecture/", tokusanHandler.GetByPrefecture)
	mux.HandleFunc("/api/tokusan/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/tokusan/" {
			tokusanHandler.GetAll(w, r)
			return
		}
		tokusanHandler.GetByQID(w, r)
	})
	mux.HandleFunc("/api/tokusan", tokusanHandler.GetAll)

	wikidataHandler := handlers.NewWikidataHandler()
	mux.HandleFunc("/api/wikiimage", wikidataHandler.GetWikidataImage)

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

	port := os.Getenv("PORT")
	if port == "" {
		port = "8531"
	}

	server := &http.Server{
		Addr:    ":" + port,
		Handler: gzipMiddleware(muxWithCORS),
	}

	go func() {
		fmt.Println("Starting tokusan-map server on :" + port)
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			fmt.Printf("Server error: %v\n", err)
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	<-stop
	fmt.Println("Shutting down server...")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := server.Shutdown(ctx); err != nil {
		fmt.Printf("Server forced to shutdown: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Server stopped gracefully")
}
