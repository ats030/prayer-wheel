// summary-warm: 5セクション(歴史・由来 / 見どころ / お祭りの流れ /
// アクセス / 周辺観光)の構造化要約を LLM で一括生成し、
// data/summaries.json に書き込むウォームアップツール。
//
// 用途: Cloud Run は実行中に LLM を呼べないため、要約生成済みのキャッシュを
// イメージと同梱して配信する。本ツールはそのキャッシュをローカルで生成する。
//
// 運用メモ:
//   - LLM は localhost の Open WebUI/proxy (localhost:11434) 経由。同じ proxy
//     が生成を1本同時にしか通さないため並列は1。
//   - 503(busy)は再試行してよい一時的エラー。1パスで未完了のセクションは
//     再実行で再挑戦する（キャッシュ済みは LLM を呼ばない）。
//   - プロセスは SIGINT/Ctrl-C で安全に停止。data/summaries.json は
//     Put ごとに flush されるため、再実行はキャッシュ済みをスキップして
//     未了分だけ進める（resume 安全）。
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
	"strings"
	"syscall"
	"time"

	"omatsuri-map/internal/services"
)

// festivalDoc is the minimal shape of a festivals.json entry. The summary-warm
// tool only needs the Wikipedia title it will warm the five sections for; a
// document with an empty wikipedia_title falls back to the Japanese label,
// which is the value the panel actually opens on the detail request.
type festivalDoc struct {
	WikipediaTitle string `json:"wikipedia_title"`
	LabelJa        string `json:"label_ja"`
}

func loadTitles(jsonPath string) []string {
	raw, err := os.ReadFile(jsonPath)
	if err != nil {
		log.Fatalf("load %s: %v", jsonPath, err)
	}
	var docs []festivalDoc
	if err := json.Unmarshal(raw, &docs); err != nil {
		log.Fatalf("parse %s: %v", jsonPath, err)
	}
	seen := map[string]bool{}
	out := make([]string, 0, len(docs))
	for _, d := range docs {
		t := strings.TrimSpace(d.WikipediaTitle)
		if t == "" {
			t = strings.TrimSpace(d.LabelJa)
		}
		if t == "" || seen[t] {
			continue
		}
		seen[t] = true
		out = append(out, t)
	}
	sort.Strings(out)
	return out
}

func main() {
	jsonPath := flag.String("json", "frontend/festivals.json", "festivals list JSON")
	limit := flag.Int("limit", 0, "only process first N titles (0 = all)")
	dryRun := flag.Bool("dry-run", false, "load titles and print sample, then exit (no LLM)")
	flag.Parse()

	titles := loadTitles(*jsonPath)
	if *limit > 0 && *limit < len(titles) {
		titles = titles[:*limit]
	}
	if *dryRun {
		print := 5
		if len(titles) < print {
			print = len(titles)
		}
		fmt.Printf("titles=%d (dry-run)\n", len(titles))
		for _, t := range titles[:print] {
			fmt.Println("  ", t)
		}
		return
	}
	fmt.Printf("warming %d titles (LLM enabled, serial, resume-safe)\n", len(titles))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	done := 0
	skipped := 0
	stopped := false
	for i, t := range titles {
		if ctx.Err() != nil {
			stopped = true
			break
		}
		start := time.Now()
		_, _, _, _, _, transient, err := services.FetchPanelSections(ctx, t)
		elapsed := time.Since(start)
		if err != nil {
			skipped++
			log.Printf("[%3d/%d] %s SKIP err=%v transient=%v (%.0fs)\n", i+1, len(titles), t, err, transient, elapsed.Seconds())
			if transient {
				log.Printf("    transient; retry after the LLM is free")
			}
			continue
		}
		done++
		log.Printf("[%3d/%d] %s OK (%.0fs) done=%d skipped=%d\n", i+1, len(titles), t, elapsed.Seconds(), done, skipped)
	}

	fmt.Printf("warm-up %s: done=%d skipped=%d\n", map[bool]string{true: "stopped (SIGINT)", false: "complete"}[stopped], done, skipped)
	if stopped {
		os.Exit(130)
	}
}
