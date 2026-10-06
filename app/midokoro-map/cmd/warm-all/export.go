package main

import (
	"encoding/json"
	"fmt"
	"midokoro-map/internal/shared"
	tk "midokoro-map/internal/tokusan/services"
	"os"
	"path/filepath"
	"time"
)

type sourceProof struct {
	Version    int               `json:"version"`
	Complete   bool              `json:"complete"`
	StartedAt  time.Time         `json:"started_at"`
	FinishedAt time.Time         `json:"finished_at"`
	Rosters    map[string]string `json:"rosters"`
}

func exportSummaries(root, output string, service *tk.TokusanService) error {
	b, err := os.ReadFile(filepath.Join(root, "source-recheck.json"))
	if err != nil {
		return err
	}
	var proof sourceProof
	if err = json.Unmarshal(b, &proof); err != nil {
		return err
	}
	now := time.Now().UTC()
	if proof.Version != 6 || !proof.Complete || proof.StartedAt.IsZero() || proof.FinishedAt.Before(proof.StartedAt) || proof.FinishedAt.After(now) || now.Sub(proof.FinishedAt) > 24*time.Hour {
		return fmt.Errorf("export requires a successful full source recheck within 24 hours")
	}
	p := shared.PublishedSummaries{Version: 6, CheckedAt: proof.FinishedAt, Rosters: proof.Rosters, Counts: map[string]int{}, Items: map[string]map[string]map[string]shared.PreparedSection{}}
	for kind := range required {
		items, err := load(kind, service)
		if err != nil {
			return err
		}
		if hash(items) != proof.Rosters[kind] {
			return fmt.Errorf("%s roster changed since source recheck", kind)
		}
		p.Counts[kind] = len(items)
		p.Items[kind] = map[string]map[string]shared.PreparedSection{}
		for _, it := range items {
			c := read(filepath.Join(root, "items", kind, shared.SourceHash(it.ID)+".json"))
			if !complete(c, kind, it) || c.CheckedAt.Before(proof.StartedAt) || c.CheckedAt.After(proof.FinishedAt) {
				return fmt.Errorf("%s/%s not checked in successful source pass", kind, it.ID)
			}
			p.Items[kind][it.ID] = c.Sections
		}
	}
	if err := p.Validate(); err != nil {
		return err
	}
	return writeJSON(output, p)
}
