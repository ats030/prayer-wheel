package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"midokoro-map/internal/shared"
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
		cacheKey := summaryCacheKey(title, spec.label+" v1")
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
		if ready {
			cached, ok := lookupSummary(cacheKey)
			content := decodeSectionContent(cached)
			ready = ok && (content.Summary != "" || len(content.Items) > 0)
		}
		out[spec.key] = shared.Prepared(section.Summary, section.Items, len(section.Items) > 0, source, fullText, ready)
	}
	return out, nil
}

// PrepareOfficialSummary reuses the legacy history/production cache and adds
// the previously raw overview. Source-free visit is explicitly absent.
func PrepareOfficialSummary(ctx context.Context, service *TokusanService, item Tokusan) (map[string]shared.PreparedSection, error) {
	out := map[string]shared.PreparedSection{}
	history, production, err := service.OfficialSourceChecked(item.QID)
	if err != nil {
		return nil, err
	}
	for _, key := range []string{"about", "history", "production", "visit"} {
		text := ""
		switch key {
		case "about":
			text = item.Description
		case "history":
			text = history
		case "production":
			text = production
			if text == "" {
				text = item.ProductionArea
			}
		}
		if text == "" {
			out[key] = shared.Prepared("", nil, false, item.SourceURL, text, true)
			continue
		}
		var content SectionContent
		var err error
		if key == "history" || key == "production" {
			var ok bool
			content, ok = GetOfficialSummary(item.QID, key)
			markerKey := "midokoro-official-source-v1:" + item.QID + ":" + key
			marker, matched := lookupSummary(markerKey)
			proof, verified := lookupSummary("midokoro-verified-none:" + markerKey)
			ok = ok && (content.Summary != SummaryNone || verified && proof == "1") && matched && marker == shared.SourceHash(text) && (content.Summary != "" || len(content.Items) > 0)
			if !ok {
				content, err = SummarizeOfficialSection(ctx, item.QID, key, text)
				if err == nil {
					saveSummary(markerKey, shared.SourceHash(text))
					if content.Summary == SummaryNone {
						saveSummary("midokoro-verified-none:"+markerKey, "1")
					}
				}
			}
		} else {
			cacheKey := "midokoro-about-v1:" + item.QID + ":" + shared.SourceHash(text)
			value, ok := lookupSummary(cacheKey)
			if ok {
				c := decodeSectionContent(value)
				ok = c.Summary != "" || len(c.Items) > 0
			}
			if ok && decodeSectionContent(value).Summary == SummaryNone {
				proof, verified := lookupSummary("midokoro-verified-none:" + cacheKey)
				ok = verified && proof == "1"
			}
			if ok {
				content = decodeSectionContent(value)
			} else {
				content, err = generateSectionContent(ctx, "概要", "どんな特産物で、どんな特徴があるかを本文の事実だけで簡潔に説明する。", text)
				if err == nil {
					saveSummary(cacheKey, encodeSectionContent(content))
					if content.Summary == SummaryNone {
						saveSummary("midokoro-verified-none:"+cacheKey, "1")
					}
				}
			}
		}
		if err != nil {
			return out, err
		}
		out[key] = shared.Prepared(content.Summary, content.Items, len(content.Items) > 0, item.SourceURL, text, content.Summary != "" || len(content.Items) > 0)
	}
	return out, nil
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
