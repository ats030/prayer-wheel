package main

import (
	"midokoro-map/internal/shared"
	"path/filepath"
	"testing"
)

func TestResumeRequiresEverySectionAndSameInput(t *testing.T) {
	it := item{ID: "Q1", Title: "史跡"}
	c := checkpoint{Version: 5, Kind: "shiseki", ID: it.ID, InputHash: hash(it), Sections: map[string]shared.PreparedSection{}}
	for _, key := range required["shiseki"] {
		c.Sections[key] = shared.Prepared("", nil, false, "", "", true)
	}
	path := filepath.Join(t.TempDir(), "items/Q1.json")
	if err := writeJSON(path, c); err != nil {
		t.Fatal(err)
	}
	if !complete(read(path), "shiseki", it) {
		t.Fatal("valid checkpoint not resumable")
	}
	failed := c
	failed.Sections = nil
	failed.Error = "fetch failed"
	history := filepath.Join(filepath.Dir(path), "history")
	if err := saveCheckpoint(path, history, c, failed); err != nil {
		t.Fatal(err)
	}
	archived := filepath.Join(history, "shiseki", shared.SourceHash(it.ID), hash(c)+".json")
	if !complete(read(archived), "shiseki", it) {
		t.Fatal("failed refresh lost previous completed summary")
	}
	if complete(read(path), "shiseki", it) {
		t.Fatal("failed refresh passed current audit")
	}
	if err := writeJSON(path, c); err != nil {
		t.Fatal(err)
	}
	c.Sections["history"] = shared.Prepared("", nil, false, "", "", false)
	if complete(c, "shiseki", it) {
		t.Fatal("failed section passed cutover audit")
	}
	delete(c.Sections, "about")
	if complete(c, "shiseki", it) {
		t.Fatal("old sections without overview passed")
	}
	if complete(read(path), "onsen", it) {
		t.Fatal("category mismatch passed")
	}
	it.Description = "新しい原文"
	if complete(read(path), "shiseki", it) {
		t.Fatal("changed input not invalidated")
	}
	if complete(read(path+"missing"), "shiseki", it) {
		t.Fatal("missing checkpoint passed")
	}
}
