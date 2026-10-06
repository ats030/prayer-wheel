// official-warm: 公的資料品目(農林水産省・林野庁)の「歴史」「産地・製法」を
// LLMで構造化して data/tokusan/official_summaries.json に書き込むウォームアップツール。
//
// 用途: Cloud Run は実行中にLLMを呼べない(TOKUSAN_SUMMARY_DISABLE=1)ため、
// 要約生成済みのキャッシュをイメージに同梱して配信する。本ツールはその
// キャッシュをローカルで生成する(summary-warmがWikipedia品目に対応するもの。
// 本ツールは公式品目に対応する)。
//
// 運用メモ:
//   - LLMは localhost:11434 経由で、品目×セクションずつ直列に行う。
//   - data/tokusan/official_summaries.json は書き込みごとに flush されるため、再実行は
//     キャッシュ済みをスキップして未了分だけ進める(resume安全)。SIGINTで安全に停止する。
//   - 原文の無い(歴史・製造方法が空の)品目は「なし」として保存し、再実行しない。
//   - 終了時にセクションごとの内容あり件数を表示する。
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"midokoro-map/internal/tokusan/services"
)

func main() {
	dbPath := flag.String("db", "data/tokusan/tokusan.db", "tokusan SQLite DB")
	limit := flag.Int("limit", 0, "only process first N items (0 = all)")
	only := flag.String("only", "", "only process items whose QID contains this substring")
	dryRun := flag.Bool("dry-run", false, "list items and exit (no LLM)")
	flag.Parse()

	service, err := services.NewTokusanService(*dbPath)
	if err != nil {
		log.Fatalf("load %s: %v", *dbPath, err)
	}
	defer service.Close()

	var items []services.Tokusan
	for _, t := range service.GetAll() {
		if t.Description == "" {
			continue
		}
		if *only != "" && !contains(t.QID, *only) {
			continue
		}
		items = append(items, t)
	}
	if *limit > 0 && *limit < len(items) {
		items = items[:*limit]
	}
	if *dryRun {
		fmt.Printf("official items=%d (dry-run)\n", len(items))
		for _, t := range items {
			fmt.Println("  ", t.QID, t.LabelJA)
		}
		return
	}
	fmt.Printf("warming %d official items (serial, resume-safe)\n", len(items))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	sections := []string{"history", "production"}
	filled := map[string]int{}
	done, skipped := 0, 0
	stopped := false
	for i, t := range items {
		if ctx.Err() != nil {
			stopped = true
			break
		}
		itemStart := time.Now()
		var generated, skippedSections []string
		for _, key := range sections {
			text := sourceText(service, t.QID, key)
			if services.HasOfficialSummary(t.QID, key) {
				skippedSections = append(skippedSections, key)
				continue
			}
			if text == "" {
				// 原文が無い: 「なし」を保存して再実行されないようにする。
				if _, err := services.SummarizeOfficialSection(ctx, t.QID, key, text); err != nil {
					log.Printf("[%3d/%d] %s %s ERR %v", i+1, len(items), t.QID, key, err)
					continue
				}
				if content, ok := services.GetOfficialSummary(t.QID, key); ok &&
					!(content.Summary == services.SummaryNone && len(content.Items) == 0) {
					filled[key]++
					generated = append(generated, key)
				}
				continue
			}
			content, err := services.SummarizeOfficialSection(ctx, t.QID, key, text)
			if err != nil {
				log.Printf("[%3d/%d] %s %s ERR %v", i+1, len(items), t.QID, key, err)
				continue
			}
			if content.Summary == "" && len(content.Items) == 0 {
				continue
			}
			filled[key]++
			generated = append(generated, key)
		}
		if len(generated) == 0 && len(skippedSections) == 0 {
			skipped++
		}
		done++
		log.Printf("[%3d/%d] %s %s OK (%.0fs) new=%v cached=%v", i+1, len(items), t.QID, t.LabelJA, time.Since(itemStart).Seconds(), generated, skippedSections)
	}

	fmt.Printf("official warm-up %s: done=%d empty_skipped=%d\n",
		map[bool]string{true: "stopped", false: "complete"}[stopped], done, skipped)
	for _, key := range sections {
		fmt.Printf("  %-12s %d/%d\n", key, filled[key], done)
	}
	if stopped {
		os.Exit(130)
	}
}

// sourceText returns the raw text for an official item's section: the history
// column for history, the production column for production.
func sourceText(service *services.TokusanService, qid, section string) string {
	switch section {
	case "history":
		return service.GetHistory(qid)
	case "production":
		return service.GetProduction(qid)
	}
	return ""
}

func contains(s, substr string) bool {
	return strings.Contains(s, substr)
}
