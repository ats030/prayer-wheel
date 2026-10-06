package shared

import (
	"os"
	"time"
)

// Public requests retain their existing limit. Offline generation can wait for
// the local proxy's ten-minute background queue fairness window.
func SummaryRequestTimeout() time.Duration {
	d, err := time.ParseDuration(os.Getenv("SUMMARY_REQUEST_TIMEOUT"))
	if err != nil || d <= 0 || d > 30*time.Minute {
		return time.Minute
	}
	return d
}
