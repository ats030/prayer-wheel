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
	summaryPromptSystem  = "日本語の温泉アプリの情報編集者です。記事本文から指示された情報を抜き出してください。記事の事実のみを用い、推測や追加の情報は含めません。表現は以下のように正規化してください。範囲・経路の区切りは「〜」に統一します。数字と日本語の間の半角スペースは除去します(例:「1925 年」は「1925年」)。括弧は全角（）に統一します。文調は常体で統一します。固有名詞・数値・年号・駅名・路線名は原文のまま変更しないでください。"
	summaryTimeout       = 60 * time.Second
	maxSummaryInputRunes = 12000
	// SummaryNone is the exact token the model is instructed to reply with when
	// the article has no usable content for the requested section. Callers treat
	// it as "no relevant text" and fall back to the raw blocks / placeholder.
	SummaryNone = "なし"
)

// SectionItem is one labelled row in a structured section answer. Label is the
// short heading of the row (時代 / 品名 / 施設名 / 交通手段 etc.), Value is the
// one or two sentence description under it. From and To are only used by the
// access section (departure and arrival points); they may be empty.
type SectionItem struct {
	Label string `json:"label"`
	Value string `json:"value"`
	From  string `json:"from,omitempty"`
	To    string `json:"to,omitempty"`
}

// SectionContent is the structured LLM response any detail-panel section can
// return: an optional lead sentence plus a list of labelled rows.
type SectionContent struct {
	Summary string        `json:"summary,omitempty"`
	Items   []SectionItem `json:"items"`
}

var summaryClient = &http.Client{Timeout: summaryTimeout + 10*time.Second}

var ErrSummaryUnavailable = errors.New("summary is temporarily unavailable")

func sectionsPrompt(sectionLabel, instruction, sourceText string) string {
	text := strings.TrimSpace(sourceText)
	if runes := []rune(text); len(runes) > maxSummaryInputRunes {
		text = string(runes[:maxSummaryInputRunes])
	}
	schema := `{"summary":"全体をかいつまむ要約(1文程度。無い場合は空文字)","items":[{"label":"行の見出し(時代・品名・施設名・交通手段など1〜4語)","value":"その行の概要(1〜2句)"}]}`
	return "## タスク\n下の記事本文から、「" + sectionLabel + "」に関する情報を抜き出してください。\n指示: " + instruction + "\n出力JSONのschema:\n" + schema + "\n## 記事本文\n" + text + "\n上記に基づいて、JSONオブジェクトを1行のみで出力してください。itemsは必ず配列(array)にしてください(オブジェクトや文字列にすると壊れます)。summaryの値には平文の1文のみ入れ、JSONオブジェクトを埋め込まないでください。末尾の ] と } を必ず閉じた、1行の妥当なJSONを出力してください。"
}

// headingPromptSystem pins the assistant's role for the heading-resolution
// pass so the model produces exactly one JSON object keyed by the section
// identifiers the caller supplied.
const headingPromptSystem = "あなたは日本語の温泉アプリの編集者です。記事の見出しと内容を照らして、指定されたセクションへ見出しを割り当ててください。推測は含めません。該当しないセクションの値は空文字列にしてください。出力はJSONオブジェクト1行のみです。"

// resolveSectionsForHeadings asks the local LLM to map each detail-panel
// section (identified by spec.key) to the single article heading that best
// carries its content. It is invoked only as a fallback: the exact-match pass
// in matchSectionHeading runs first, and this LLM call happens only when at
// least one section is still unresolved, so articles whose headings line up
// with the candidate list never pay the cost.
//
// The model returns JSON of the form {"history":"…","food":"…","access":"…",
// "tourism":"…"}; a section with no suitable heading is mapped to "". The
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
// an error on transport failure, an HTTP-level failure (>= 400), an unparseable
// body, or an empty content field; keys missing from the response (or not held
// as strings) are defaulted to "" so callers can treat them as "no assignment".
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
	// Batch client: the proxy lets it wait GENERATION_QUEUE_TIMEOUT_BATCH
	// (120s) for the generation gate instead of the short interactive
	// timeout, and evicts idle competing models before forwarding.
	req.Header.Set("X-Client-App", "onsen-map-summary-warm")
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

// generateSectionContent asks the local LLM for a structured section answer
// (lead sentence + labelled rows). The model's body is tolerated leniently so a
// malformed answer degrades gracefully:
//
//   - object with items        -> returned as-is (items drive the structured UI)
//   - object without items     -> summary-only shape, shown inline above blocks
//   - unparseable body          -> whole body becomes the plain summary
//
// Only transport / HTTP / empty-content failures return an error, which callers
// treat as "show the raw blocks only".
func generateSectionContent(ctx context.Context, sectionLabel, instruction, sourceText string) (SectionContent, error) {
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
			{"role": "user", "content": sectionsPrompt(sectionLabel, instruction, sourceText)},
		},
		"options": map[string]any{"temperature": 0.2, "num_predict": 4096},
	}
	buf, err := json.Marshal(payload)
	if err != nil {
		return SectionContent{}, err
	}
	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, OllamaBaseURL+"/api/chat", strings.NewReader(string(buf)))
	if err != nil {
		return SectionContent{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Client-App", "onsen-map-summary-warm")
	resp, err := summaryClient.Do(req)
	if err != nil {
		return SectionContent{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		return SectionContent{}, fmt.Errorf("ollama status %d (model %s)", resp.StatusCode, summaryModel)
	}
	var out struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return SectionContent{}, err
	}
	content := strings.TrimSpace(out.Message.Content)
	if content == "" {
		return SectionContent{}, ErrSummaryUnavailable
	}
	if content == SummaryNone {
		return SectionContent{Summary: SummaryNone, Items: []SectionItem{}}, nil
	}
	// The answer is not JSON-shaped at all: treat the whole body as the plain
	// summary (the legacy, still-supported behaviour).
	if strings.IndexByte(content, '{') == -1 {
		return SectionContent{Summary: content, Items: []SectionItem{}}, nil
	}
	s, e := strings.IndexByte(content, '{'), strings.LastIndexByte(content, '}')
	if s != -1 && e != -1 && e < s {
		e = s // malformed: no closing brace after the first '{'
	}
	if s != -1 && e != -1 && e >= s {
		var decoded SectionContent
		if err := json.Unmarshal([]byte(content[s:e+1]), &decoded); err == nil {
			decoded = sanitizeSectionContent(decoded)
			trimSectionItems(&decoded)
			if len(decoded.Items) > 0 || decoded.Summary != "" {
				return decoded, nil
			}
			// Model produced a valid object with nothing in it at all.
			return SectionContent{}, ErrSummaryUnavailable
		}
		// The LLM truncates long answers before the trailing "]" / "}" are
		// emitted (done_reason=length), which leaves the JSON unbalanced. Close
		// the open brackets in order and decode the prefix we do have instead of
		// discarding it.
		if repaired, ok := repairUnclosedJSON(content[s : e+1]); ok {
			var decoded SectionContent
			if err := json.Unmarshal([]byte(repaired), &decoded); err == nil {
				decoded = sanitizeSectionContent(decoded)
				trimSectionItems(&decoded)
				if len(decoded.Items) > 0 || decoded.Summary != "" {
					return decoded, nil
				}
			}
		}
	}
	// Unparseable answer: keep only the parts that are plainly prose so a JSON
	// blob never surfaces as the summary text in the UI.
	decoded, ok := parseEmbeddedSectionContent(content)
	if !ok {
		if prose := recoverPlainSummary(content); prose != "" {
			return SectionContent{Summary: prose, Items: []SectionItem{}}, nil
		}
		return SectionContent{}, ErrSummaryUnavailable
	}
	trimSectionItems(&decoded)
	return decoded, nil
}

// repairUnclosedJSON closes brackets that were opened but never closed in s,
// in the order they were left open (an unterminated string is terminated
// first). It returns ok=false when s is not a well-formed JSON prefix in the
// first place.
func repairUnclosedJSON(s string) (string, bool) {
	var b strings.Builder
	b.Grow(len(s) + 8)
	var stack []rune
	inString := false
	escaped := false
	sawAny := false
	for _, r := range s {
		sawAny = true
		switch {
		case inString:
			if escaped {
				escaped = false
			} else {
				switch r {
				case '\\':
					escaped = true
				case '"':
					inString = false
				}
			}
			b.WriteRune(r)
		default:
			switch r {
			case '"':
				inString = true
				b.WriteRune(r)
			case '{':
				stack = append(stack, '{')
				b.WriteRune(r)
			case '[':
				stack = append(stack, '[')
				b.WriteRune(r)
			case '}', ']':
				if len(stack) == 0 {
					return "", false
				}
				open := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				if (r == '}' && open != '{') || (r == ']' && open != '[') {
					return "", false
				}
				b.WriteRune(r)
			default:
				b.WriteRune(r)
			}
		}
	}
	if inString && !sawAny {
		return "", false
	}
	if inString {
		b.WriteByte('"')
	}
	for i := len(stack) - 1; i >= 0; i-- {
		if stack[i] == '{' {
			b.WriteByte('}')
		} else {
			b.WriteByte(']')
		}
	}
	return b.String(), true
}

// parseEmbeddedSectionContent extracts a {summary, items} object embedded in
// a malformed or truncated answer body, tolerating a missing trailing
// "]" / "}".
func parseEmbeddedSectionContent(content string) (SectionContent, bool) {
	s, e := strings.IndexByte(content, '{'), strings.LastIndexByte(content, '}')
	if s == -1 || e == -1 || e < s {
		return SectionContent{}, false
	}
	blob := content[s : e+1]
	var decoded SectionContent
	if err := json.Unmarshal([]byte(blob), &decoded); err == nil {
		return sanitizeSectionContent(decoded), true
	}
	if repaired, ok := repairUnclosedJSON(blob); ok {
		if err := json.Unmarshal([]byte(repaired), &decoded); err == nil {
			return sanitizeSectionContent(decoded), true
		}
	}
	return SectionContent{}, false
}

// recoverPlainSummary finds the plain-prose lead sentence in a body whose JSON
// envelope could not be parsed, so the useful text still reaches the UI
// instead of the raw blob. Bodies that are not recognisably a summary shape
// (no '"summary":"..."') return "".
func recoverPlainSummary(content string) string {
	const marker = `"summary":"`
	start := strings.Index(content, marker)
	if start == -1 {
		return ""
	}
	// Walk rune by rune over the remainder of the body. content[i] is a byte,
	// and a multibyte UTF-8 character (e.g. Japanese) must be copied whole —
	// re-encoding it one byte at a time turns "荒湯" into Latin-1 mojibake,
	// which is exactly the "summary shows garbage / JSON" bug. A backslash
	// still introduces a two-rune escape we keep verbatim (e.g. \" or \\).
	endMarker := start + len(marker)
	rs := []rune(content[endMarker:])
	var b strings.Builder
	for j := 0; j < len(rs); j++ {
		r := rs[j]
		if r == '\\' && j+1 < len(rs) {
			b.WriteRune(r)
			b.WriteRune(rs[j+1])
			j++
			continue
		}
		if r == '"' {
			break
		}
		b.WriteRune(r)
	}
	prose := strings.TrimSpace(b.String())
	prose = strings.ReplaceAll(prose, `\"`, `"`)
	prose = strings.ReplaceAll(prose, `\\`, `\`)
	return prose
}

func trimSectionItems(c *SectionContent) {
	if c.Items == nil {
		c.Items = []SectionItem{}
	}
	for i := range c.Items {
		c.Items[i].Label = strings.TrimSpace(c.Items[i].Label)
		c.Items[i].Value = strings.TrimSpace(c.Items[i].Value)
		c.Items[i].From = strings.TrimSpace(c.Items[i].From)
		c.Items[i].To = strings.TrimSpace(c.Items[i].To)
	}
}

// sanitizeSectionContent normalises a decoded answer:
//
//   - a nested {summary, items} object stored (truncated or not) as the string
//     in the outer "summary" field is decoded one level deeper and merged, so
//     the stored summary stays plain prose at every nesting depth;
//   - if the nested object cannot be decoded even after bracket repair, the
//     malformed JSON string is dropped from summary entirely (the raw item
//     rows still carry the data) instead of being rendered as visible JSON.
//
// stripCodeFence removes a surrounding ```lang ... ``` markdown fence from s,
// which LLM answers occasionally wrap their JSON object in.
func stripCodeFence(s string) string {
	s = strings.TrimSpace(s)
	if !strings.HasPrefix(s, "```") {
		return s
	}
	firstNewline := strings.IndexByte(s, '\n')
	if firstNewline == -1 {
		return s
	}
	rest := strings.TrimSpace(s[firstNewline+1:])
	if !strings.HasSuffix(rest, "```") {
		return s
	}
	return strings.TrimSpace(rest[:len(rest)-3])
}

func sanitizeSectionContent(c SectionContent) SectionContent {
	raw := stripCodeFence(c.Summary)
	c.Summary = raw
	for depth := 0; depth < 4; depth++ {
		s := strings.TrimSpace(c.Summary)
		if s == "" || !strings.HasPrefix(s, "{") {
			break
		}
		inner, ok := decodeNestedSection(s)
		if !ok {
			// The nested shape failed to parse even after bracket repair:
			// salvage the plain-prose lead sentence from the raw JSON text so
			// it still renders instead of leaking the JSON blob into the UI.
			c.Summary = recoverPlainSummary(s)
			break
		}
		c.Summary = inner.Summary
		if inner.Items != nil {
			c.Items = inner.Items
		}
	}
	if strings.TrimSpace(c.Summary) == "" {
		c.Summary = recoverPlainSummary(raw)
	}
	return c
}

func decodeNestedSection(s string) (SectionContent, bool) {
	var inner SectionContent
	if err := json.Unmarshal([]byte(s), &inner); err == nil {
		return inner, true
	}
	repaired, ok := repairUnclosedJSON(s)
	if !ok {
		return SectionContent{}, false
	}
	if err := json.Unmarshal([]byte(repaired), &inner); err != nil {
		return SectionContent{}, false
	}
	return inner, true
}
