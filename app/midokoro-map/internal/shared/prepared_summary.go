package shared

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"strings"
)

// PreparedSection contains derived text only. Raw source stays in the source
// database/cache and is never copied into the publishable summary document.
type PreparedItem struct {
	Label string `json:"label,omitempty"`
	Value string `json:"value,omitempty"`
	From  string `json:"from,omitempty"`
	To    string `json:"to,omitempty"`
}

type PreparedSection struct {
	Status    string         `json:"status"` // summarized, no_source, retry
	Summary   string         `json:"summary,omitempty"`
	Items     []PreparedItem `json:"items,omitempty"`
	SourceURL string         `json:"source_url,omitempty"`
	// Hash of the source checked during this pass, not proof of the generation
	// revision for legacy caches whose original source revision was not stored.
	CheckedSourceHash string `json:"checked_source_hash,omitempty"`
}

func SourceHash(text string) string { return fmt.Sprintf("%x", sha256.Sum256([]byte(text))) }

func Prepared(summary string, items any, hasItems bool, source, text string, ready bool) PreparedSection {
	var rows []PreparedItem
	if b, err := json.Marshal(items); err == nil {
		_ = json.Unmarshal(b, &rows)
	}
	valid := rows[:0]
	for _, row := range rows {
		if strings.TrimSpace(row.Label+row.Value+row.From+row.To) != "" {
			valid = append(valid, row)
		}
	}
	if hasItems && len(valid) == 0 {
		ready = false
	}
	s := PreparedSection{Summary: summary, Items: valid, SourceURL: source, CheckedSourceHash: SourceHash(text), Status: "retry"}
	if ready {
		s.Status = "no_source"
		if strings.TrimSpace(summary) != "" && summary != "なし" || len(valid) > 0 {
			s.Status = "summarized"
		}
	}
	if summary == "なし" {
		s.Summary = ""
	}
	return s
}

func SummaryComplete(sections map[string]PreparedSection, required []string) bool {
	for _, key := range required {
		s, ok := sections[key]
		if !ok || (s.Status != "summarized" && s.Status != "no_source") {
			return false
		}
		if s.Status == "summarized" && strings.TrimSpace(s.Summary) == "" && len(s.Items) == 0 {
			return false
		}
	}
	return len(required) > 0
}

// ValidateWikiEnvelope prevents HTTP-200 API errors from becoming a cached
// negative result in the offline audit. Empty sections are valid only when the
// server explicitly returns a sections array.
func ValidateWikiEnvelope(body []byte, container, field string) error {
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(body, &envelope); err != nil {
		return err
	}
	if apiError, ok := envelope["error"]; ok {
		return fmt.Errorf("Wikipedia API error: %s", apiError)
	}
	var payload map[string]json.RawMessage
	if err := json.Unmarshal(envelope[container], &payload); err != nil {
		return fmt.Errorf("Wikipedia %s payload missing: %w", container, err)
	}
	var entries []json.RawMessage
	if err := json.Unmarshal(payload[field], &entries); err != nil || entries == nil {
		return fmt.Errorf("Wikipedia %s.%s array missing", container, field)
	}
	if field == "pages" && len(entries) == 0 {
		return fmt.Errorf("Wikipedia pages list empty")
	}
	if field == "pages" {
		for _, entry := range entries {
			var page map[string]json.RawMessage
			if err := json.Unmarshal(entry, &page); err != nil {
				return err
			}
			var missing bool
			_ = json.Unmarshal(page["missing"], &missing)
			if missing {
				continue
			}
			var extract, title string
			if err := json.Unmarshal(page["extract"], &extract); err != nil {
				return fmt.Errorf("Wikipedia extract field missing: %w", err)
			}
			if err := json.Unmarshal(page["title"], &title); err != nil || title == "" {
				return fmt.Errorf("Wikipedia resolved title missing")
			}
		}
	}
	return nil
}
