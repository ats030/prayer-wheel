package handlers

import (
	"encoding/json"
	"strings"
	"testing"

	"omatsuri-map/internal/services"
)

func TestToPayloadOmitsRawText(t *testing.T) {
	raw := []services.WikipediaTextBlock{{Heading: "歴史", Text: "原文の段落"}}
	for _, section := range []services.PanelSection{
		{Summary: "要約", Blocks: raw, SourceURL: "https://ja.wikipedia.org/wiki/x"},
		{Blocks: raw, SourceURL: "https://ja.wikipedia.org/wiki/x"},
	} {
		encoded, err := json.Marshal(toPayload(section))
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(encoded), "原文の段落") || strings.Contains(string(encoded), "blocks") {
			t.Fatalf("raw article text must not be sent: %s", encoded)
		}
		if !strings.Contains(string(encoded), "source_url") {
			t.Fatalf("attribution lost: %s", encoded)
		}
	}
	if got := toPayload(services.PanelSection{Summary: "要約"}); got.Summary != "要約" {
		t.Fatalf("summary lost: %+v", got)
	}
}
