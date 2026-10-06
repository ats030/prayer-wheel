package services

import (
	"strings"
	"testing"
)

func TestFlattenSectionContent(t *testing.T) {
	c := SectionContent{Summary: `{"summary":"平たい要約","items":[{"label":"A","value":"1"}]}`, Items: nil}
	got := sanitizeSectionContent(c)
	if got.Summary != "平たい要約" {
		t.Fatalf("summary = %q, want 平たい要約", got.Summary)
	}
	if len(got.Items) != 1 || got.Items[0].Value != "1" {
		t.Fatalf("items = %+v, want 1 item Value=1", got.Items)
	}
}

func TestFlattenSectionContentTruncatedInner(t *testing.T) {
	// Real-world corruption shape: outer object closes, but the nested
	// object stored in "summary" was truncated before its closing "]" / "}".
	c := SectionContent{Summary: `{"summary":"あつみ温泉は、821年の開湯伝説から現代の温泉街再生に至るまで、歴史的な変遷を経て発展してきた。","items":[{"label":"開湯伝説","value":"821年の開湯伝説が伝えられている。"},{"label":"1971年","value":"「国民宿舎」が開業した。"}]}`}
	got := sanitizeSectionContent(c)
	if got.Summary != "あつみ温泉は、821年の開湯伝説から現代の温泉街再生に至るまで、歴史的な変遷を経て発展してきた。" {
		t.Fatalf("summary = %q, want the plain prose lead", got.Summary)
	}
	if len(got.Items) != 2 {
		t.Fatalf("items = %+v, want 2 items recovered from the truncated inner object", got.Items)
	}
	if strings.Contains(got.Summary, "{") || strings.Contains(got.Summary, "\"") {
		t.Fatalf("summary must not leak raw JSON: %q", got.Summary)
	}
}

func TestFlattenSectionContentNestedTruncatedDeep(t *testing.T) {
	// A double-encoded body (an object stored inside "summary") that ends
	// with an unterminated value followed by a stray long digit run — the
	// exact shape found in cached access data for one onsen.
	c := SectionContent{Summary: `{"summary":"JR二本松駅からバスで岳温泉へ向かい、そこからタクシーや徒歩、または登山道を経てくろがね小屋へ到達する。","items":[{"label":"電車","value":"JR二本松駅からバス"},{"label":"タクシー","value":"岳温泉からタクシーで15分"},10000000000000000000000000000000}`}
	got := sanitizeSectionContent(c)
	if got.Summary == "" {
		t.Fatalf("summary empty; expected a recovered plain-prose lead")
	}
	if strings.HasPrefix(strings.TrimSpace(got.Summary), "{") {
		t.Fatalf("summary must be plain prose, got JSON: %q", got.Summary)
	}
}

func TestFlattenSectionContentPlain(t *testing.T) {
	c := SectionContent{Summary: "普通に平たい", Items: []SectionItem{{Label: "B"}}}
	got := sanitizeSectionContent(c)
	if got.Summary != "普通に平たい" {
		t.Fatalf("summary = %q, unchanged expected", got.Summary)
	}
	if got.Items[0].Label != "B" {
		t.Fatalf("items changed: %+v", got.Items)
	}
}

func TestFlattenSectionContentNotJSON(t *testing.T) {
	c := SectionContent{Summary: "not json but looks like", Items: nil}
	got := sanitizeSectionContent(c)
	if got.Summary != c.Summary {
		t.Fatalf("summary changed = %q", got.Summary)
	}
}

func TestFlattenSectionContentMalformedJSONNotSummary(t *testing.T) {
	// An inner object that is valid JSON but not a summary object must not be
	// surfaced as the summary text verbatim.
	c := SectionContent{Summary: `{"foo":"bar"}`}
	got := sanitizeSectionContent(c)
	if got.Summary != "" {
		t.Fatalf("expected empty summary for irrelevant JSON, got %q", got.Summary)
	}
}

func TestFlattenSectionContentOverClosed(t *testing.T) {
	// Real-world corruption shape: the nested object stored in "summary" is
	// VALID JSON but its items array is over-closed with an extra "]]" (this
	// is the shape the model emits when done_reason=length cuts the stream
	// mid-object). decodeSectionContent must still yield the plain-prose lead
	// instead of leaking the JSON envelope into the UI.
	c := SectionContent{Summary: `{"summary":"荒湯は、奈良時代から交通の要所として栄え、明治以降の鉱山開発や地熱発電所の稼働を経て現在の景観に至るまでの変遷を辿る。","items":[{"label":"奈良時代","value":"軍事上、交通上の要点として重要な位置にあった。"},{"label":"737年（天平9年）","value":"羽前街道が新設され、のちに羽後街道が開かれた。"}]]}`}
	got := decodeSectionContent(encodeSectionContent(c))
	if strings.ContainsAny(got.Summary, "{}\"") {
		t.Fatalf("summary must not leak raw JSON: %q", got.Summary)
	}
	if !strings.HasPrefix(got.Summary, "荒湯は") {
		t.Fatalf("expected the plain-prose lead, got %q", got.Summary)
	}
}

func TestFlattenSectionContentCodeFence(t *testing.T) {
	// Real-world corruption shape: the LLM wrapped its answer in a markdown
	// ```json ... ``` fence, so the stored "summary" string is the fence plus
	// an empty nested object. decodeSectionContent must strip the fence and
	// still emit plain prose (or empty) rather than the visible ``` fence.
	c := SectionContent{Summary: "```json\n{\"summary\":\"\",\"items:[]}\n```", Items: []SectionItem{}}
	got := decodeSectionContent(encodeSectionContent(c))
	if strings.Contains(got.Summary, "```") {
		t.Fatalf("summary must not contain a code fence: %q", got.Summary)
	}
	if strings.ContainsAny(got.Summary, "{}") {
		t.Fatalf("summary must not leak a JSON object: %q", got.Summary)
	}
}

func TestRecoverPlainSummaryPreservesUTF8(t *testing.T) {
	// Regression for the byte-wise loop bug: recoverPlainSummary used to
	// iterate content[i] (one byte) and cast to a rune, turning multibyte
	// Japanese into Latin-1 mojibake. It must now pass UTF-8 through intact.
	body := `{"summary":"荒湯は、奈良時代から交通の要所として栄えた。","items":[]}`
	got := recoverPlainSummary(body)
	want := "荒湯は、奈良時代から交通の要所として栄えた。"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	// Escaped quote and backslash must still be de-escaped, not dropped.
	body2 := `{"summary":"温泉は\"源泉かけ流み\"で、古い宿も多い\\古い。","items":[]}`
	got2 := recoverPlainSummary(body2)
	want2 := `温泉は"源泉かけ流み"で、古い宿も多い\古い。`
	if got2 != want2 {
		t.Fatalf("escape handling broken: got %q, want %q", got2, want2)
	}
}

func TestRepairUnclosedJSON(t *testing.T) {
	var cases = []struct {
		in   string
		want string
		ok   bool
	}{
		{`{"a":1`, `{"a":1}`, true},
		{`{"a":[1,2`, `{"a":[1,2]}`, true},
		{`{"s":"x`, `{"s":"x"}`, true},
		{`{"a":[1,2]}`, `{"a":[1,2]}`, true}, // already balanced: unchanged
		{`[1}`, `[1}`, false},                // mismatched close
	}
	for _, tc := range cases {
		got, ok := repairUnclosedJSON(tc.in)
		if ok != tc.ok {
			t.Fatalf("repairUnclosedJSON(%q) ok=%v, want %v", tc.in, ok, tc.ok)
		}
		if tc.ok && got != tc.want {
			t.Fatalf("repairUnclosedJSON(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

var _ = strings.Contains
