package shared

import (
	"testing"
	"time"
)

func TestOfflineTimeoutDoesNotChangePublicDefault(t *testing.T) {
	for _, v := range []string{"", "bad", "-1m", "31m"} {
		t.Setenv("SUMMARY_REQUEST_TIMEOUT", v)
		if SummaryRequestTimeout() != time.Minute {
			t.Fatal("invalid setting changed public limit")
		}
	}
	t.Setenv("SUMMARY_REQUEST_TIMEOUT", "15m")
	if SummaryRequestTimeout() != 15*time.Minute {
		t.Fatal("offline wait not applied")
	}
}
