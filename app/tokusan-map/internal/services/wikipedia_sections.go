package services

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// errWikipediaArticleContentNotFound marks a permanent "the article does not
// resolve to usable content" condition (missing page, or an empty extract),
// as opposed to a transient API-level failure.
var errWikipediaArticleContentNotFound = errors.New("Wikipedia article content not found")

var wikipediaAPIBase = "https://ja.wikipedia.org"
var wikipediaClient = &http.Client{Timeout: 12 * time.Second}

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

// sectionSpec bundles what is needed to resolve one detail-panel section: the
// JSON key, the candidate headings (in priority order), the per-section LLM
// instruction, and the label used in the prompt and cache key. A spec with no
// candidates reads the article lead (the text before the first heading).
type sectionSpec struct {
	key         string
	label       string
	candidates  []string
	instruction string
}

const noneRule = "記事本文にこの内容の記述が無い場合は、推測で補わず、summaryに「なし」、itemsに空配列を入れてください。"

var sectionSpecs = []sectionSpec{
	{
		key:         "about",
		label:       "概要",
		instruction: "この特産物が何か(種類・原料・形状・味や用途などの特徴)を構造化してください。summaryは1文でこの特産物を説明してください。itemsのlabelは特徴の種類(例:「原料」「味」「用途」)にしてください。歴史や製法の詳細は含めません。" + noneRule,
	},
	{
		key:         "history",
		label:       "歴史",
		candidates:  []string{"歴史", "沿革", "起源", "由来", "概史"},
		instruction: "起源と変遷を時系列に沿って構造化してください。itemsのlabelは時代区分(例:「江戸時代」「明治」「1990年代」)や出来事名にしてください。" + noneRule,
	},
	{
		key:         "production",
		label:       "産地・製法",
		candidates:  []string{"製法", "製造方法", "製造法", "製造工程", "生産", "産地", "原料", "栽培", "特徴"},
		instruction: "産地の条件(気候・水・土壌など)、原料、作り方・栽培方法を構造化してください。itemsのlabelは項目名(例:「原料」「産地」「工程」)にしてください。" + noneRule,
	},
	{
		key:         "visit",
		label:       "購入・観光",
		candidates:  []string{"販売", "観光", "施設", "関連施設", "祭り", "イベント", "店舗"},
		instruction: "旅行者がこの特産物を買える場所・味わえる店・見学できる施設・関連する祭りや行事に限って構造化してください。itemsのlabelは施設名・行事名にしてください。特産物そのものの説明、歴史、製法、生産量は含めません。" + noneRule,
	},
}

// PanelSection is the per-section payload the handler returns. Summary is a
// one-sentence lead when the LLM produced one. Items holds the structured
// labelled rows. Blocks is the raw article text used as the reading fallback.
// Status is an internal classification (not serialised) used by the warm-up
// tool to distinguish "done" from "please retry later".
type PanelSection struct {
	Summary   string               `json:"summary,omitempty"`
	Items     []SectionItem        `json:"items,omitempty"`
	Blocks    []WikipediaTextBlock `json:"blocks,omitempty"`
	SourceURL string               `json:"source_url,omitempty"`
	Status    string               `json:"-"`
}

// sectionStatus values for PanelSection.Status (internal, not serialised).
const (
	sectionStatusWarmed = "warmed" // cache hit, LLM done, or legitimately empty
	sectionStatusRetry  = "retry"  // LLM unavailable; warm-up should retry
)

// SectionRetry reports whether the warm-up tool should retry this section.
func (s PanelSection) SectionRetry() bool { return s.Status == sectionStatusRetry }

// FetchPanelSections resolves the detail-panel sections (sectionSpecs order,
// keyed by spec.key) for a Wikipedia article. LLM failures are non-fatal: the
// affected section falls back to its raw blocks, or stays empty. err is set
// only when the article itself cannot be read; transient marks that failure as
// worth retrying (rate limit, 5xx, network).
func FetchPanelSections(ctx context.Context, title string) (sections map[string]PanelSection, transient bool, err error) {
	headings, err := fetchWikipediaSectionHeadings(ctx, title)
	if err != nil {
		return nil, isTransientWikipediaError(err), err
	}
	fullText, resolvedTitle, err := fetchWikipediaPlainText(ctx, title)
	if err != nil {
		return nil, isTransientWikipediaError(err), err
	}
	// Cache keys use the requested title so a warm run and the server agree
	// even when the article redirects.
	sourceURL := wikipediaArticleURL(resolvedTitle)
	headingMap := resolveSectionHeadings(ctx, title, headings)
	sections = make(map[string]PanelSection, len(sectionSpecs))
	for _, spec := range sectionSpecs {
		sections[spec.key] = resolvePanelSection(ctx, title, fullText, headings, sourceURL, spec, headingMap)
	}
	return sections, false, nil
}

func isTransientWikipediaError(err error) bool {
	return !errors.Is(err, errWikipediaArticleContentNotFound) && isRetryableAPIError(err)
}

// headingSpecs returns the specs that map to an article heading (the lead
// section has none).
func headingSpecs() []sectionSpec {
	specs := make([]sectionSpec, 0, len(sectionSpecs))
	for _, spec := range sectionSpecs {
		if len(spec.candidates) > 0 {
			specs = append(specs, spec)
		}
	}
	return specs
}

// resolveSectionHeadings maps each heading-backed section to an article
// heading: exact candidates first, then a cached LLM verdict for the rest.
func resolveSectionHeadings(ctx context.Context, title string, headings []wikipediaHeading) map[string]string {
	specs := headingSpecs()
	resolved := make(map[string]string, len(specs))
	anyMissing := false
	for _, spec := range specs {
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
	llm, err := resolveSectionsForHeadings(ctx, title, specs, headingLines)
	if err == nil {
		// Guard against the model fabricating a heading that is not in the
		// article, which would break extractSectionBlocks.
		for k, v := range llm {
			if v != "" && headingSet[v] {
				resolved[k] = v
			}
		}
		// Cache only a complete LLM verdict so a failed call is retried.
		if b, err := json.Marshal(resolved); err == nil {
			saveSummary(key, string(b))
		}
	}
	return resolved
}

// sectionBlocks returns the raw article text for a section: the lead for a
// spec without candidates, otherwise the resolved heading's body.
func sectionBlocks(fullText string, headings []wikipediaHeading, spec sectionSpec, headingMap map[string]string) []WikipediaTextBlock {
	if len(spec.candidates) == 0 {
		return truncateSectionBlocks(extractLeadBlocks(fullText, headings))
	}
	target := matchSectionHeading(headings, spec.candidates)
	if target == nil {
		if line := headingMap[spec.key]; line != "" {
			for i := range headings {
				if headings[i].Line == line {
					target = &headings[i]
					break
				}
			}
		}
	}
	if target == nil {
		return nil
	}
	return truncateSectionBlocks(extractSectionBlocks(fullText, *target, headings))
}

// resolvePanelSection builds one section. Specialty-product articles are short
// and often mention production or sales outside a dedicated heading, so the LLM
// reads the whole article even when no heading matched; the raw blocks are only
// the reading fallback. A cached answer is served even when
// TOKUSAN_SUMMARY_DISABLE is set, so a pre-warmed deployment needs no LLM.
func resolvePanelSection(ctx context.Context, title, fullText string, headings []wikipediaHeading, sourceURL string, spec sectionSpec, headingMap map[string]string) PanelSection {
	blocks := sectionBlocks(fullText, headings, spec, headingMap)
	withContent := func(content SectionContent, status string) PanelSection {
		if content.Summary == SummaryNone && len(content.Items) == 0 {
			content = SectionContent{}
		}
		section := PanelSection{Summary: content.Summary, Items: content.Items, Blocks: blocks, Status: status}
		if section.Summary != "" || len(section.Items) > 0 || len(section.Blocks) > 0 {
			section.SourceURL = sourceURL
		}
		return section
	}

	key := summaryCacheKey(title, spec.label+" v1")
	if cached, ok := lookupSummary(key); ok {
		return withContent(decodeSectionContent(cached), sectionStatusWarmed)
	}
	if SummaryDisabled() {
		return withContent(SectionContent{}, sectionStatusRetry)
	}
	answer, err := generateSectionContent(ctx, spec.label, spec.instruction, fullText)
	if err != nil {
		return withContent(SectionContent{}, sectionStatusRetry)
	}
	saveSummary(key, encodeSectionContent(answer))
	return withContent(answer, sectionStatusWarmed)
}

// decodeSectionContent parses a stored section value: SummaryNone, or the
// {summary, items} JSON written by encodeSectionContent.
func decodeSectionContent(cached string) SectionContent {
	trimmed := strings.TrimSpace(cached)
	if trimmed == SummaryNone {
		return SectionContent{Summary: SummaryNone, Items: []SectionItem{}}
	}
	var decoded SectionContent
	if err := json.Unmarshal([]byte(trimmed), &decoded); err != nil {
		return SectionContent{Summary: trimmed, Items: []SectionItem{}}
	}
	decoded = sanitizeSectionContent(decoded)
	for i := range decoded.Items {
		decoded.Items[i].Label = strings.TrimSpace(decoded.Items[i].Label)
		decoded.Items[i].Value = strings.TrimSpace(decoded.Items[i].Value)
	}
	decoded.Summary = strings.TrimSpace(decoded.Summary)
	return decoded
}

// extractLeadBlocks returns the article text before the first heading.
func extractLeadBlocks(fullText string, headings []wikipediaHeading) []WikipediaTextBlock {
	headingSet := make(map[string]bool, len(headings))
	for _, h := range headings {
		headingSet[h.Line] = true
	}
	var paragraphs []string
	for _, line := range strings.Split(fullText, "\n") {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		if headingSet[trimmed] {
			break
		}
		paragraphs = append(paragraphs, trimmed)
	}
	text := strings.Join(paragraphs, "\n\n")
	if text == "" {
		return nil
	}
	return []WikipediaTextBlock{{Text: text}}
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

// OfficialSectionSpecs returns the label and prompt instruction for each
// official-source section (officialSummarySections) so the official-warm tool
// and the handler share the same wording the Wikipedia path uses. Sections not
// in officialSummarySections are omitted, so an item with no history or
// production text simply has no stored entry for that key.
func OfficialSectionSpecs() map[string]struct {
	Label       string
	Instruction string
} {
	specs := map[string]struct {
		Label       string
		Instruction string
	}{}
	for _, key := range officialSummarySections {
		for _, s := range sectionSpecs {
			if s.key == key {
				specs[key] = struct {
					Label       string
					Instruction string
				}{Label: s.label, Instruction: s.instruction}
				break
			}
		}
	}
	return specs
}

func matchSectionHeading(headings []wikipediaHeading, candidates []string) *wikipediaHeading {
	for _, candidate := range candidates {
		for i, heading := range headings {
			if heading.Line == candidate {
				return &headings[i]
			}
		}
	}
	return nil
}

func fetchWikipediaSectionHeadings(ctx context.Context, title string) ([]wikipediaHeading, error) {
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

func fetchWikipediaPlainText(ctx context.Context, title string) (text string, resolvedTitle string, err error) {
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
