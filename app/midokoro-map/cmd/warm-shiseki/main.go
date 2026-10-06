// summary-warm: 4セクション(歴史・遺構・見どころ・アクセス・指定・保存)の要約を
// LLMで一括生成し、data/shiseki/summaries.json に書き込むウォームアップツール。
//
// 用途: Cloud Run は実行中にLLMを呼べない(SHISEKI_SUMMARY_DISABLE=1)ため、
// 要約生成済みのキャッシュをイメージに同梱して配信する。本ツールはそのキャッシュを
// ローカルで生成する。
//
// 運用メモ:
//   - 指定区分の重い順(特別史跡→国→地方→未指定)に処理する。-designation で絞れる。
//   - LLMは localhost:11434。並列は1。
//   - SIGINT/Ctrl-Cで安全に停止。data/shiseki/summaries.json はPutごとに flush される
//     ため、再実行はキャッシュ済みをスキップして未了分だけ進める(resume安全)。
//   - app/midokoro-map で実行する(キャッシュは相対パス data/shiseki/summaries.json)。
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

	"midokoro-map/internal/shiseki/services"
)

type shisekiDoc struct {
	TitleJa     string `json:"title_ja"`
	Designation string `json:"designation"`
}

var designationRank = map[string]int{"special": 0, "national": 1, "local": 2, "undesig": 3}

func loadDocs(jsonPath, designation string) []shisekiDoc {
	raw, err := os.ReadFile(jsonPath)
	if err != nil {
		log.Fatalf("load %s: %v", jsonPath, err)
	}
	var docs []shisekiDoc
	if err := json.Unmarshal(raw, &docs); err != nil {
		log.Fatalf("parse %s: %v", jsonPath, err)
	}
	allowed := map[string]bool{}
	for _, d := range strings.Split(designation, ",") {
		if d = strings.TrimSpace(d); d != "" {
			allowed[d] = true
		}
	}
	seen := map[string]bool{}
	out := make([]shisekiDoc, 0, len(docs))
	for _, d := range docs {
		t := strings.TrimSpace(d.TitleJa)
		if t == "" || seen[t] || (len(allowed) > 0 && !allowed[d.Designation]) {
			continue
		}
		seen[t] = true
		out = append(out, shisekiDoc{TitleJa: t, Designation: d.Designation})
	}
	sort.SliceStable(out, func(i, j int) bool {
		ri, rj := designationRank[out[i].Designation], designationRank[out[j].Designation]
		if ri != rj {
			return ri < rj
		}
		return out[i].TitleJa < out[j].TitleJa
	})
	return out
}

func main() {
	jsonPath := flag.String("json", "frontend/assets/shiseki/shiseki.json", "shiseki list JSON")
	designation := flag.String("designation", "", "comma-separated designations to include (special,national,local,undesig; empty = all)")
	limit := flag.Int("limit", 0, "only process first N titles (0 = all)")
	dryRun := flag.Bool("dry-run", false, "load titles and print sample, then exit (no LLM)")
	flag.Parse()

	if services.SummaryDisabled() {
		log.Fatal("SHISEKI_SUMMARY_DISABLE is set; unset it to generate summaries")
	}
	docs := loadDocs(*jsonPath, *designation)
	if *limit > 0 && *limit < len(docs) {
		docs = docs[:*limit]
	}
	if *dryRun {
		fmt.Printf("titles=%d (dry-run)\n", len(docs))
		for _, d := range docs[:min(5, len(docs))] {
			fmt.Println("  ", d.TitleJa, d.Designation)
		}
		return
	}
	fmt.Printf("warming %d titles (LLM enabled, serial, resume-safe)\n", len(docs))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	done, skipped, summarized := 0, 0, 0
	stopped := false
	for i, d := range docs {
		if ctx.Err() != nil {
			stopped = true
			break
		}
		start := time.Now()
		history, remains, access, highlights, transient, err := services.FetchPanelSections(ctx, d.TitleJa)
		elapsed := time.Since(start)
		if err != nil {
			skipped++
			log.Printf("[%5d/%d] %s SKIP err=%v transient=%v (%.0fs)", i+1, len(docs), d.TitleJa, err, transient, elapsed.Seconds())
			continue
		}
		done++
		n := 0
		for _, s := range []services.PanelSection{history, remains, access, highlights} {
			if s.Summary != "" {
				n++
			}
		}
		if n > 0 {
			summarized++
		}
		log.Printf("[%5d/%d] %s OK summaries=%d (%.0fs) done=%d summarized=%d skipped=%d", i+1, len(docs), d.TitleJa, n, elapsed.Seconds(), done, summarized, skipped)
	}

	fmt.Printf("warm-up %s: done=%d summarized=%d skipped=%d\n", map[bool]string{true: "stopped (SIGINT)", false: "complete"}[stopped], done, summarized, skipped)
	if stopped {
		os.Exit(130)
	}
}
