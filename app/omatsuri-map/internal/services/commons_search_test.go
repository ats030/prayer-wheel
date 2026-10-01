package services

import (
	"regexp"
	"testing"
)

var baseNameExtExt = regexp.MustCompile(`\.(jpg|jpeg|png|svg|gif|webp)$`)

func TestBaseNameStripsExtension(t *testing.T) {
	cases := []struct{name, want string}{
		{"博多祇園山笠.jpg", "博多祇園山笠"},
		{"博多祇園山笠.png", "博多祇園山笠"},
		{"博多祇園山笠", "博多祇園山笠"},
		{"山車 2024.svg (thumb).jpg", "山車 2024.svg (thumb)"},
		{"noext", "noext"},
	}
	for _, c := range cases {
		if got := baseName(c.name); got != c.want {
			t.Fatalf("baseName(%q) = %q, want %q", c.name, got, c.want)
		}
	}
}

func TestBaseNameOnlyStripsImageExtensions(t *testing.T) {
	// A non-image suffix must not be stripped.
	if got := baseName("festo (1).txt"); got != "festo (1).txt" {
		t.Fatalf("baseName = %q, want the input unchanged", got)
	}
}
