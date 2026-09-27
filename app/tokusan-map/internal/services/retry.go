package services

import (
	"context"
	"log"
	"net/http"
	"strconv"
	"time"
)

// retryableStatus reports whether a Wikimedia API HTTP status is safe to retry.
// Only 429 and 5xx are considered transient; any other 4xx is a hard failure
// that must surface to the caller immediately.
func retryableStatus(status int) bool {
	return status == http.StatusTooManyRequests || status >= http.StatusInternalServerError
}

// retryDelayFor picks the backoff before the next attempt, preferring a
// Retry-After header from the upstream when present and parseable. It falls
// back to the caller's base duration when the header is absent, malformed,
// or a past HTTP-date.
func retryDelayFor(resp *http.Response, base time.Duration) time.Duration {
	if resp == nil {
		return base
	}
	v := resp.Header.Get("Retry-After")
	if v == "" {
		return base
	}
	if secs, err := strconv.Atoi(v); err == nil && secs > 0 {
		return time.Duration(secs) * time.Second
	}
	if t, err := time.Parse(time.RFC1123, v); err == nil {
		if d := time.Until(t); d > 0 {
			return d
		}
	}
	return base
}

// withRetry retries a fallible Wikimedia-family API call on transient failures
// (HTTP 429, 5xx, and network errors) up to maxRetries times with exponential
// backoff. A Retry-After response value takes precedence over the calculated
// backoff.
func withRetry[T any](ctx context.Context, label string, attempt func() (T, error)) (T, error) {
	backoff := initialBackoff
	var lastErr error
	var zero T

	for i := 0; i <= maxRetries; i++ {
		if i > 0 {
			log.Printf("tokusan-map: %s API retry %d/%d (last error: %v)", label, i, maxRetries, lastErr)
		}

		result, err := attempt()
		if err == nil {
			return result, nil
		}
		lastErr = err

		if !isRetryableAPIError(err) {
			return zero, err
		}
		if i == maxRetries {
			break
		}

		_, retryAfter, _ := statusFromError(err)
		if retryAfter > 0 {
			backoff = retryAfter
		}

		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return zero, err
		}
		backoff *= 2
	}

	log.Printf("tokusan-map: %s API retries exhausted: %v", label, lastErr)
	return zero, lastErr
}
