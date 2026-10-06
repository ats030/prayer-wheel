package services

import (
	"net/http"
	"testing"
	"time"
)

func TestRetryableStatus(t *testing.T) {
	cases := []struct {
		status int
		want   bool
	}{
		{429, true},
		{500, true},
		{503, true},
		{404, false},
		{400, false},
		{200, false},
	}
	for _, c := range cases {
		if got := retryableStatus(c.status); got != c.want {
			t.Errorf("retryableStatus(%d) = %v, want %v", c.status, got, c.want)
		}
	}
}

func TestRetryDelayForUsesHeader(t *testing.T) {
	cases := []struct {
		name   string
		header string
		base   time.Duration
		want   time.Duration
	}{
		{"numeric", "21", 250 * time.Millisecond, 21 * time.Second},
		{"zero falls back", "0", 250 * time.Millisecond, 250 * time.Millisecond},
		{"no header falls back", "", 250 * time.Millisecond, 250 * time.Millisecond},
		{"non-numeric falls back", "garbage", 250 * time.Millisecond, 250 * time.Millisecond},
	}
	for _, c := range cases {
		h := http.Header{}
		if c.header != "" {
			h.Set("Retry-After", c.header)
		}
		got := retryDelayFor(&http.Response{Header: h}, c.base)
		if got != c.want {
			t.Errorf("%s: retryDelayFor = %v, want %v", c.name, got, c.want)
		}
	}
}
