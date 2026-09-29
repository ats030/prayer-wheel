package services

import (
	"encoding/json"
	"testing"
)

func TestDecodeExtmetadata(t *testing.T) {
	cases := []struct {
		name    string
		input   string
		wantLen int
		wantLic string
	}{
		{"object", `{"License":{"value":"cc-by-sa-4.0"}}`, 1, "cc-by-sa-4.0"},
		{"empty array (bug shape)", `[]`, 0, ""},
		{"empty object", `{}`, 0, ""},
		{"null", `null`, 0, ""},
		{"empty array with spaces", ` [ ] `, 0, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			m := decodeExtmetadata(json.RawMessage(tc.input))
			if len(m) != tc.wantLen {
				t.Fatalf("len = %d, want %d", len(m), tc.wantLen)
			}
			if got := m["License"].Value; got != tc.wantLic {
				t.Fatalf("License = %q, want %q", got, tc.wantLic)
			}
		})
	}
}
