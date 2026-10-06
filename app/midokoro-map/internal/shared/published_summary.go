package shared

import (
	"fmt"
	"time"
)

var SummarySections = map[string][]string{
	"shiseki":  {"about", "history", "remains", "access", "highlights"},
	"omatsuri": {"about", "history", "highlights", "flow", "access", "tourism"},
	"onsen":    {"about", "history", "food", "efficacy", "access", "tourism"},
	"tokusan":  {"about", "history", "production", "visit"},
}

type PublishedSummaries struct {
	Version        int                                              `json:"version"`
	CheckedAt      time.Time                                        `json:"checked_at"`
	Rosters        map[string]string                                `json:"rosters"`
	Counts         map[string]int                                   `json:"counts"`
	SourceDBHashes map[string]string                                `json:"source_db_hashes"`
	Items          map[string]map[string]map[string]PreparedSection `json:"items"`
}

func (p PublishedSummaries) Validate() error {
	if p.Version != 6 || p.CheckedAt.IsZero() || len(p.Items) != len(SummarySections) {
		return fmt.Errorf("invalid published summary version or categories")
	}
	for kind, sections := range SummarySections {
		if p.Rosters[kind] == "" || p.Counts[kind] == 0 || len(p.Items[kind]) != p.Counts[kind] {
			return fmt.Errorf("incomplete published %s roster", kind)
		}
		for id, values := range p.Items[kind] {
			if id == "" || !SummaryComplete(values, sections) || len(values) != len(sections) {
				return fmt.Errorf("incomplete published %s/%s", kind, id)
			}
			for _, s := range values {
				if s.Status == "no_source" && (s.Summary != "" || len(s.Items) != 0) {
					return fmt.Errorf("nonempty absent summary %s/%s", kind, id)
				}
			}
		}
	}
	return nil
}
