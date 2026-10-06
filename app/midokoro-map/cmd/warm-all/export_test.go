package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestExportRejectsMissingFailedAndStaleProof(t *testing.T) {
	root := t.TempDir()
	output := filepath.Join(root, "published.json")
	if err := os.WriteFile(output, []byte("keep previous publication"), 0600); err != nil {
		t.Fatal(err)
	}
	if exportSummaries(root, output, nil) == nil {
		t.Fatal("missing proof accepted")
	}
	for _, proof := range []sourceProof{
		{Version: 6, Complete: false, StartedAt: time.Now().Add(-time.Hour), FinishedAt: time.Now()},
		{Version: 6, Complete: true, StartedAt: time.Now().Add(-48 * time.Hour), FinishedAt: time.Now().Add(-25 * time.Hour)},
	} {
		if err := writeJSON(filepath.Join(root, "source-recheck.json"), proof); err != nil {
			t.Fatal(err)
		}
		if exportSummaries(root, output, nil) == nil {
			t.Fatal("failed/stale proof accepted")
		}
	}
	b, _ := os.ReadFile(output)
	if string(b) != "keep previous publication" {
		t.Fatal("rejected export destroyed previous publication")
	}
}
