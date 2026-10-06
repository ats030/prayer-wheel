package handlers

import "testing"

func TestBuildFullLocation(t *testing.T) {
	tests := []struct {
		name  string
		parts []string
		want  string
	}{
		{name: "hierarchy", parts: []string{"青森県", "青森市", "新町", "県道16号"}, want: "青森県 青森市 新町 県道16号"},
		{name: "deduplicates", parts: []string{"北海道", "札幌市", "札幌市", "大通西"}, want: "北海道 札幌市 大通西"},
		{name: "skips empty", parts: []string{"京都府", "", "東山区", ""}, want: "京都府 東山区"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := buildFullLocation(tt.parts...); got != tt.want {
				t.Fatalf("buildFullLocation() = %q, want %q", got, tt.want)
			}
		})
	}
}
