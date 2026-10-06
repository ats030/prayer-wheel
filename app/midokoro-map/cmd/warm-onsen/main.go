// summary-warm: 4セクション(歴史・名物・アクセス・観光)の構造化要約を
// LLMで一括生成し、data/onsen/summaries.json に書き込むウォームアップツール。
//
// 用途: Cloud Run は実行中にLLMを呼べないため、要約生成済みのキャッシュを
// イメージと同梱して配信する。本ツールはそのキャッシュをローカルで生成する。
//
// 運用メモ:
//   - LLMは localhost の Open WebUI/proxy (localhost:11434) 経由。同じ proxy
//     が生成を1本同時にしか通さないため並列は1。
//   - 503(busy)は再試行してよい一時的エラー。1パスで未完了のセクションは
//     再実行で再挑戦する（キャッシュ済みはLLMを呼ばない）。
//   - プロセスはSIGINT/Ctrl-Cで安全に停止。data/onsen/summaries.json はPutごとに
//     flush されるため、再実行はキャッシュ済みをスキップして未了分だけ
//     進める（resume安全）。
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

	"midokoro-map/internal/onsen/services"
)

type onsenDoc struct {
	TitleJa string `json:"title_ja"`
	QID     string `json:"qid"`
}

func loadOnsenDocs(jsonPath string) []onsenDoc {
	raw, err := os.ReadFile(jsonPath)
	if err != nil {
		log.Fatalf("load %s: %v", jsonPath, err)
	}
	var docs []onsenDoc
	if err := json.Unmarshal(raw, &docs); err != nil {
		log.Fatalf("parse %s: %v", jsonPath, err)
	}
	seen := map[string]bool{}
	out := make([]onsenDoc, 0, len(docs))
	for _, d := range docs {
		t := strings.TrimSpace(d.TitleJa)
		if t == "" || seen[t] {
			continue
		}
		seen[t] = true
		out = append(out, onsenDoc{TitleJa: t, QID: strings.TrimSpace(d.QID)})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].TitleJa < out[j].TitleJa })
	return out
}

func main() {
	jsonPath := flag.String("json", "frontend/assets/onsen/onsen.json", "onsen list JSON")
	limit := flag.Int("limit", 0, "only process first N titles (0 = all)")
	dryRun := flag.Bool("dry-run", false, "load titles and print sample, then exit (no LLM)")
	flag.Parse()

	docs := loadOnsenDocs(*jsonPath)
	if *limit > 0 && *limit < len(docs) {
		docs = docs[:*limit]
	}
	if *dryRun {
		print := 5
		if len(docs) < print {
			print = len(docs)
		}
		fmt.Printf("titles=%d (dry-run)\n", len(docs))
		for _, d := range docs[:print] {
			fmt.Println("  ", d.TitleJa, d.QID)
		}
		return
	}
	fmt.Printf("warming %d titles (LLM enabled, serial, resume-safe)\n", len(docs))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	done := 0
	skipped := 0
	stopped := false
	for i, d := range docs {
		if ctx.Err() != nil {
			stopped = true
			break
		}
		start := time.Now()
		_, _, _, _, _, transient, err := services.FetchPanelSections(ctx, d.TitleJa, d.QID)
		elapsed := time.Since(start)
		if err != nil {
			skipped++
			log.Printf("[%3d/%d] %s SKIP err=%v transient=%v (%.0fs)\n", i+1, len(docs), d.TitleJa, err, transient, elapsed.Seconds())
			if transient {
				log.Printf("    transient; retry after the LLM is free")
			}
			continue
		}
		done++
		log.Printf("[%3d/%d] %s OK (%.0fs) done=%d skipped=%d\n", i+1, len(docs), d.TitleJa, elapsed.Seconds(), done, skipped)
	}

	fmt.Printf("warm-up %s: done=%d skipped=%d\n", map[bool]string{true: "stopped (SIGINT)", false: "complete"}[stopped], done, skipped)
	if stopped {
		os.Exit(130)
	}
}
