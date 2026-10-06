package services

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
)

var OllamaBaseURL = "http://localhost:11434"

var summaryModel = func() string {
	if model := strings.TrimSpace(os.Getenv("OLLAMA_MODEL")); model != "" {
		return model
	}
	return "gemma4:12b"
}()

const (
	summaryPromptSystem  = "日本語の史跡アプリの情報編集者です。記事本文から指示された情報を抜き出して、自然な日本語で簡潔な要約を1つの段落にまとめてください。記事の事実のみを用い、推測や追加の情報は含めません。該当する記述が全くないと判断できる場合は、1語で「" + SummaryNone + "」とだけ答えてください。"
	summaryTimeout       = 60 * time.Second
	maxSummaryInputRunes = 12000
	// SummaryNone is the exact token the model is instructed to reply with when
	// the article has no usable content for the requested section. Callers treat
	// it as "no relevant text" and fall back to the raw blocks / placeholder.
	SummaryNone = "なし"
)

var summaryClient = &http.Client{Timeout: summaryTimeout + 10*time.Second}

var ErrSummaryUnavailable = errors.New("summary is temporarily unavailable")

func summarizePrompt(sectionLabel, instruction, sourceText string) string {
	text := strings.TrimSpace(sourceText)
	if runes := []rune(text); len(runes) > maxSummaryInputRunes {
		text = string(runes[:maxSummaryInputRunes])
	}
	return "## タスク\n下の記事本文から、「" + sectionLabel + "」に関する情報を抜き出してください。\n指示: " + instruction + "\n## 記事本文\n" + text + "\n上記に基づいて、1つの自然な段落に簡潔に要約してください。"
}

// headingPromptSystem pins the assistant's role for the heading-resolution
// pass so the model produces exactly one JSON object keyed by the section
// identifiers the caller supplied.
const headingPromptSystem = "あなたは日本語の史跡アプリの編集者です。記事の見出しと内容を照らして、指定されたセクションへ見出しを割り当ててください。推測は含めません。該当しないセクションの値は空文字列にしてください。出力はJSONオブジェクト1行のみです。"

// resolveSectionsForHeadings asks the local LLM to map each detail-panel
// section (identified by spec.key) to the single article heading that best
// carries its content. It is invoked only as a fallback: the exact-match pass
// in matchSectionHeading runs first, and this LLM call happens only when at
// least one section is still unresolved, so articles whose headings line up
// with the candidate list never pay the cost.
//
// The model returns JSON of the form {"history":"…","remains":"…","access":"…",
// "highlights":"…"}; a section with no suitable heading is mapped to "". The
// response envelope is decoded by callOllamaForJSON, which also tolerates the
// common case of the model wrapping the JSON in a backtick fence or a short
// explanatory sentence by extracting the first balanced {...} block.
func resolveSectionsForHeadings(ctx context.Context, title string, specs []sectionSpec, headings []string, requireAllKeys ...bool) (map[string]string, error) {
	reqCtx, cancel := context.WithTimeout(ctx, summaryTimeout)
	defer cancel()

	var b strings.Builder
	b.WriteString("## タスク\n")
	b.WriteString("この日本語Wikipedia記事の見出しから、各セクションの内容を最もよく表す見出しに1つずつ割り当ててください。\n")
	b.WriteString("## セクション\n")
	keys := make([]string, 0, len(specs))
	for _, s := range specs {
		b.WriteString("- " + s.key + "（" + strings.Join(s.candidates, "、") + "）\n")
		keys = append(keys, s.key)
	}
	b.WriteString("## 記事の見出し\n")
	for i, h := range headings {
		fmt.Fprintf(&b, "%d. %s\n", i+1, h)
	}
	b.WriteString("## 出力\n")
	var keysJSON strings.Builder
	for i, k := range keys {
		if i > 0 {
			keysJSON.WriteString(",")
		}
		keysJSON.WriteString(fmt.Sprintf("%q", k))
		keysJSON.WriteString(":\"…\"")
	}
	b.WriteString("{" + keysJSON.String() + "}")
	b.WriteString(" のJSONオブジェクトを1行のみで出力してください。割り当てられないセクションはその値に空文字列をいれてください。見出しの値は記事の見出しリストのいずれかをそのまま使用し、それ以外の文字列を出力しないでください。")

	payload := map[string]any{
		"model":  summaryModel,
		"stream": false,
		"think":  false,
		"messages": []map[string]string{
			{"role": "system", "content": headingPromptSystem + "\n記事タイトル: " + title},
			{"role": "user", "content": b.String()},
		},
		"options": map[string]any{"temperature": 0.0, "num_predict": 256},
	}

	return callOllamaForJSON(reqCtx, payload, keys, requireAllKeys...)
}

// callOllamaForJSON sends a single /api/chat request and decodes the assistant
// message into a JSON object mapping the supplied keys to strings. It returns
// an error on transport failure, an HTTP-level failure (>= 400), an
// unparseable body, an empty content field, or a response missing any of the
// expected keys; callers treat all of these as "no result" and fall back.
func callOllamaForJSON(ctx context.Context, payload map[string]any, keys []string, requireAllKeys ...bool) (map[string]string, error) {
	buf, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, OllamaBaseURL+"/api/chat", strings.NewReader(string(buf)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := summaryClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		return nil, fmt.Errorf("ollama status %d (model %s)", resp.StatusCode, summaryModel)
	}
	var out struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	content := strings.TrimSpace(out.Message.Content)
	if content == "" {
		return nil, ErrSummaryUnavailable
	}
	// The model is instructed to emit exactly one JSON object; tolerate the case
	// where it wraps the JSON in a backtick fence or a brief explanatory sentence
	// by extracting the first balanced {...} block.
	s, e := strings.Index(content, "{"), strings.Index(content, "}")
	if s == -1 || e == -1 || e < s {
		return nil, errors.New("no JSON object in Ollama heading-resolution response")
	}
	jsonBlob := content[s : e+1]
	var decoded map[string]any
	if err := json.Unmarshal([]byte(jsonBlob), &decoded); err != nil {
		return nil, err
	}
	result := make(map[string]string, len(keys))
	for _, k := range keys {
		if v, ok := decoded[k].(string); ok {
			result[k] = v
		} else {
			if len(requireAllKeys) > 0 && requireAllKeys[0] {
				return nil, fmt.Errorf("heading verdict missing string key %s", k)
			}
			result[k] = ""
		}
	}
	return result, nil
}

// generateSummary asks the local LLM for a concise Japanese summary of
// sourceText for the given sectionLabel. It returns the trimmed summary text.
// The caller treats ErrSummaryUnavailable (LLM unreachable or empty response)
// as a fallback signal and displays the raw blocks instead.

func generateSummary(ctx context.Context, sectionLabel, instruction, sourceText string) (string, error) {
	reqCtx, cancel := context.WithTimeout(ctx, summaryTimeout)
	defer cancel()

	payload := map[string]any{
		"model":  summaryModel,
		"stream": false,
		// gemma4 / qwen3 等の thinking モデルはデフォルトでは思考を message.thinking
		// に書き、content は空のまま done_reason=length で止まる。think:false を
		// 付与すると思考を無効化した直接応答が content に帰るので、要約を得られる。
		// 非 thinking モデルではこのキーは安全に無視される。
		"think": false,
		"messages": []map[string]string{
			{"role": "system", "content": summaryPromptSystem},
			{"role": "user", "content": summarizePrompt(sectionLabel, instruction, sourceText)},
		},
		"options": map[string]any{"temperature": 0.2, "num_predict": 512},
	}
	buf, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, OllamaBaseURL+"/api/chat", strings.NewReader(string(buf)))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := summaryClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		return "", fmt.Errorf("ollama status %d (model %s)", resp.StatusCode, summaryModel)
	}
	var out struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	summary := strings.TrimSpace(out.Message.Content)
	if !validPlainSummary(summary) {
		return "", ErrSummaryUnavailable
	}
	return summary, nil
}

func validPlainSummary(summary string) bool {
	s := strings.TrimSpace(summary)
	return s != "" && !strings.HasPrefix(s, "{") && !strings.HasPrefix(s, "[") && !strings.HasPrefix(s, "```") && s != "null" && s != "true" && s != "false"
}
