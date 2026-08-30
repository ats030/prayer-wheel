import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_STOPWORDS_JA = {
    "について", "から", "まで", "という", "として", "ため", "こと", "もの",
    "これ", "それ", "あの", "この", "その", "など", "また", "さらに",
}
_STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "will", "would", "can",
    "could", "should", "may", "might", "that", "this", "it", "its",
    "how", "what", "when", "where", "who", "why", "not", "no",
    "new", "top", "best", "first", "last", "more", "most", "just",
    "really", "fast", "end", "big", "good", "bad", "old", "long", "way",
    "get", "got", "let", "put", "set", "run", "use", "make", "take",
    "part", "back", "well", "over", "one", "two", "time", "year",
    "revenge", "waterfall", "era", "death",
}

_FEW_SHOT = """\
以下はフィードのタイトル群からタグを生成した例です。

【例1】
フィード名: Rebuild
タイトル群:
- 424: Waterfall But Really Fast
- 423: The End of the Smartphone Era
- 422: AI Agents in Production
- 421: Revenge of the Developers
タグ: ソフトウェア開発, AI, 英語, ポッドキャスト, テック

【例2】
フィード名: Simon Willison's Weblog
タイトル群:
- Notes on Claude's extended thinking
- Running LLMs locally with Ollama
- Python packaging in 2024
- Datasette 1.0 alpha released
タグ: LLM/AI, Python, OSS, 英語ブログ, データ

【例3】
フィード名: NHKニュース
タイトル群:
- 円安進む 1ドル155円台に
- 能登半島地震 復興状況
- 少子化対策 政府が新方針
- 春闘 大手企業の賃上げ結果
タグ: ニュース, 日本, 政治経済, 社会

"""

_INSTRUCTION = """\
上記の例を参考に、以下のフィードにタグを3〜5個付けてください。

ルール:
- カンマ区切りで1行に出力（例: AI, Python, 英語ブログ, 技術）
- 1タグは1〜4単語
- ジャンル・技術領域・言語・フォーマット（ブログ/ポッドキャスト/ニュース等）を組み合わせる
- タグのみ出力し、説明・番号・記号は不要

フィード名: {title}{meta_lines}
タイトル群:
{titles}

タグ:"""


def generate_tags(
    feed_title: str,
    item_titles: list[str],
    description: str = "",
    media_type: str = "",
    authors: list[str] | None = None,
) -> list[str]:
    authors = authors or []
    tags = _ollama_tags(feed_title, item_titles, description, media_type, authors)
    if tags:
        return tags
    return _keyword_tags(feed_title, item_titles, description, media_type)


def _build_prompt(
    feed_title: str,
    item_titles: list[str],
    description: str,
    media_type: str,
    authors: list[str],
) -> str:
    titles_text = "\n".join(f"- {t}" for t in item_titles[:20])
    if not titles_text and description:
        titles_text = f"（タイトル不明）説明: {description[:200]}"

    meta_parts: list[str] = []
    if media_type:
        meta_parts.append(f"メディアタイプ: {media_type}")
    if authors:
        meta_parts.append(f"著者/パーソナリティ: {', '.join(authors)}")
    if description:
        meta_parts.append(f"説明: {description[:150]}")
    meta_lines = ("\n" + "\n".join(meta_parts)) if meta_parts else ""

    return _FEW_SHOT + _INSTRUCTION.format(title=feed_title, meta_lines=meta_lines, titles=titles_text)


def _parse_response(text: str) -> list[str]:
    text = text.strip()

    # JSON配列形式: ["tag1", "tag2"]
    m = re.search(r'\[([^\]]+)\]', text)
    if m:
        try:
            tags = json.loads(f"[{m.group(1)}]")
            if isinstance(tags, list):
                return [str(t).strip() for t in tags if t][:5]
        except Exception:
            pass

    # 番号付きリスト / 箇条書き: 最初の行群から抽出
    lines = [re.sub(r'^[\d\-\*\.\)]+\s*', '', l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l and len(l) <= 30]
    if len(lines) >= 2:
        # 1行に複数カンマがある → カンマ分割を優先
        if ',' in lines[0]:
            pass  # fall through to comma split
        else:
            return lines[:5]

    # カンマ区切り（最も一般的）
    tags = [t.strip().lstrip('#').strip() for t in text.split(',')]
    return [t for t in tags if t and len(t) <= 30][:5]


def _get_models() -> list[str]:
    tag_model = os.environ.get("OLLAMA_TAG_MODEL", "").strip()
    models_str = os.environ.get("OLLAMA_MODELS", "")
    models = [m.strip() for m in models_str.split(",") if m.strip()]
    if tag_model:
        models = [tag_model] + [m for m in models if m != tag_model]
    return models[:3]


def _ollama_tags(
    feed_title: str,
    item_titles: list[str],
    description: str,
    media_type: str = "",
    authors: list[str] | None = None,
) -> list[str]:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    prompt = _build_prompt(feed_title, item_titles, description, media_type, authors or [])

    for model in _get_models():
        try:
            import httpx

            resp = httpx.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=httpx.Timeout(connect=5, read=30, write=5, pool=5),
            )
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            tags = _parse_response(text)
            if tags:
                return tags
        except Exception as exc:
            # 上流の 5xx を黙って捨てると、キーワード抽出へ降格したことに気付けない
            # (ats030-bnrg)。降格自体は仕様どおりなので継続はする。
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning("tagger: %s failed (%s)", model, status or exc)
            continue

    return []


def _keyword_tags(
    feed_title: str,
    item_titles: list[str],
    description: str,
    media_type: str = "",
) -> list[str]:
    all_text = feed_title + " " + " ".join(item_titles[:15]) + " " + description[:200]

    # 技術スタック名（ドット・スラッシュ含む複合語を優先）
    tech = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:[.\-/][A-Za-z][A-Za-z0-9]+)+", all_text)

    # 大文字始まり固有名詞
    proper = [w for w in re.findall(r"[A-Z][a-zA-Z]{2,}", all_text)
              if w.lower() not in _STOPWORDS_EN]

    # 日本語：漢字は2〜4字（5字以上は動詞語幹まで含む可能性が高い）、カタカナ3字以上
    ja_kanji = re.findall(r"[一-龠々]{2,4}", all_text)
    ja_kata = re.findall(r"[ァ-ヶー]{3,}", all_text)
    ja_tags = [w for w in ja_kanji + ja_kata if w not in _STOPWORDS_JA]

    # classifier で判定済みのメディアタイプを優先利用、未提供時は推定
    if media_type:
        format_tags = [media_type]
    else:
        format_tags = []
        if any(re.search(r"^\d+[:：]", t) for t in item_titles[:5]):
            format_tags.append("ポッドキャスト")
        if any(k in feed_title for k in ("ニュース", "News", "news", "速報")):
            format_tags.append("ニュース")
        elif any(k in feed_title.lower() for k in ("blog", "zenn", "qiita", "ブログ")):
            format_tags.append("ブログ")

    # ひらがなが少ないタイトルが多数 → 英語コンテンツと判定
    ja_title_count = sum(1 for t in item_titles[:10] if re.search(r"[ぁ-ん]", t))
    if ja_title_count < len(item_titles[:10]) * 0.4:
        format_tags.append("英語")

    # フォーマットタグを先頭に置いて優先度を上げる
    combined = format_tags + tech + proper + ja_tags
    seen: set[str] = set()
    result = []
    for t in combined:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
        if len(result) >= 5:
            break
    return result
