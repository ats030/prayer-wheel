package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"midokoro-map/internal/omatsuri"
	"midokoro-map/internal/onsen"
	"midokoro-map/internal/shared"
	"midokoro-map/internal/shiseki"
	"midokoro-map/internal/tokusan"
)

var kinds = map[string]bool{"shiseki": true, "omatsuri": true, "onsen": true, "tokusan": true}

type publicConfig struct {
	DefaultKind      string   `json:"defaultKind"`
	AffiliateOrigins []string `json:"affiliateOrigins"`
	SummariesOnly    bool     `json:"summariesOnly"`
}

func readConfig() (publicConfig, error) {
	def := os.Getenv("MIDOKORO_DEFAULT_KIND")
	if def == "" {
		def = "shiseki"
	}
	if !kinds[def] {
		return publicConfig{}, fmt.Errorf("invalid MIDOKORO_DEFAULT_KIND: %s", def)
	}
	return publicConfig{DefaultKind: def, AffiliateOrigins: shared.AffiliateOrigins(), SummariesOnly: os.Getenv("MIDOKORO_SUMMARIES_ONLY") == "1"}, nil
}

func newHandler(dataDir, frontendDir string, config publicConfig) (http.Handler, error) {
	mux := http.NewServeMux()
	registerStoryRoutes(mux, frontendDir)
	if config.SummariesOnly {
		if err := registerPublishedSummaries(mux, dataDir); err != nil {
			return nil, err
		}
	}
	builders := map[string]func(string) (http.Handler, error){
		"shiseki": shiseki.NewHandler, "omatsuri": omatsuri.NewHandler,
		"onsen": onsen.NewHandler, "tokusan": tokusan.NewHandler,
	}
	for kind, build := range builders {
		domain, err := build(dataDir)
		if err != nil {
			return nil, err
		}
		prefix := "/api/" + kind
		mux.Handle(prefix+"/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			copy := r.Clone(r.Context())
			urlCopy := *r.URL
			urlCopy.Path = "/api" + strings.TrimPrefix(r.URL.Path, prefix)
			copy.URL = &urlCopy
			domain.ServeHTTP(w, copy)
		}))
	}
	mux.HandleFunc("/api/config", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		json.NewEncoder(w).Encode(config)
	})
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"status":"ok","service":"midokoro-map"}`))
	})
	files := http.FileServer(http.Dir(frontendDir))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") {
			http.NotFound(w, r)
			return
		}
		if r.URL.Path == "/changelog" {
			r = r.Clone(r.Context())
			u := *r.URL
			u.Path = "/changelog.html"
			r.URL = &u
		}
		if strings.HasSuffix(r.URL.Path, ".db") || strings.HasSuffix(r.URL.Path, ".sqlite") || strings.Contains(r.URL.Path, "/data/") {
			http.NotFound(w, r)
			return
		}
		if r.URL.Path == "/" || strings.HasSuffix(r.URL.Path, ".html") {
			w.Header().Set("Cache-Control", "no-store")
		} else {
			w.Header().Set("Cache-Control", "no-cache")
		}
		files.ServeHTTP(w, r)
	})
	return gzipMiddleware(mux), nil
}

func main() {
	config, err := readConfig()
	if err != nil {
		log.Fatal(err)
	}
	dataDir := os.Getenv("MIDOKORO_DATA_DIR")
	if dataDir == "" {
		dataDir = "data"
	}
	frontendDir := os.Getenv("MIDOKORO_FRONTEND_DIR")
	if frontendDir == "" {
		frontendDir = "frontend"
	}
	if !shared.AdsEnabled() {
		os.Setenv("TOKUSAN_AMAZON_URL", "")
	}
	handler, err := newHandler(filepath.Clean(dataDir), filepath.Clean(frontendDir), config)
	if err != nil {
		log.Fatal(err)
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8533"
	}
	server := &http.Server{Addr: ":" + port, Handler: handler, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 90 * time.Second}
	go func() {
		log.Printf("midokoro-map listening on %s", server.Addr)
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	server.Shutdown(ctx)
}
