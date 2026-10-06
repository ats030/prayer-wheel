package handlers

import (
	"testing"

	"midokoro-map/internal/shiseki/services"
)

func TestToPayloadOmitsRawTextForSummaryOnlyDesignations(t *testing.T) {
	blocks := []services.WikipediaTextBlock{{Text: "原文"}}
	raw := services.PanelSection{Blocks: blocks, SourceURL: "https://ja.wikipedia.org/wiki/X"}
	summarized := services.PanelSection{Summary: "要約", Blocks: blocks, SourceURL: raw.SourceURL}

	for _, designation := range []string{"special", "national", "local"} {
		if !summaryOnlyDesignations[designation] {
			t.Fatalf("%s must be summary-only", designation)
		}
	}
	for _, designation := range []string{"undesig", ""} {
		if summaryOnlyDesignations[designation] {
			t.Fatalf("%q must keep the raw text until warmed", designation)
		}
	}

	got := toPayload(summarized, true)
	if got.Summary != "要約" || len(got.Blocks) != 0 || got.RawOmitted || got.SourceURL != raw.SourceURL {
		t.Fatalf("summary-only section must carry the summary and no raw text: %+v", got)
	}
	got = toPayload(raw, true)
	if len(got.Blocks) != 0 || !got.RawOmitted || got.SourceURL != raw.SourceURL {
		t.Fatalf("unsummarized section must drop the raw text and flag it: %+v", got)
	}
	if got = toPayload(services.PanelSection{}, true); got.RawOmitted {
		t.Fatal("a section with no text must not claim omitted raw text")
	}
	if got = toPayload(raw, false); len(got.Blocks) != 1 || got.RawOmitted {
		t.Fatalf("other designations keep the raw text: %+v", got)
	}
}
