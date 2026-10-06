package services

import (
	"strings"
	"testing"
)

// These fixtures reproduce the corruption shapes actually found cached in
// data/onsen/summaries.json: a valid outer object whose "summary" field holds a
// nested {summary, items} object that was truncated (trailing "]" / "}"
// missing) or left with a stray numeric token where the closing bracket
// should have been. Every one of them must decode to plain prose in
// SectionContent.Summary instead of the raw JSON blob.
func TestDecodeSectionContent_CorruptedCache(t *testing.T) {
	cases := []struct {
		name string
		// backtick raw strings: the inner object is stored as a JSON string
		// inside the outer, so its quotes appear escaped (\"), exactly as in
		// the real cache values.
		json string
	}{
		{"inner truncated before closing brackets",
			`{"summary":"{\"summary\":\"あつみ温泉は、821年の開湯伝説から現代の温泉街再生に至るまで、歴史的な変遷を経て発展してきた。\",\"items\":[{\"label\":\"開湯伝説\",\"value\":\"821年の開湯伝説が伝えられている。\"},{\"label\":\"2019年\",\"value\":\"山形県沖地震で被災し、同年10月に国民保養温泉地に指定された。\"]]}","items":[]}`},
		{"stray numeric token instead of closing brace",
			`{"summary":"{\"summary\":\"JR二本松駅からバスで岳温泉へ向かい、そこからタクシーや徒歩、または登山道を経てくろがね小屋へ到達する。\",\"items\":[{\"label\":\"電車\",\"value\":\"JR二本松駅からバス\"},{\"label\":\"タクシー\",\"value\":\"岳温泉からタクシーで15分\"},10000000000000000000000000000000","items":[]}`},
		{"deeply nested object with unterminated value",
			`{"summary":"{\"summary\":\"「国民宿舎いろは島」の開業および改装の経緯。\",\"items\":[{\"label\":\"1971年（昭和46年）9月\",\"value\":\"「国民宿舎いろは島」開業。\"},{\"label\":\"1992年（平成4年）2月\",\"value\":\"「国民宿舎いろは島」2度目の改装。\"]}]","items":[]}`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := decodeSectionContent(tc.json)
			if got.Summary == "" {
				t.Fatalf("summary empty; expected a recovered plain-prose lead for %s", tc.name)
			}
			if strings.ContainsAny(strings.TrimSpace(got.Summary), "{}") {
				t.Fatalf("summary must not contain raw JSON for %s, got %q", tc.name, got.Summary)
			}
		})
	}
}
