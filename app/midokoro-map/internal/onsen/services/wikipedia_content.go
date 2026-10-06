package services

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"midokoro-map/internal/shared"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// errWikipediaArticleContentNotFound marks a permanent "the article does not
// resolve to usable content" condition (missing page, or an extract that
// came back empty) as opposed to a transient API-level failure. It is a
// parsed-response-level result, not an HTTP status, so it is never wrapped
// in apiStatusError; IsTransientWikimediaError checks for it explicitly so
// this case is not swept into isRetryableAPIError's "unclassified error,
// assume transient" default.
var errWikipediaArticleContentNotFound = errors.New("Wikipedia article content not found")

var wikipediaAPIBase = "https://ja.wikipedia.org"
var wikipediaClient = &http.Client{Timeout: 12 * time.Second}

type WikipediaContent struct {
	Description string
	SourceURL   string
	ImageURL    string
	Attribution CommonsAttribution
	ImageTitles []string
}

func FetchWikipediaContent(title, expectedQID string) (WikipediaContent, error) {
	// 30s leaves room for the transient-failure retry budget (backoff up to
	// ~7s across maxRetries) plus per-attempt response time. Wikipedia applies
	// rate limiting (429) under request bursts, so a short deadline previously
	// cut retries short and made the history/access section intermittently
	// disappear.
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	content, err := withRetry(ctx, "Wikipedia content", func() (WikipediaContent, error) {
		return fetchWikipediaContentOnce(ctx, title, expectedQID)
	})
	if err != nil {
		return WikipediaContent{}, err
	}
	if content.ImageURL == "" {
		for _, title := range usableArticleImageTitles(content.ImageTitles) {
			fileName := strings.TrimPrefix(strings.TrimPrefix(title, "ファイル:"), "File:")
			candidateURL := "https://upload.wikimedia.org/" + url.PathEscape(fileName)
			attribution, err := FetchCommonsAttribution(candidateURL)
			if err == nil && attribution.ImageURL != "" && attribution.License != "" {
				content.ImageURL = attribution.ImageURL
				content.Attribution = attribution
				break
			}
		}
	}
	return content, nil
}

func fetchWikipediaContentOnce(ctx context.Context, title, expectedQID string) (WikipediaContent, error) {
	params := url.Values{
		"action":        {"query"},
		"format":        {"json"},
		"formatversion": {"2"},
		"redirects":     {"1"},
		"prop":          {"extracts|pageimages|pageprops|images"},
		"exintro":       {"1"},
		"explaintext":   {"1"},
		"exchars":       {"700"},
		"piprop":        {"thumbnail"},
		"pithumbsize":   {"1200"},
		"pilicense":     {"free"},
		"imlimit":       {"20"},
		"titles":        {title},
	}
	body, err := doWikipediaAPI(ctx, params)
	if err != nil {
		return WikipediaContent{}, err
	}
	return parseWikipediaContent(body, expectedQID)
}

// doWikipediaAPI performs a single Japanese Wikipedia MediaWiki API request
// (query or parse action) and returns the decoded JSON body. A non-200 status
// is wrapped in the shared apiStatusError so withRetry can classify it for
// retrying; transient failures are backoff-handled by the caller.
func doWikipediaAPI(ctx context.Context, params url.Values) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, wikipediaAPIBase+"/w/api.php?"+params.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", wikimediaUserAgent)
	resp, err := wikipediaClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, &apiStatusError{status: resp.StatusCode, retryAfter: parseRetryAfter(resp.Header.Get("Retry-After"))}
	}
	return io.ReadAll(resp.Body)
}

const maxSectionChars = 2000

// WikipediaTextBlock is one readable unit under a section heading. Heading
// is empty for the section's own lead-in paragraph (before the first
// subsection heading); otherwise it is the subsection heading the paragraph
// belongs to. Consecutive paragraphs under the same heading are merged into
// one block.
type WikipediaTextBlock struct {
	Heading string `json:"heading"`
	Text    string `json:"text"`
}

// WikipediaSection holds an extracted article section's readable blocks and
// source URL.
type WikipediaSection struct {
	Blocks    []WikipediaTextBlock
	SourceURL string
}

// sectionSpec bundles what is needed to resolve one detail-panel section: the
// JSON key the LLM heading-resolution pass uses, the candidate headings (in
// display order), the per-section LLM instruction, and the human label used
// in the prompt and cache key.
type sectionSpec struct {
	key         string
	label       string
	candidates  []string
	instruction string
	// sectionSource feeds the LLM only the matched section's text instead of
	// the whole article. Municipality articles are long enough that the target
	// section often lies past the LLM input cap on the full text.
	sectionSource bool
}

var sectionSpecs = []sectionSpec{
	{
		key:         "history",
		label:       "歴史",
		candidates:  []string{"歴史", "沿革", "起源", "由来", "年表"},
		instruction: "開創・開発の経緯や時代の変遷を時系列に沿って構造化してください。itemsのlabelは時代区分(例:「明治」「大正」「平成」)や出来事名(例:「ダム反対運動」)にしてください。",
	},
	{
		key:         "food",
		label:       "名物",
		candidates:  []string{"名物", "名産", "名産品", "特産", "特産品", "料理", "美食", "名店"},
		instruction: "名物・名産品・特産品・名店など、地場の食べものや飲み物に焦点を当て構造化してください。itemsのlabelは品名(例:「牛タン」「饅頭」)にしてください。本文に具体的な品名・施設名が見える場合は必ず1件以上 items へ列挙し、要約だけにまとめないこと。",
	},
	{
		key:         "efficacy",
		label:       "効能",
		candidates:  []string{"効能", "温泉の効能", "薬効", "効用"},
		instruction: "入浴による効能・効果(美肌・疲労回復・冷え性・神経痛・切り傷など)を列挙し構造化してください。itemsのlabelは効能の種類(例:「美肌」「疲労回復」「神経痛」)にしてください。",
	},
	{
		key:         "access",
		label:       "アクセス",
		candidates:  []string{"アクセス", "交通", "交通アクセス", "交通機関"},
		instruction: "最寄り駅・路線・駅からの導線など、旅行者が使えるアクセス情報を構造化してください。itemsのlabelは交通手段の種類(例:「電車」「車」「バス」「徒歩」)にしてください。fromには出発点の固有名詞(駅名・IC名など)、toには到着点の固有名詞を入れてください(無い場合は空文字で可)。路線・所要時間・距離はvalueへ含めてください。",
	},
	{
		key:         "tourism",
		label:       "観光",
		candidates:  []string{"周辺", "周辺観光", "周辺観光スポット", "近隣", "近隣の観光", "温泉街", "名所・旧跡", "文化財"},
		instruction: "周辺・近隣の観光スポット・名所・施設に焦点を当て構造化してください。itemsのlabelは施設名・スポット名(例:「由布岳」「湯布院駅前」)にしてください。本文に具体的なスポット名・施設名が見える場合は必ず1件以上 items へ列挙し、要約だけにまとめないこと。",
	},
}

// PanelSection is the per-section payload the handler returns. Summary is a
// one-sentence lead when the LLM produced one. Items holds the structured
// labelled rows. Blocks is the raw fallback rendering. When Summary and Items
// are both empty the article has no matching content and the client shows its
// own placeholder. Status is an internal classification (not serialised) used
// by the warm-up tool to distinguish "done" from "please retry later".
type PanelSection struct {
	Summary   string               `json:"summary,omitempty"`
	Items     []SectionItem        `json:"items,omitempty"`
	Blocks    []WikipediaTextBlock `json:"blocks,omitempty"`
	SourceURL string               `json:"source_url,omitempty"`
	// SourceTitle names the municipality article when the section was filled
	// by municipalityFallback; empty for content from the onsen article.
	SourceTitle string `json:"source_title,omitempty"`
	Status      string `json:"-"`
}

// FetchPanelSections resolves the five detail-panel sections (歴史 / 名物 /
// 効能 / アクセス / 観光) for a Wikipedia article. Headings, plain text, and
// any LLM call failures are all non-fatal: the affected section simply comes
// back with its raw blocks (or empty), and the error is surfaced only when the
// article genuinely cannot be read (missing page, non-transient API failure).
//
// When the onsen article has no 名物 or 観光 content and a Wikidata QID is
// available, the empty sections are re-resolved against the municipality
// article (spring item P131 chain -> jawiki sitelink) that the onsen belongs to. Any
// fallback failure is non-fatal: the affected section simply stays empty.
//
// transient is set when the heading or plain-text fetch failed for a reason
// worth retrying (rate limit, 5xx, network), so the client does not cache an
// empty panel as "the article has no such sections".
func FetchPanelSections(ctx context.Context, title, qid string) (history, food, efficacy, access, tourism PanelSection, transient bool, err error) {
	if SummaryDisabled() {
		var readErr error
		history, food, efficacy, access, tourism, readErr = resolveSectionsNoSummary(title)
		// An unreadable onsen article says nothing about whether it has 名物 or
		// 観光, so do not paper over the failure with another article's content.
		if qid != "" && readErr == nil {
			food, tourism = municipalityFallback(ctx, title, qid, food, tourism)
		}
		return history, food, efficacy, access, tourism, false, nil
	}

	fullText, _, fetchErr := fetchWikipediaPlainText(ctx, title)
	if fetchErr != nil {
		return PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, true, fetchErr
	}
	headings, headingErr := fetchWikipediaSectionHeadings(ctx, title)
	if headingErr != nil {
		return PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, true, headingErr
	}
	sourceURL := wikipediaArticleURL(title)
	headingMap := resolveSectionHeadings(ctx, title, headings)
	history = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[0], headingMap)
	food = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[1], headingMap)
	efficacy = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[2], headingMap)
	access = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[3], headingMap)
	tourism = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[4], headingMap)
	if qid != "" {
		food, tourism = municipalityFallback(ctx, title, qid, food, tourism)
	}
	return history, food, efficacy, access, tourism, false, nil
}

// municipalityFoodSpec and municipalityTourismSpec reuse the 名物 / 観光
// prompts but match the heading vocabulary of municipality articles, where the
// content lives under e.g. 名産・特産 or 名所・旧跡・観光スポット. The bare 観光
// is last because it is often a parent heading spanning unrelated subsections.
var (
	municipalityFoodSpec = withCandidates(sectionSpecs[1], []string{
		"名産・特産", "名物・特産品", "名産品・特産品", "特産・名産", "特産品", "名産品",
		"名産", "特産", "名物", "郷土料理", "グルメ・特産品", "郷土料理・ご当地グルメ", "文化・名物",
	})
	municipalityTourismSpec = withCandidates(sectionSpecs[4], []string{
		"観光スポット", "名所・旧跡・観光スポット", "名所・旧跡", "名所・旧跡・観光地", "観光地",
		"名所・旧跡・観光スポット・祭事・催事", "観光地・祭事・催事", "観光",
	})
)

func withCandidates(spec sectionSpec, candidates []string) sectionSpec {
	spec.candidates = candidates
	spec.sectionSource = true
	return spec
}

// municipalityFallback re-resolves the 名物 (food) and/or 観光 (tourism)
// section against the Wikipedia article of the municipality the onsen lies in
// when the onsen article did not yield structured items for it. A section is
// replaced only when the municipality article actually produced items, so a
// summary-only result from the onsen article survives (it is still rendered
// as the lead sentence). The source URL points at the municipality article,
// and headings are matched exactly (no LLM heading resolution) so the
// fallback stays deterministic. Any failure is non-fatal: the section simply
// keeps its original content. ONSEN_MUNICIPALITY_FALLBACK_DISABLE turns the
// fallback off.
func municipalityFallback(ctx context.Context, title, qid string, food, tourism PanelSection) (PanelSection, PanelSection) {
	if MunicipalityFallbackDisabled() || (len(food.Items) > 0 && len(tourism.Items) > 0) {
		return food, tourism
	}
	muniTitle, err := resolveMunicipalityTitle(ctx, qid)
	if err != nil || muniTitle == "" || muniTitle == title {
		return food, tourism
	}
	fullText, _, err := fetchWikipediaPlainText(ctx, muniTitle)
	if err != nil {
		return food, tourism
	}
	headings, err := fetchWikipediaSectionHeadings(ctx, muniTitle)
	if err != nil {
		return food, tourism
	}
	sourceURL := wikipediaArticleURL(muniTitle)
	food = fillMunicipalitySection(ctx, muniTitle, fullText, headings, sourceURL, municipalityFoodSpec, food)
	tourism = fillMunicipalitySection(ctx, muniTitle, fullText, headings, sourceURL, municipalityTourismSpec, tourism)
	return food, tourism
}

// fillMunicipalitySection re-resolves one missing section against the
// municipality article and returns the fallback result only when it actually
// produced structured items, so a summary-only section from the onsen article
// is never downgraded to raw blocks.
func fillMunicipalitySection(ctx context.Context, muniTitle, fullText string, headings []wikipediaHeading, sourceURL string, spec sectionSpec, section PanelSection) PanelSection {
	if len(section.Items) > 0 {
		return section
	}
	filled := resolvePanelSection(ctx, muniTitle, fullText, headings, sourceURL, spec, nil)
	if len(filled.Items) == 0 {
		return section
	}
	filled.SourceTitle = muniTitle
	return filled
}

// sectionEmpty reports whether a panel section carries no renderable content
// at all (no summary, no structured items, no raw blocks).
func sectionEmpty(section PanelSection) bool {
	return section.Summary == "" && len(section.Items) == 0 && len(section.Blocks) == 0
}

// resolveSectionsNoSummary is the ONSEN_SUMMARY_DISABLE path: same five
// sections, but the LLM is never called (neither the heading-resolution fall-
// back nor the per-section summary) but shipped heading maps and section summaries remain available.
// A cache miss uses the exact-match candidate pass without generating new text.
func resolveSectionsNoSummary(title string) (history, food, efficacy, access, tourism PanelSection, err error) {
	ctx := context.Background()
	fullText, _, err := fetchWikipediaPlainText(ctx, title)
	if err != nil {
		return PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, err
	}
	headings, err := fetchWikipediaSectionHeadings(ctx, title)
	if err != nil {
		return PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, PanelSection{}, err
	}
	sourceURL := wikipediaArticleURL(title)
	headingMap := resolveSectionHeadings(ctx, title, headings)
	history = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[0], headingMap)
	food = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[1], headingMap)
	efficacy = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[2], headingMap)
	access = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[3], headingMap)
	tourism = resolvePanelSection(ctx, title, fullText, headings, sourceURL, sectionSpecs[4], headingMap)
	return history, food, efficacy, access, tourism, nil
}

// resolveSectionHeadings returns a per-section-key -> article-heading mapping,
// preferring the LLM fall-back over the exact-match candidate pass. The LLM
// call is the expensive part, so we cache its verdict per
// (article, heading-snapshot) pair; the exact-match pass is free and always
// runs first, so articles whose headings line up with the candidate list never
// pay the LLM cost. If the LLM is unreachable (Ollama down, disabled, etc.)
// the returned map is empty and callers fall through to their exact-match
// target.
func resolveSectionHeadings(ctx context.Context, title string, headings []wikipediaHeading) map[string]string {
	// Fast pass: every section already matches an exact candidate => no LLM.
	resolved := make(map[string]string, len(sectionSpecs))
	anyMissing := false
	for _, spec := range sectionSpecs {
		if hit := matchSectionHeading(headings, spec.candidates); hit != nil {
			resolved[spec.key] = hit.Line
		} else {
			anyMissing = true
		}
	}
	if !anyMissing || len(headings) == 0 {
		return resolved
	}

	headingLines := make([]string, 0, len(headings))
	for _, h := range headings {
		headingLines = append(headingLines, h.Line)
	}
	key := headingMapCacheKey(title, headingLines)
	if cached, ok := lookupSummary(key); ok {
		var m map[string]string
		if err := json.Unmarshal([]byte(cached), &m); err != nil {
			return resolved
		}
		for k, v := range m {
			if v != "" {
				resolved[k] = v
			}
		}
		return resolved
	}

	if SummaryDisabled() {
		return resolved
	}

	headingSet := make(map[string]bool, len(headings))
	for _, h := range headings {
		headingSet[h.Line] = true
	}
	llm, err := resolveSectionsForHeadings(ctx, title, sectionSpecs, headingLines)
	if err == nil {
		// The model is instructed to return one of the article headings verbatim;
		// guard against it fabricating a string that does not exist in the list
		// (which would break extractSectionBlocks).
		for k, v := range llm {
			if v != "" && headingSet[v] {
				resolved[k] = v
			}
		}
		// Cache only a complete LLM verdict. A failed resolution stores
		// nothing so the next request retries the LLM instead of being
		// pinned to the exact-match-only result indefinitely.
		if b, err := json.Marshal(resolved); err == nil {
			saveSummary(key, string(b))
		}
	}
	return resolved
}

// resolvePanelSection is the single per-section pipeline shared by the summary
// and no-summary paths:
//
//  1. Resolve the target heading. Two-stage: the exact-match candidate pass
//     first, then the LLM heading-resolution verdict (headingMap) if the
//     exact pass did not match. If neither resolves a heading, return empty.
//  2. Extract + truncate the raw blocks (always available for fallback).
//  3. Look up the section-content cache. A hit returns immediately (a cached
//     SummaryNone verdict means "article has no relevant text", so blocks are
//     still returned as the reading fallback). The cache is consulted even
//     when ONSEN_SUMMARY_DISABLE is set, so a pre-warmed deployment (Cloud Run)
//     can serve the structured content without an LLM call.
//  4. When ONSEN_SUMMARY_DISABLE is set, skip the LLM step entirely and return
//     blocks only on a cache miss.
//  5. Otherwise ask the LLM for a fresh structured answer. On success
//     (including a SummaryNone verdict) record it in the cache; on failure fall
//     back to blocks only.
//
// sectionStatus values for PanelSection.Status (internal, not serialised).
const (
	sectionStatusWarmed = "warmed" // cache hit, LLM done, or legitimately empty
	sectionStatusRetry  = "retry"  // LLM call failed (transient); warm-up should retry
)

func resolvePanelSection(ctx context.Context, title, fullText string, headings []wikipediaHeading, sourceURL string, spec sectionSpec, headingMap map[string]string) PanelSection {
	target := matchSectionHeading(headings, spec.candidates)
	if target == nil && headingMap != nil {
		if line, ok := headingMap[spec.key]; ok && line != "" {
			for i := range headings {
				if headings[i].Line == line {
					target = &headings[i]
					break
				}
			}
		}
	}
	if target == nil {
		return PanelSection{Status: sectionStatusWarmed}
	}
	sectionBlocks := extractSectionBlocks(fullText, *target, headings)
	blocks := truncateSectionBlocks(sectionBlocks)
	if len(blocks) == 0 {
		return PanelSection{SourceURL: sourceURL, Status: sectionStatusWarmed}
	}

	// Every section now uses the same structured {summary, items} shape; a
	// single versioned label keeps the cache key stable across sections.
	key := summaryCacheKey(title, spec.label+" v3")
	if cached, ok := lookupSummary(key); ok {
		decoded := decodeSectionContent(cached)
		if decoded.Summary == SummaryNone && len(decoded.Items) == 0 {
			// A cached "no relevant text" verdict: raw blocks only.
			return PanelSection{Blocks: blocks, SourceURL: sourceURL, Status: sectionStatusWarmed}
		}
		return PanelSection{Summary: decoded.Summary, Items: decoded.Items, Blocks: blocks, SourceURL: sourceURL, Status: sectionStatusWarmed}
	}

	if SummaryDisabled() {
		// Production: no LLM at runtime; a fresh request without a warmed cache
		// has nothing to show beyond the raw blocks.
		return PanelSection{Blocks: blocks, SourceURL: sourceURL, Status: sectionStatusRetry}
	}

	source := fullText
	if spec.sectionSource {
		source = joinSectionBlocks(sectionBlocks)
	}
	answer, err := generateSectionContent(ctx, spec.label, spec.instruction, source)
	if err != nil {
		// LLM unavailable or errored: fall back to the raw blocks; the warm-up
		// loop will retry this section next pass.
		return PanelSection{Blocks: blocks, SourceURL: sourceURL, Status: sectionStatusRetry}
	}
	saveSummary(key, encodeSectionContent(answer))
	if answer.Summary == SummaryNone && len(answer.Items) == 0 {
		return PanelSection{Blocks: blocks, SourceURL: sourceURL, Status: sectionStatusWarmed}
	}
	return PanelSection{Summary: answer.Summary, Items: answer.Items, Blocks: blocks, SourceURL: sourceURL, Status: sectionStatusWarmed}
}

// joinSectionBlocks renders untruncated section blocks back into plain text
// (heading line, then paragraph) for use as LLM source text.
func joinSectionBlocks(blocks []WikipediaTextBlock) string {
	var b strings.Builder
	for _, block := range blocks {
		if block.Heading != "" {
			b.WriteString(block.Heading + "\n")
		}
		if block.Text != "" {
			b.WriteString(block.Text + "\n")
		}
	}
	return b.String()
}

// decodeSectionContent parses a stored section value. It round-trips the
// current {summary, items} shape and tolerates the legacy plain-summary string
// (pre-structured) and the legacy {summary, routes} access shape so a cache
// file written before either rewrite still renders instead of erroring.
func decodeSectionContent(cached string) SectionContent {
	trimmed := strings.TrimSpace(cached)
	if trimmed == SummaryNone {
		return SectionContent{Summary: SummaryNone, Items: []SectionItem{}}
	}
	if strings.HasPrefix(trimmed, "{") {
		var decoded SectionContent
		if err := json.Unmarshal([]byte(trimmed), &decoded); err == nil {
			decoded = sanitizeSectionContent(decoded)
			for i := range decoded.Items {
				decoded.Items[i].Label = strings.TrimSpace(decoded.Items[i].Label)
				decoded.Items[i].Value = strings.TrimSpace(decoded.Items[i].Value)
				decoded.Items[i].From = strings.TrimSpace(decoded.Items[i].From)
				decoded.Items[i].To = strings.TrimSpace(decoded.Items[i].To)
			}
			decoded.Summary = strings.TrimSpace(decoded.Summary)
			return decoded
		}
		// Legacy access JSON: {"summary": "...", "routes":[{mode,from,to,detail}]}
		var legacy struct {
			Summary string `json:"summary"`
			Routes  []struct {
				Mode   string `json:"mode"`
				From   string `json:"from"`
				To     string `json:"to"`
				Detail string `json:"detail"`
			} `json:"routes"`
		}
		if err := json.Unmarshal([]byte(trimmed), &legacy); err == nil {
			items := make([]SectionItem, 0, len(legacy.Routes))
			for _, r := range legacy.Routes {
				items = append(items, SectionItem{
					Label: strings.TrimSpace(r.Mode),
					Value: strings.TrimSpace(r.Detail),
					From:  strings.TrimSpace(r.From),
					To:    strings.TrimSpace(r.To),
				})
			}
			return SectionContent{Summary: strings.TrimSpace(legacy.Summary), Items: items}
		}
	}
	// Not JSON-shaped: legacy plain summary.
	return SectionContent{Summary: cached, Items: []SectionItem{}}
}

// encodeSectionContent serializes a structured section answer into a single
// string for the flat summary cache. A summary-only answer is stored as a JSON
// object with an empty items array so decodeSectionContent can round-trip it
// without confusing it with the legacy plain-string shape.
func encodeSectionContent(content SectionContent) string {
	if content.Summary == "" && len(content.Items) == 0 {
		return SummaryNone
	}
	b, err := json.Marshal(content)
	if err != nil {
		if content.Summary == "" {
			return SummaryNone
		}
		return content.Summary
	}
	return string(b)
}

// wikipediaHeading pairs a section's heading text with its nesting level
// (the MediaWiki API's "level" field, e.g. "2" for a top-level heading, "3"
// for its subsections). The level is needed so extractSectionBlocks can stop
// only at a sibling-or-shallower heading instead of at any heading,
// including the target's own subsections.
type wikipediaHeading struct {
	Line  string
	Level int
}

func matchSectionHeading(headings []wikipediaHeading, candidates []string) *wikipediaHeading {
	for _, candidate := range candidates {
		for i, heading := range headings {
			if normalizeHeading(heading.Line) == candidate {
				return &headings[i]
			}
		}
	}
	return nil
}

// normalizeHeading folds the halfwidth middle dot (･) some articles use into
// the fullwidth ・ the candidate lists are written with.
func normalizeHeading(line string) string {
	return strings.ReplaceAll(line, "･", "・")
}

func fetchWikipediaSectionHeadings(ctx context.Context, title string, requireValid ...bool) ([]wikipediaHeading, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	params := url.Values{
		"action":        {"parse"},
		"format":        {"json"},
		"formatversion": {"2"},
		"redirects":     {"1"},
		"prop":          {"sections"},
		"page":          {title},
	}
	body, err := withRetry(ctx, "Wikipedia section headings", func() ([]byte, error) {
		return doWikipediaAPI(ctx, params)
	})
	if err != nil {
		return nil, err
	}
	if len(requireValid) > 0 && requireValid[0] {
		if err := shared.ValidateWikiEnvelope(body, "parse", "sections"); err != nil {
			return nil, err
		}
	}
	var data struct {
		Parse struct {
			Sections []struct {
				Line  string `json:"line"`
				Level string `json:"level"`
			} `json:"sections"`
		} `json:"parse"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, err
	}
	headings := make([]wikipediaHeading, 0, len(data.Parse.Sections))
	for _, section := range data.Parse.Sections {
		level, err := strconv.Atoi(section.Level)
		if err != nil {
			level = 0
		}
		headings = append(headings, wikipediaHeading{Line: strings.TrimSpace(section.Line), Level: level})
	}
	return headings, nil
}

func fetchWikipediaPlainText(ctx context.Context, title string, requireValid ...bool) (text string, resolvedTitle string, err error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	params := url.Values{
		"action":          {"query"},
		"format":          {"json"},
		"formatversion":   {"2"},
		"redirects":       {"1"},
		"prop":            {"extracts"},
		"explaintext":     {"1"},
		"exsectionformat": {"plain"},
		"titles":          {title},
	}
	body, err := withRetry(ctx, "Wikipedia plain text", func() ([]byte, error) {
		return doWikipediaAPI(ctx, params)
	})
	if err != nil {
		return "", "", err
	}
	if len(requireValid) > 0 && requireValid[0] {
		if err := shared.ValidateWikiEnvelope(body, "query", "pages"); err != nil {
			return "", "", err
		}
	}
	var data struct {
		Query struct {
			Pages []struct {
				Missing bool   `json:"missing"`
				Title   string `json:"title"`
				Extract string `json:"extract"`
			} `json:"pages"`
		} `json:"query"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return "", "", err
	}
	for _, page := range data.Query.Pages {
		if page.Missing || strings.TrimSpace(page.Extract) == "" {
			continue
		}
		return page.Extract, page.Title, nil
	}
	return "", "", errWikipediaArticleContentNotFound
}

// extractSectionBlocks returns the target section's content as readable
// blocks, classifying each non-empty line as a subsection heading or body
// paragraph using the known heading levels. Consecutive paragraphs under the
// same heading are merged into one block (heading first, then the merged
// text); paragraphs before the first subsection heading carry an empty
// heading. A heading that has no paragraph under it is dropped. The walk
// stops only at the next heading of the same or shallower level (a sibling
// or ancestor), not at every heading, so subsections nested under the target
// are still collected.
func extractSectionBlocks(fullText string, target wikipediaHeading, allHeadings []wikipediaHeading) []WikipediaTextBlock {
	headingLevels := make(map[string]int, len(allHeadings))
	for _, heading := range allHeadings {
		if _, exists := headingLevels[heading.Line]; !exists {
			headingLevels[heading.Line] = heading.Level
		}
	}
	lines := strings.Split(fullText, "\n")
	startIdx := -1
	for i, line := range lines {
		if strings.TrimSpace(line) == target.Line {
			startIdx = i
			break
		}
	}
	if startIdx == -1 {
		return nil
	}

	currentHeading := ""
	var paragraphs []string
	var blocks []WikipediaTextBlock
	flush := func(heading string) {
		text := strings.TrimSpace(strings.Join(paragraphs, "\n\n"))
		if text != "" {
			blocks = append(blocks, WikipediaTextBlock{Heading: heading, Text: text})
		}
		paragraphs = nil
	}

	for i := startIdx + 1; i < len(lines); i++ {
		trimmed := strings.TrimSpace(lines[i])
		if trimmed == "" {
			continue
		}
		level, isHeading := headingLevels[trimmed]
		if isHeading && level <= target.Level {
			break
		}
		if isHeading {
			flush(currentHeading)
			currentHeading = trimmed
			continue
		}
		paragraphs = append(paragraphs, trimmed)
	}
	flush(currentHeading)
	return blocks
}

func wikipediaArticleURL(title string) string {
	return "https://ja.wikipedia.org/wiki/" + url.PathEscape(strings.ReplaceAll(title, " ", "_"))
}

// truncateSectionBlocks bounds the total rune count across all blocks to
// maxSectionChars, keeping each block's heading intact and appending "…" to
// whichever block the budget runs out in (or dropping its trailing blocks if
// the budget is exhausted exactly on a boundary). If the first block alone
// exceeds the budget, it is cut mid-paragraph with the heading preserved.
func truncateSectionBlocks(blocks []WikipediaTextBlock) []WikipediaTextBlock {
	if len(blocks) == 0 {
		return blocks
	}
	total := 0
	for _, b := range blocks {
		total += len(b.Heading) + len(b.Text)
	}
	if total <= maxSectionChars {
		return blocks
	}

	budget := maxSectionChars
	out := make([]WikipediaTextBlock, 0, len(blocks))
	for _, b := range blocks {
		if budget <= 0 {
			break
		}
		headingRunes := []rune(b.Heading)
		textRunes := []rune(b.Text)
		// Reserve room for the heading (and the ellipsis we may need).
		headCost := len(headingRunes)
		if headCost > budget {
			// Even the heading doesn't fit; keep as much of it as we can.
			out = append(out, WikipediaTextBlock{Heading: string(headingRunes[:budget]), Text: ""})
			budget = 0
			break
		}
		remaining := budget - headCost
		if remaining <= 0 {
			out = append(out, WikipediaTextBlock{Heading: b.Heading, Text: ""})
			budget = 0
			break
		}
		if len(textRunes) <= remaining {
			out = append(out, b)
			budget -= headCost + len(textRunes)
		} else {
			// budget >= 1 guarantees room; reserve one rune for "…".
			keep := remaining - 1
			if keep < 0 {
				keep = 0
			}
			out = append(out, WikipediaTextBlock{Heading: b.Heading, Text: string(textRunes[:keep]) + "…"})
			budget = 0
			break
		}
	}
	return out
}

func usableArticleImageTitles(titles []string) []string {
	result := make([]string, 0, len(titles))
	for _, title := range titles {
		lower := strings.ToLower(title)
		if strings.Contains(lower, "logo") || strings.Contains(lower, "icon") || strings.Contains(lower, "wiki letter") || strings.Contains(lower, "camera-photo") || strings.HasSuffix(lower, ".svg") {
			continue
		}
		result = append(result, title)
	}
	return result
}

func parseWikipediaContent(body []byte, expectedQID string) (WikipediaContent, error) {
	var data struct {
		Query struct {
			Pages []struct {
				Missing   bool   `json:"missing"`
				Title     string `json:"title"`
				Extract   string `json:"extract"`
				Thumbnail struct {
					Source string `json:"source"`
				} `json:"thumbnail"`
				PageProps struct {
					WikibaseItem string `json:"wikibase_item"`
				} `json:"pageprops"`
				Images []struct {
					Title string `json:"title"`
				} `json:"images"`
			} `json:"pages"`
		} `json:"query"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return WikipediaContent{}, err
	}
	for _, page := range data.Query.Pages {
		if page.Missing || strings.TrimSpace(page.Extract) == "" || expectedQID == "" || page.PageProps.WikibaseItem != expectedQID {
			continue
		}
		content := WikipediaContent{
			Description: strings.TrimSpace(page.Extract),
			SourceURL:   wikipediaArticleURL(page.Title),
			ImageURL:    page.Thumbnail.Source,
		}
		for _, image := range page.Images {
			content.ImageTitles = append(content.ImageTitles, image.Title)
		}
		if content.ImageURL != "" {
			if attribution, err := FetchCommonsAttribution(content.ImageURL); err == nil {
				content.Attribution = attribution
			} else {
				content.ImageURL = ""
			}
		}
		return content, nil
	}
	return WikipediaContent{}, errWikipediaArticleContentNotFound
}
