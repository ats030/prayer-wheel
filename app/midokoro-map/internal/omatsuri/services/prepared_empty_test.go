package services

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestEmptyStructuredAnswerRetriesAndExplicitNoneCompletes(t *testing.T) {
	for _, content := range []string{`{"summary":"","items":[]}`, `なし`} {
		t.Run(content, func(t *testing.T) {
			model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_ = json.NewEncoder(w).Encode(map[string]any{"message": map[string]string{"content": content}})
			}))
			defer model.Close()
			old := OllamaBaseURL
			OllamaBaseURL = model.URL
			defer func() { OllamaBaseURL = old }()
			got, err := generateSectionContent(context.Background(), "概要", "要約する", "原文。")
			if content == "なし" {
				if err != nil || got.Summary != SummaryNone {
					t.Fatalf("explicit absence rejected: %v %+v", err, got)
				}
			} else if err == nil {
				t.Fatal("empty model output became absence")
			}
		})
	}
}
