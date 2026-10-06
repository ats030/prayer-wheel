// summary-warm: 詳細パネルの節(概要・歴史・産地・製法・購入・観光)の構造化要約を
// LLMで一括生成し、data/tokusan/summaries.json に書き込むウォームアップツール。
//
// 用途: Cloud Run は実行中にLLMを呼べない(TOKUSAN_SUMMARY_DISABLE=1)ため、
// 要約生成済みのキャッシュをイメージに同梱して配信する。本ツールはその
// キャッシュをローカルで生成する。
//
// 運用メモ:
//   - LLMは localhost:11434 経由で、生成は1本ずつ直列に行う。
//   - data/tokusan/summaries.json はPutごとに flush されるため、再実行はキャッシュ済みを
//     スキップして未了分だけ進める(resume安全)。SIGINTで安全に停止する。
//   - 終了時に節ごとの内容あり件数を表示する。購入・観光の掲載可否の判断に使う。
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"midokoro-map/internal/tokusan/services"
)

func main() {
	dbPath := flag.String("db", "data/tokusan/tokusan.db", "tokusan SQLite DB")
	limit := flag.Int("limit", 0, "only process first N items (0 = all)")
	dryRun := flag.Bool("dry-run", false, "list titles and exit (no LLM)")
	flag.Parse()

	service, err := services.NewTokusanService(*dbPath)
	if err != nil {
		log.Fatalf("load %s: %v", *dbPath, err)
	}
	defer service.Close()
	items := service.GetAll()
	if *limit > 0 && *limit < len(items) {
		items = items[:*limit]
	}
	if *dryRun {
		fmt.Printf("items=%d (dry-run)\n", len(items))
		for _, t := range items {
			fmt.Println("  ", t.QID, t.WikipediaTitle())
		}
		return
	}
	fmt.Printf("warming %d items (serial, resume-safe)\n", len(items))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	filled := map[string]int{}
	done, skipped, retry := 0, 0, 0
	stopped := false
	for i, t := range items {
		if ctx.Err() != nil {
			stopped = true
			break
		}
		title := t.WikipediaTitle()
		if title == "" {
			skipped++
			log.Printf("[%3d/%d] %s SKIP no Wikipedia title", i+1, len(items), t.QID)
			continue
		}
		start := time.Now()
		sections, transient, err := services.FetchPanelSections(ctx, title)
		elapsed := time.Since(start)
		if err != nil {
			skipped++
			log.Printf("[%3d/%d] %s SKIP err=%v transient=%v (%.0fs)", i+1, len(items), title, err, transient, elapsed.Seconds())
			continue
		}
		var keys []string
		for key, section := range sections {
			if section.SectionRetry() {
				retry++
			}
			if section.Summary != "" || len(section.Items) > 0 {
				filled[key]++
				keys = append(keys, key)
			}
		}
		done++
		log.Printf("[%3d/%d] %s OK (%.0fs) filled=%v", i+1, len(items), title, elapsed.Seconds(), keys)
	}

	fmt.Printf("warm-up %s: done=%d skipped=%d retry_sections=%d\n", map[bool]string{true: "stopped", false: "complete"}[stopped], done, skipped, retry)
	for _, key := range []string{"about", "history", "production", "visit"} {
		fmt.Printf("  %-10s %d/%d\n", key, filled[key], done)
	}
	if stopped {
		os.Exit(130)
	}
}
