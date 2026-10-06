// warm-all owns offline generation for all four maps. It never modifies the
// public display policy or deploys: publication follows a separate full audit.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	om "midokoro-map/internal/omatsuri/services"
	on "midokoro-map/internal/onsen/services"
	"midokoro-map/internal/shared"
	sh "midokoro-map/internal/shiseki/services"
	tk "midokoro-map/internal/tokusan/services"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"
)

var required = map[string][]string{
	"shiseki":  {"about", "history", "remains", "access", "highlights"},
	"omatsuri": {"about", "history", "highlights", "flow", "access", "tourism"},
	"onsen":    {"about", "history", "food", "efficacy", "access", "tourism"},
	"tokusan":  {"about", "history", "production", "visit"},
}

type item struct {
	OfficialSourceHash string      `json:"official_source_hash,omitempty"`
	ID                 string      `json:"qid"`
	LocalID            string      `json:"id,omitempty"`
	Label              string      `json:"label_ja"`
	Title              string      `json:"title_ja"`
	WikiTitle          string      `json:"wikipedia_title"`
	Description        string      `json:"description"`
	DescriptionSource  string      `json:"description_source"`
	Source             string      `json:"source_url"`
	Designation        string      `json:"designation"`
	Official           *tk.Tokusan `json:"official,omitempty"`
}
type checkpoint struct {
	Version   int                               `json:"version"`
	Kind      string                            `json:"kind"`
	ID        string                            `json:"id"`
	InputHash string                            `json:"input_hash"`
	CheckedAt time.Time                         `json:"checked_at"`
	Sections  map[string]shared.PreparedSection `json:"sections"`
	Error     string                            `json:"error,omitempty"`
}

func hash(v any) string { b, _ := json.Marshal(v); return shared.SourceHash(string(b)) }
func complete(c checkpoint, kind string, it item) bool {
	return c.Version == 5 && c.Kind == kind && c.ID == it.ID && c.InputHash == hash(it) && c.Error == "" && shared.SummaryComplete(c.Sections, required[kind])
}
func writeJSON(path string, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".checkpoint-*")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(b); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(name, path)
}
func read(path string) checkpoint {
	var c checkpoint
	b, err := os.ReadFile(path)
	if err == nil {
		_ = json.Unmarshal(b, &c)
	}
	return c
}

func saveCheckpoint(path, historyRoot string, previous, next checkpoint) error {
	if previous.Version > 0 && previous.Error == "" && shared.SummaryComplete(previous.Sections, required[previous.Kind]) {
		backup := filepath.Join(historyRoot, previous.Kind, shared.SourceHash(previous.ID), hash(previous)+".json")
		if err := writeJSON(backup, previous); err != nil {
			return err
		}
	}
	return writeJSON(path, next)
}
func load(kind string, service *tk.TokusanService) ([]item, error) {
	var items []item
	if kind == "tokusan" {
		roster, err := service.GetAllChecked()
		if err != nil {
			return nil, err
		}
		if len(roster) == 0 {
			return nil, fmt.Errorf("empty tokusan roster")
		}
		for _, t := range roster {
			v := t
			history, production, err := service.OfficialSourceChecked(t.QID)
			if err != nil {
				return nil, err
			}
			items = append(items, item{OfficialSourceHash: hash([]string{history, production}), ID: t.QID, Label: t.LabelJA, Title: t.WikipediaTitle(), Source: t.SourceURL, Description: t.Description, Official: &v})
		}
	} else {
		names := map[string]string{"shiseki": "shiseki.json", "onsen": "onsen.json", "omatsuri": "festivals.json"}
		b, err := os.ReadFile(filepath.Join("frontend/assets", kind, names[kind]))
		if err != nil {
			return nil, err
		}
		if err = json.Unmarshal(b, &items); err != nil {
			return nil, err
		}
	}
	if len(items) == 0 {
		return nil, fmt.Errorf("empty %s roster", kind)
	}
	seen := map[string]bool{}
	for i := range items {
		it := &items[i]
		if it.ID == "" {
			it.ID = it.LocalID
		}
		if it.ID == "" || seen[it.ID] {
			return nil, fmt.Errorf("%s: missing/duplicate identity %q", kind, it.ID)
		}
		seen[it.ID] = true
		if kind == "omatsuri" {
			it.Title = it.WikiTitle
			// Legacy festival descriptions without a verified source are not evidence.
			if it.DescriptionSource == "" {
				it.Description = ""
			}
		}
		if it.DescriptionSource == "" {
			it.DescriptionSource = it.Source
		}
		if kind == "onsen" && it.DescriptionSource == "" {
			it.Description = ""
		}
		if it.Description != "" && it.DescriptionSource == "" {
			it.Description = ""
		}
	}
	rank := map[string]int{"special": 0, "national": 1, "local": 2, "undesig": 3}
	sort.SliceStable(items, func(i, j int) bool {
		if kind == "shiseki" && rank[items[i].Designation] != rank[items[j].Designation] {
			return rank[items[i].Designation] < rank[items[j].Designation]
		}
		return items[i].Title+items[i].ID < items[j].Title+items[j].ID
	})
	return items, nil
}
func prepare(ctx context.Context, kind string, it item, service *tk.TokusanService) (map[string]shared.PreparedSection, error) {
	switch kind {
	case "shiseki":
		return sh.PrepareSummary(ctx, it.Title, it.ID, it.Description, it.DescriptionSource)
	case "onsen":
		return on.PrepareSummary(ctx, it.Title, it.ID, it.Description, it.DescriptionSource)
	case "omatsuri":
		return om.PrepareSummary(ctx, it.Title, it.ID, it.Description, it.DescriptionSource)
	case "tokusan":
		if it.Description != "" {
			return tk.PrepareOfficialSummary(ctx, service, *it.Official)
		}
		return tk.PrepareSummary(ctx, it.Title, it.ID, "", it.Source)
	}
	return nil, fmt.Errorf("unknown kind %s", kind)
}
func main() {
	kinds := flag.String("kinds", "shiseki,omatsuri,onsen,tokusan", "categories, serial order")
	root := flag.String("work", "data/summary-work", "private work directory")
	limit := flag.Int("limit", 0, "limit attempted items per pass (audit always checks full roster)")
	audit := flag.Bool("audit", false, "read-only full completion check; nonzero until all ready")
	flag.Parse()
	service, err := tk.NewTokusanService("data/tokusan/tokusan.db")
	if err != nil {
		log.Fatal(err)
	}
	defer service.Close()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	allReady := true
	for _, kind := range strings.Split(*kinds, ",") {
		if required[kind] == nil {
			log.Fatalf("unknown kind %q", kind)
		}
		items, err := load(kind, service)
		if err != nil {
			log.Fatal(err)
		}
		rosterHash := hash(items)
		attempted, ready := 0, 0
		for _, it := range items {
			p := filepath.Join(*root, "items", kind, shared.SourceHash(it.ID)+".json")
			if complete(read(p), kind, it) {
				ready++
			}
		}
		status := func() map[string]any {
			return map[string]any{"version": 5, "kind": kind, "roster_hash": rosterHash, "total": len(items), "complete": ready, "pending": len(items) - ready, "attempted": attempted, "checked_at": time.Now().UTC()}
		}
		flushStatus := func() {
			if !*audit {
				if e := writeJSON(filepath.Join(*root, "status", kind+".json"), status()); e != nil {
					log.Fatal(e)
				}
			}
		}
		flushStatus()
		for i, it := range items {
			path := filepath.Join(*root, "items", kind, shared.SourceHash(it.ID)+".json")
			c := read(path)
			wasComplete := complete(c, kind, it)
			didAttempt := false
			if !complete(c, kind, it) && !*audit && (*limit == 0 || attempted < *limit) && ctx.Err() == nil {
				attempted++
				didAttempt = true
				previous := c
				sections, e := prepare(ctx, kind, it, service)
				c = checkpoint{Version: 5, Kind: kind, ID: it.ID, InputHash: hash(it), CheckedAt: time.Now().UTC(), Sections: sections}
				if e != nil {
					c.Error = e.Error()
				}
				if e = saveCheckpoint(path, filepath.Join(*root, "history"), previous, c); e != nil {
					log.Fatal(e)
				}
				log.Printf("%s [%d/%d] %s complete=%v error=%s", kind, i+1, len(items), it.Label, complete(c, kind, it), c.Error)
			}
			if !wasComplete && complete(c, kind, it) {
				ready++
			}
			if didAttempt {
				flushStatus()
			}
		}
		flushStatus()
		b, _ := json.Marshal(status())
		fmt.Println(string(b))
		if ready != len(items) {
			allReady = false
		}
	}
	if ctx.Err() != nil {
		os.Exit(130)
	}
	if !allReady {
		os.Exit(2)
	}
}
