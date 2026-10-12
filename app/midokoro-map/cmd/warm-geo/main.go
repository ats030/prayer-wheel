// warm-geo fills data/geo/summaries.json for natural monuments that have a
// Japanese Wikipedia article in data/geo/wikidata.json, using the geo section
// profile. It is serial and resume-safe: cached sections are not regenerated.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"sort"
	"syscall"
	"time"

	"midokoro-map/internal/shared"
	"midokoro-map/internal/shiseki/services"
)

type mapping struct {
	QID   string  `json:"qid"`
	Title *string `json:"title"`
	Via   string  `json:"via"`
}

func loadTitles(path string) []string {
	raw, err := os.ReadFile(path)
	if err != nil {
		log.Fatalf("load %s: %v", path, err)
	}
	var entries map[string]mapping
	if err := json.Unmarshal(raw, &entries); err != nil {
		log.Fatalf("parse %s: %v", path, err)
	}
	seen := map[string]bool{}
	titles := []string{}
	for _, entry := range entries {
		if entry.Title != nil && *entry.Title != "" && !seen[*entry.Title] {
			seen[*entry.Title] = true
			titles = append(titles, *entry.Title)
		}
	}
	sort.Strings(titles)
	return titles
}

func main() {
	path := flag.String("mapping", shared.DataPath("geo", "wikidata.json"), "natural monument to Wikipedia mapping")
	limit := flag.Int("limit", 0, "only process first N titles (0 = all)")
	dryRun := flag.Bool("dry-run", false, "print the titles and exit (no LLM)")
	flag.Parse()
	if services.SummaryDisabled() {
		log.Fatal("SHISEKI_SUMMARY_DISABLE is set; unset it to generate summaries")
	}
	titles := loadTitles(*path)
	if *limit > 0 && *limit < len(titles) {
		titles = titles[:*limit]
	}
	if *dryRun {
		fmt.Printf("titles=%d (dry-run)\n", len(titles))
		for _, title := range titles[:min(5, len(titles))] {
			fmt.Println("  ", title)
		}
		return
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	done, summarized, skipped := 0, 0, 0
	for i, title := range titles {
		if ctx.Err() != nil {
			fmt.Printf("warm-geo stopped: done=%d summarized=%d skipped=%d\n", done, summarized, skipped)
			os.Exit(130)
		}
		start := time.Now()
		origin, features, access, protection, transient, err := services.GeoProfile.FetchPanelSections(ctx, title)
		if err != nil {
			skipped++
			log.Printf("[%3d/%d] %s SKIP err=%v transient=%v (%.0fs)", i+1, len(titles), title, err, transient, time.Since(start).Seconds())
			continue
		}
		done++
		n := 0
		for _, section := range []services.PanelSection{origin, features, access, protection} {
			if section.Summary != "" {
				n++
			}
		}
		if n > 0 {
			summarized++
		}
		log.Printf("[%3d/%d] %s OK summaries=%d (%.0fs)", i+1, len(titles), title, n, time.Since(start).Seconds())
	}
	fmt.Printf("warm-geo complete: done=%d summarized=%d skipped=%d\n", done, summarized, skipped)
	// 1 = some titles failed (rerun resumes), 3 = nothing summarized (e.g. Ollama unavailable).
	if skipped > 0 {
		os.Exit(1)
	}
	if summarized == 0 {
		os.Exit(3)
	}
}
