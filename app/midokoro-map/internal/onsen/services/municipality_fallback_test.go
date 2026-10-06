package services

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"testing"
)

// fakePlace renders a wbgetentities response for one item with the given P31
// classes, comma-separated P131 parents, and jawiki sitelink ("" omits each
// part).
func fakePlace(qid string, p31 []string, p131, jawiki string) string {
	claim := func(id string) string {
		return fmt.Sprintf(`{"mainsnak":{"datavalue":{"type":"wikibase-entityid","value":{"id":%q}}}}`, id)
	}
	var classes []string
	for _, c := range p31 {
		classes = append(classes, claim(c))
	}
	claims := fmt.Sprintf(`"P31":[%s]`, strings.Join(classes, ","))
	if p131 != "" {
		var parents []string
		for _, id := range strings.Split(p131, ",") {
			parents = append(parents, claim(id))
		}
		claims += fmt.Sprintf(`,"P131":[%s]`, strings.Join(parents, ","))
	}
	sitelinks := "{}"
	if jawiki != "" {
		sitelinks = fmt.Sprintf(`{"jawiki":{"site":"jawiki","title":%q}}`, jawiki)
	}
	return fmt.Sprintf(`{"entities":{%q:{"claims":{%s},"sitelinks":%s}}}`, qid, claims, sitelinks)
}

func withPlaces(t *testing.T, places map[string]string) *int {
	t.Helper()
	municipalityTitleCache = sync.Map{}
	t.Cleanup(func() { municipalityTitleCache = sync.Map{} })
	var mu sync.Mutex
	calls := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls++
		mu.Unlock()
		if got := r.URL.Query().Get("props"); got != "claims|sitelinks" {
			t.Errorf("props = %q", got)
		}
		body, ok := places[r.URL.Query().Get("ids")]
		if !ok {
			http.Error(w, "unknown id", http.StatusBadRequest)
			return
		}
		w.Write([]byte(body))
	}))
	t.Cleanup(s.Close)
	withWikidataBase(t, s)
	return &calls
}

func TestResolveMunicipalityTitle(t *testing.T) {
	places := map[string]string{
		// direct: spring -> town whose sitelink differs from its label
		"Q1":  fakePlace("Q1", []string{"Q40434727"}, "Q10", ""),
		"Q10": fakePlace("Q10", []string{"Q1059478"}, "Q99", "古里町 (鹿児島市)"),
		// ward of a designated city is climbed through to the city
		"Q2":  fakePlace("Q2", []string{"Q40434727"}, "Q20", ""),
		"Q20": fakePlace("Q20", []string{"Q137773"}, "Q21", "中央区 (札幌市)"),
		"Q21": fakePlace("Q21", []string{"Q1749269"}, "Q99", "札幌市"),
		// prefecture / country are never accepted
		"Q3":  fakePlace("Q3", []string{"Q40434727"}, "Q99", ""),
		"Q99": fakePlace("Q99", []string{"Q50337"}, "Q17", "北海道"),
		"Q17": fakePlace("Q17", []string{"Q6256"}, "", "日本"),
		// no P131 at all
		"Q4": fakePlace("Q4", []string{"Q40434727"}, "", ""),
		// municipality beyond the hop limit
		"Q5":  fakePlace("Q5", []string{"Q40434727"}, "Q51", ""),
		"Q51": fakePlace("Q51", []string{"Q1"}, "Q52", ""),
		"Q52": fakePlace("Q52", []string{"Q1"}, "Q53", ""),
		"Q53": fakePlace("Q53", []string{"Q1"}, "Q54", ""),
		"Q54": fakePlace("Q54", []string{"Q494721"}, "", "遠い市"),
		// several P131 statements, prefecture first: the town is still found
		"Q6":  fakePlace("Q6", []string{"Q40434727"}, "Q99,Q60,Q61", ""),
		"Q60": fakePlace("Q60", []string{"Q1122846"}, "Q99", "柴田郡"),
		"Q61": fakePlace("Q61", []string{"Q1059478"}, "Q99,Q60", "川崎町 (宮城県)"),
		// first P131 target is unreadable (merged item missing from the
		// response): its sibling still resolves
		"Q7":  fakePlace("Q7", []string{"Q40434727"}, "Q70,Q10", ""),
		"Q70": `{"entities":{"Q71":{"claims":{},"sitelinks":{}}}}`,
	}
	calls := withPlaces(t, places)
	cases := map[string]string{"Q1": "古里町 (鹿児島市)", "Q2": "札幌市", "Q3": "", "Q4": "", "Q5": "", "Q6": "川崎町 (宮城県)", "Q7": "古里町 (鹿児島市)"}
	for qid, want := range cases {
		got, err := resolveMunicipalityTitle(context.Background(), qid)
		if err != nil {
			t.Fatalf("%s: unexpected error: %v", qid, err)
		}
		if got != want {
			t.Errorf("%s: got %q, want %q", qid, got, want)
		}
	}

	before := *calls
	if got, _ := resolveMunicipalityTitle(context.Background(), "Q2"); got != "札幌市" || *calls != before {
		t.Errorf("cached lookup: got %q with %d extra calls", got, *calls-before)
	}
}

func TestResolveMunicipalityTitle_ErrorNotCached(t *testing.T) {
	calls := withPlaces(t, map[string]string{})
	if _, err := resolveMunicipalityTitle(context.Background(), "Q404"); err == nil {
		t.Fatal("expected error for unknown entity")
	}
	before := *calls
	resolveMunicipalityTitle(context.Background(), "Q404")
	if *calls == before {
		t.Error("failed lookup was cached")
	}
}

func TestMatchSectionHeading_MunicipalityCandidates(t *testing.T) {
	headings := []wikipediaHeading{
		{Line: "観光", Level: 2},
		{Line: "名所･旧跡･観光スポット", Level: 3},
		{Line: "名物･特産品", Level: 3},
	}
	if got := matchSectionHeading(headings, municipalityTourismSpec.candidates); got == nil || got.Line != "名所･旧跡･観光スポット" {
		t.Errorf("tourism heading = %+v, want the specific subsection over the 観光 parent", got)
	}
	if got := matchSectionHeading(headings, municipalityFoodSpec.candidates); got == nil || got.Line != "名物･特産品" {
		t.Errorf("food heading = %+v", got)
	}
}

func TestMunicipalityFallback_Disabled(t *testing.T) {
	t.Setenv("ONSEN_MUNICIPALITY_FALLBACK_DISABLE", "1")
	calls := withPlaces(t, map[string]string{})
	food, tourism := municipalityFallback(context.Background(), "某温泉", "Q1", PanelSection{}, PanelSection{})
	if !sectionEmpty(food) || !sectionEmpty(tourism) || *calls != 0 {
		t.Errorf("disabled fallback touched the network (%d calls) or filled sections", *calls)
	}
}

// The fallback summarises only the matched section: joinSectionBlocks must
// carry every heading and body line of the section, untruncated and in order,
// so a 観光 section past the LLM input cap of a long municipality article is
// still what the model sees.
func TestJoinSectionBlocks(t *testing.T) {
	long := strings.Repeat("あ", maxSummaryInputRunes+10)
	got := joinSectionBlocks([]WikipediaTextBlock{
		{Heading: "観光スポット", Text: "城跡がある。"},
		{Heading: "", Text: long},
		{Heading: "温泉", Text: ""},
	})
	want := "観光スポット\n城跡がある。\n" + long + "\n温泉\n"
	if got != want {
		t.Errorf("joinSectionBlocks mismatch: len(got)=%d len(want)=%d", len([]rune(got)), len([]rune(want)))
	}
}

// A section that already carries structured items is never replaced, and a
// fallback that yields no items (no heading match, or LLM off in production)
// leaves the original section untouched instead of downgrading it.
func TestFillMunicipalitySection(t *testing.T) {
	t.Setenv("ONSEN_SUMMARY_DISABLE", "1")
	muni := "川崎町 (宮城県)"
	sourceURL := "https://ja.wikipedia.org/wiki/川崎町"

	withItems := PanelSection{Summary: "温泉側の要約。", Items: []SectionItem{{Label: "牛タン", Value: "有名店あり"}}}
	if got := fillMunicipalitySection(context.Background(), muni, "名物・特産品\n牛肉が有名。\n", []wikipediaHeading{{Line: "名物・特産品", Level: 3}}, sourceURL, sectionSpecs[1], withItems); len(got.Items) != 1 || got.SourceTitle != "" || got.Summary != "温泉側の要約。" {
		t.Errorf("fillMunicipalitySection replaced a section that already has items: %+v", got)
	}

	summaryOnly := PanelSection{Summary: "温泉側の要約。"}
	if got := fillMunicipalitySection(context.Background(), muni, "地理\n山が多い。\n", []wikipediaHeading{{Line: "地理", Level: 2}}, sourceURL, sectionSpecs[1], summaryOnly); !reflect.DeepEqual(got, summaryOnly) {
		t.Errorf("fillMunicipalitySection replaced a section with an empty one: %+v", got)
	}
}
