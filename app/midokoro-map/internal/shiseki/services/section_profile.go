package services

import (
	"sync"

	"midokoro-map/internal/shared"
)

// SectionProfile chooses the four detail-panel section specs and the summary
// cache they read and write. The shiseki tab uses ShisekiProfile. The geo
// tab's natural monuments use GeoProfile: the same four response slots
// (history / remains / access / highlights) with landform-oriented headings
// and instructions, cached separately in data/geo/summaries.json so their
// summaries and heading maps never mix with shiseki entries for the same article.
type SectionProfile struct {
	specs []sectionSpec
	cache func() *SummaryCache
	// headingKeyPrefix versions the cached LLM heading maps; change it when the
	// specs' keys or candidates change so stale slot assignments are not reused.
	headingKeyPrefix string
	// summaryOnly drops raw Wikipedia blocks from responses.
	summaryOnly bool
}

// The shiseki cache is read through the package variable so tests that swap
// summaryCache keep working.
var ShisekiProfile = &SectionProfile{specs: sectionSpecs, cache: func() *SummaryCache { return summaryCache }}

// Loaded on first use so binaries that never serve geo skip the file read.
var (
	geoSummaryCache     *SummaryCache
	geoSummaryCacheOnce sync.Once
)

// Natural monuments are all national designations, so like national shiseki
// entries the panel shows summaries only.
var GeoProfile = &SectionProfile{specs: geoSectionSpecs, headingKeyPrefix: "geo-v1|", summaryOnly: true, cache: func() *SummaryCache {
	geoSummaryCacheOnce.Do(func() {
		if geoSummaryCache == nil {
			geoSummaryCache = newSummaryCache(shared.DataPath("geo", "summaries.json"), 20000)
		}
	})
	return geoSummaryCache
}}

// Specs fill the shiseki response slots by position: history=成り立ち,
// remains=特徴・見どころ, access=アクセス, highlights=指定・保護. The keys differ
// from shiseki's because the heading-resolution prompt shows them to the model.
var geoSectionSpecs = []sectionSpec{
	{
		key:         "origin",
		label:       "成り立ち",
		candidates:  []string{"成因", "成り立ち", "形成", "地質"},
		instruction: "地形や岩石・地質がどのように形成されたかを、分かる範囲で年代を添えて簡潔に要約してください。",
	},
	{
		key:         "features",
		label:       "特徴・見どころ",
		candidates:  []string{"概要", "特徴", "見どころ", "景観", "地形", "現況", "構造"},
		instruction: "地形・岩石・景観などの特徴と、見学時の見どころを簡潔に要約してください。",
	},
	{
		key:         "access",
		label:       "アクセス",
		candidates:  []string{"アクセス", "交通", "交通アクセス", "交通機関"},
		instruction: "最寄り駅・路線・駐車場・駅からの導線など、旅行者が使えるアクセス情報を簡潔に要約してください。",
	},
	{
		key:         "protection",
		label:       "指定・保護",
		candidates:  []string{"天然記念物", "文化財", "指定", "保護", "保全"},
		instruction: "天然記念物などの指定や、保護・保全の取り組みを簡潔に要約してください。",
	},
}

// SummaryOnly reports whether responses should omit raw Wikipedia blocks.
func (p *SectionProfile) SummaryOnly() bool { return p.summaryOnly }

func (p *SectionProfile) lookup(key string) (string, bool) { return p.cache().Get(key) }

func (p *SectionProfile) save(key, summary string) {
	cache := p.cache()
	cache.Put(key, summary)
	cache.flush()
}
