package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"midokoro-map/internal/shared"
	"strings"
)

// PrepareSummary is the strict offline path. A failed heading/LLM request is
// retryable even when the public handler would silently use raw-text fallback.
func PrepareSummary(ctx context.Context, title, qid, description, descriptionSource string) (map[string]shared.PreparedSection, error) {
	if SummaryDisabled() {
		return nil, fmt.Errorf("summary generation is disabled")
	}
	out := map[string]shared.PreparedSection{}
	var fullText, resolvedTitle string
	var err error
	if title != "" {
		fullText, resolvedTitle, err = fetchWikipediaPlainText(ctx, title, true)
	}
	if title == "" || errors.Is(err, errWikipediaArticleContentNotFound) {
		err = nil
		for _, spec := range sectionSpecs {
			out[spec.key] = shared.Prepared("", nil, false, "", "", true)
		}
		out["about"] = shared.Prepared("", nil, false, "", "", true)
		if description != "" {
			out["about"], err = prepareIntro(ctx, qid, description, descriptionSource)
		}
		return out, err
	}
	if err != nil {
		return nil, err
	}
	headings, err := fetchWikipediaSectionHeadings(ctx, title, true)
	if err != nil {
		return nil, err
	}
	source := wikipediaArticleURL(resolvedTitle)
	headingMap, err := strictHeadingMap(ctx, title, headings)
	if err != nil {
		return nil, err
	}
	for _, spec := range sectionSpecs {
		cacheKey := summaryCacheKey(title, spec.label+" v3")
		if cached, ok := lookupSummary(cacheKey); ok {
			content := decodeSectionContent(cached)
			bound, knownSource := lookupSummary("midokoro-source-v1:" + cacheKey)
			proof, verified := lookupSummary("midokoro-verified-none:" + cacheKey)
			if !knownSource || bound != shared.SourceHash(fullText) || content.Summary == SummaryNone && (!verified || proof != shared.SourceHash(fullText)) || content.Summary == "" && len(content.Items) == 0 {
				summaryCache.mu.Lock()
				delete(summaryCache.byKey, cacheKey)
				summaryCache.mu.Unlock()
			}
		}
		section := resolvePanelSection(ctx, title, fullText, headings, source, spec, headingMap)
		if section.Status == sectionStatusWarmed {
			if _, ok := lookupSummary(cacheKey); ok {
				saveSummary("midokoro-source-v1:"+cacheKey, shared.SourceHash(fullText))
			}
		}
		if cached, ok := lookupSummary(cacheKey); ok && decodeSectionContent(cached).Summary == SummaryNone && section.Status == sectionStatusWarmed {
			saveSummary("midokoro-verified-none:"+cacheKey, shared.SourceHash(fullText))
		}
		ready := section.Status == sectionStatusWarmed
		if ready && len(section.Blocks) > 0 && section.Summary == "" && len(section.Items) == 0 {
			cached, ok := lookupSummary(summaryCacheKey(title, spec.label+" v3"))
			ready = ok && decodeSectionContent(cached).Summary == SummaryNone
		}
		out[spec.key] = shared.Prepared(section.Summary, section.Items, len(section.Items) > 0, source, fullText, ready)
	}
	leadLines := []string{}
	headingSet := map[string]bool{}
	for _, h := range headings {
		headingSet[h.Line] = true
	}
	for _, line := range strings.Split(fullText, "\n") {
		if headingSet[strings.TrimSpace(line)] {
			break
		}
		leadLines = append(leadLines, line)
	}
	lead := strings.TrimSpace(strings.Join(leadLines, "\n"))
	// The displayed local/curated introduction is also source material.
	if description != "" {
		lead = description
		source = descriptionSource
	}
	out["about"], err = prepareIntro(ctx, qid, lead, source)
	return out, err
}

func prepareIntro(ctx context.Context, id, text, source string) (shared.PreparedSection, error) {
	if strings.TrimSpace(text) == "" {
		return shared.Prepared("", nil, false, source, text, true), nil
	}
	key := "midokoro-about-v1:" + id + ":" + shared.SourceHash(text)
	cached, ok := lookupSummary(key)
	if ok {
		content := decodeSectionContent(cached)
		ok = content.Summary != "" || len(content.Items) > 0
	}
	if ok && decodeSectionContent(cached).Summary == SummaryNone {
		proof, verified := lookupSummary("midokoro-verified-none:" + key)
		ok = verified && proof == "1"
	}
	if !ok {
		result, err := generateSectionContent(ctx, "概要", "この場所・行事が何で、どんな特徴があるかを、本文の事実だけで簡潔に説明する。", text)
		if err != nil {
			return shared.Prepared("", nil, false, source, text, false), err
		}
		cached = encodeSectionContent(result)
		saveSummary(key, cached)
		if decodeSectionContent(cached).Summary == SummaryNone {
			saveSummary("midokoro-verified-none:"+key, "1")
		}
	}
	content := decodeSectionContent(cached)
	return shared.Prepared(content.Summary, content.Items, len(content.Items) > 0, source, text, content.Summary != "" || len(content.Items) > 0), nil
}

// Legacy heading caches omit negative verdicts. Reuse only a complete mapping;
// otherwise resolve once and retain explicit empty values for confirmed absence.
func strictHeadingMap(ctx context.Context, title string, headings []wikipediaHeading) (map[string]string, error) {
	specs := []sectionSpec{}
	exact := map[string]string{}
	lines := []string{}
	validHeadings := map[string]bool{"": true}
	for _, h := range headings {
		lines = append(lines, h.Line)
		validHeadings[h.Line] = true
	}
	missing := false
	for _, spec := range sectionSpecs {
		if len(spec.candidates) == 0 {
			continue
		}
		specs = append(specs, spec)
		if hit := matchSectionHeading(headings, spec.candidates); hit != nil {
			exact[spec.key] = hit.Line
		} else {
			missing = true
			exact[spec.key] = ""
		}
	}
	if !missing || len(headings) == 0 {
		return exact, nil
	}
	validate := func(m map[string]string) bool {
		for _, spec := range specs {
			value, ok := m[spec.key]
			if !ok || !validHeadings[value] {
				return false
			}
		}
		return true
	}
	key := headingMapCacheKey(title, lines)
	var mapping map[string]string
	if cached, ok := lookupSummary(key); ok && json.Unmarshal([]byte(cached), &mapping) == nil && validate(mapping) {
		return mapping, nil
	}
	mapping, err := resolveSectionsForHeadings(ctx, title, specs, lines, true)
	if err != nil {
		return nil, err
	}
	if !validate(mapping) {
		return nil, fmt.Errorf("incomplete heading verdict: %s", title)
	}
	for key, value := range exact {
		if value != "" {
			mapping[key] = value
		}
	}
	b, err := json.Marshal(mapping)
	if err != nil {
		return nil, err
	}
	saveSummary(key, string(b))
	return mapping, nil
}
