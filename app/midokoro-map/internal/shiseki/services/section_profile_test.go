package services

import (
	"path/filepath"
	"testing"
)

func useTempGeoSummaryCache(t *testing.T) *SummaryCache {
	t.Helper()
	cache := newSummaryCache(filepath.Join(t.TempDir(), "summaries.json"), 16)
	GeoProfile.cache() // run the lazy load first so cleanup restores a loaded cache
	orig := geoSummaryCache
	geoSummaryCache = cache
	t.Cleanup(func() { geoSummaryCache = orig })
	return cache
}

func TestGeoProfileUsesLandformHeadingsAndItsOwnCache(t *testing.T) {
	useTempSummaryCache(t, 16)
	geoCache := useTempGeoSummaryCache(t)
	fw := newFakeWikipedia(t,
		[]wikipediaHeading{{Line: "成因", Level: 2}, {Line: "特徴", Level: 2}, {Line: "アクセス", Level: 2}, {Line: "天然記念物", Level: 2}},
		"概要\n\n成因\n\n約1万年前の噴火で溶岩が流れた。\n\n特徴\n\n柱状節理が並ぶ。\n\nアクセス\n\nJR駅から徒歩15分。\n\n天然記念物\n\n1931年に国の天然記念物に指定。")
	withWikipediaBase(t, fw)
	withFakeOllama(t, newFakeOllama(t, `溶岩が冷えて柱状節理ができた。`))
	t.Setenv("SHISEKI_SUMMARY_DISABLE", "")

	origin, features, access, protection, transient, err := GeoProfile.FetchPanelSections(t.Context(), "テスト史跡")
	if err != nil || transient {
		t.Fatalf("FetchPanelSections: err=%v transient=%v", err, transient)
	}
	for name, section := range map[string]PanelSection{"成り立ち": origin, "特徴・見どころ": features, "アクセス": access, "指定・保護": protection} {
		if section.Summary == "" {
			t.Errorf("%s: expected a summary", name)
		}
	}
	if len(geoCache.byKey) == 0 {
		t.Error("geo summaries should be stored in the geo cache")
	}
	if len(summaryCache.byKey) != 0 {
		t.Errorf("geo summaries leaked into the shiseki cache: %d entries", len(summaryCache.byKey))
	}
}

func TestShisekiProfileKeepsShisekiHeadings(t *testing.T) {
	useTempSummaryCache(t, 16)
	useTempGeoSummaryCache(t)
	fw := newFakeWikipedia(t, []wikipediaHeading{{Line: "成因", Level: 2}}, "概要\n\n成因\n\n約1万年前の噴火。")
	withWikipediaBase(t, fw)
	t.Setenv("SHISEKI_SUMMARY_DISABLE", "1")

	history, _, _, _, _, err := FetchPanelSections(t.Context(), "テスト史跡")
	if err != nil {
		t.Fatal(err)
	}
	if len(history.Blocks) != 0 {
		t.Errorf("shiseki 歴史 must not match the geo-only heading 成因: %+v", history)
	}
	origin, _, _, _, _, err := GeoProfile.FetchPanelSections(t.Context(), "テスト史跡")
	if err != nil {
		t.Fatal(err)
	}
	if len(origin.Blocks) == 0 {
		t.Error("geo 成り立ち should match 成因")
	}
}
