package services

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// SanitizeStats reports how many entries SanitizeCacheFile visited and which
// ones were rewritten.
type SanitizeStats struct {
	Total              int
	Changed            int
	Unchanged          int
	SkippedHeadingMaps int
}

// SanitizeCacheFile rewrites each summary entry in the cache through
// decodeSectionContent → encodeSectionContent so any corrupted entry (over-
// closed JSON, markdown code-fence wrap, Latin-1 mojibake produced by an older
// build) is normalized to the plain shape the UI expects. Heading-map entries
// (a top-level object whose keys are the section labels rather than summary /
// items / routes) are left untouched — they are a different cache shape and
// decoding them as a section would clobber their contents.
//
// A .bak backup is written before the file is atomically replaced, so the
// command is safe to run repeatedly and trivial to roll back.
func SanitizeCacheFile(path string) (SanitizeStats, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return SanitizeStats{}, err
	}
	var raw map[string]string
	if err := json.Unmarshal(data, &raw); err != nil {
		return SanitizeStats{}, err
	}

	out := make(map[string]string, len(raw))
	stats := SanitizeStats{Total: len(raw)}
	for k, v := range raw {
		trimmed := strings.TrimSpace(v)
		if !strings.HasPrefix(trimmed, "{") {
			out[k] = v
			stats.Unchanged++
			continue
		}
		// Distinct the heading-map shape from a section (a section MUST have
		// at least one of the three keys below).
		var topKeys map[string]json.RawMessage
		if err := json.Unmarshal([]byte(trimmed), &topKeys); err != nil {
			out[k] = v
			stats.Unchanged++
			continue
		}
		_, hasSummary := topKeys["summary"]
		_, hasItems := topKeys["items"]
		_, hasRoutes := topKeys["routes"]
		if !hasSummary && !hasItems && !hasRoutes {
			// Heading map: different cache shape, leave as-is.
			out[k] = v
			stats.SkippedHeadingMaps++
			continue
		}
		decoded := decodeSectionContent(v)
		repaired := encodeSectionContent(decoded)
		if repaired == v {
			out[k] = v
			stats.Unchanged++
			continue
		}
		out[k] = repaired
		stats.Changed++
	}

	bak := path + ".bak"
	if err := os.WriteFile(bak, data, 0o644); err != nil {
		return stats, fmt.Errorf("backup: %w", err)
	}
	b, err := json.Marshal(out)
	if err != nil {
		return stats, fmt.Errorf("marshal: %w", err)
	}
	if dir := filepath.Dir(path); dir != "" {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return stats, err
		}
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o644); err != nil {
		return stats, err
	}
	if err := os.Rename(tmp, path); err != nil {
		return stats, err
	}
	return stats, nil
}
