package shared

import "testing"

func TestEmptyItemsCannotPassSummaryAudit(t *testing.T) {
	section := PreparedSection{Status: "summarized", Items: []PreparedItem{}}
	if SummaryComplete(map[string]PreparedSection{"about": section}, []string{"about"}) {
		t.Fatal("empty summary/items passed")
	}
	section = Prepared("", []map[string]string{{}}, true, "source", "text", true)
	if section.Status != "retry" {
		t.Fatalf("malformed rows accepted: %+v", section)
	}
}
