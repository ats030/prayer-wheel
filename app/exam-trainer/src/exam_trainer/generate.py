"""Generating questions from collected passages, and verifying them.

The pipeline is deliberately paranoid, in this order:

    passage -> generate -> machine checks -> grounding -> duplicate -> verify

Everything cheap and deterministic runs before anything expensive and
probabilistic. A question only reaches `verified` if a second model pass, shown
the passage but not the proposed answer, picks the same option.

The verifier is a separate call rather than "check your own work" in the same
prompt: a model asked to re-read its own answer in one turn agrees with itself
almost always, which is not a check.
"""

from __future__ import annotations

import logging
import math
import re
import time

from . import bank, checks, ollama_client
from .config import settings

logger = logging.getLogger(__name__)

# Two questions whose stems are this similar are treated as the same item.
# Chosen empirically: paraphrases of one definition land around 0.95, while
# genuinely different questions about the same term sit near 0.75.
DUPLICATE_THRESHOLD = 0.92

# Ollama call failures here used to be retried on the very next passage or
# candidate with no delay, hammering the shared generation gate at the same
# cadence as its own queue timeout whenever another app held it. This floor
# keeps a failed batch run from adding to that storm (ats030 usage-log
# investigation, 2026-09).
_OLLAMA_BACKOFF_SECONDS = 5.0

# A generated question must reuse this much of its own quoted evidence from the
# passage, otherwise the "evidence" was invented.
EVIDENCE_MIN_CHARS = 20

_GENERATE_SYSTEM = (
    "あなたは資格試験の作問者です。渡された抜粋だけを根拠に、多肢選択問題を作ります。"
    "抜粋に書かれていないことは絶対に問いません。"
    "正解は抜粋の記述から一意に決まるものだけにします。"
    "誤答の選択肢はもっともらしく、しかし抜粋に照らして明確に誤りであるものにします。"
    "『上記すべて』『該当なし』の形式は使いません。"
    "正解の選択肢だけを長くしません。"
    # Without this the model writes "抜粋における〜" stems, which are unanswerable
    # for someone who cannot see the passage.
    "解答者は抜粋を読めないので、問題文で抜粋・本文・この文章に言及してはいけません。"
    "抜粋を読んでいなくても意味が通る、独立した問題文にします。"
    "出力はJSONのみです。"
)

_VERIFY_SYSTEM = (
    "あなたは資格試験の校閲者です。抜粋と問題を読み、"
    "抜粋だけを根拠に正解を1つ選びます。"
    "抜粋から一意に決まらない場合や、複数の選択肢が正解になりうる場合は "
    "answer を -1 にして理由を書きます。"
    # The proofreading pass rides along on the call that was happening anyway.
    # Observed failure: a distractor came back as 「初めて見る問題を解いたもつ
    # ときの、間違えた割合」— visibly broken Japanese, which tells the reader
    # "this one is the wrong answer" without them knowing the subject.
    "あわせて、誤字・脱字・助詞の誤りなど日本語として壊れている選択肢があれば、"
    "その添字を flawed に入れます。表現の好みではなく、明らかな誤りだけを挙げます。"
    "出力はJSONのみです。"
)


def _generate_prompt(node_title: str, keywords: str, passage: str, count: int) -> str:
    hint = f"（キーワード: {keywords}）" if keywords else ""
    return (
        f"シラバス項目「{node_title}」{hint}の練習問題を、次の抜粋だけを根拠に"
        f"最大{count}問作ってください。\n\n"
        f"抜粋:\n---\n{passage}\n---\n\n"
        '出力形式: {"questions": [{"stem": "問題文", "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"], '
        '"answer": 0, "explanation": "なぜその選択肢が正解か", "evidence": "根拠になった抜粋中の文をそのまま引用"}]}\n'
        "answer は choices の 0 始まりの添字です。"
        "evidence は抜粋から一字一句そのまま写してください。"
        "stem は抜粋を読んでいない人にも通じる独立した問題文にしてください"
        "（「抜粋における」「本文中の」などで始めない）。"
        "抜粋の情報が薄く良い問題が作れない場合は questions を空配列にしてください。"
    )


def _verify_prompt(
    passage: str,
    stem: str,
    choices: list[str],
    node_title: str = "",
    keywords: str = "",
) -> str:
    listed = "\n".join(f"{index}: {choice}" for index, choice in enumerate(choices))
    scope = ""
    if node_title:
        hint = f"（キーワード: {keywords}）" if keywords else ""
        scope = (
            f"出題範囲: {node_title}{hint}\n"
            "問題がこの出題範囲の知識を直接問うなら in_scope を true、"
            "記事中の周辺的な逸話や範囲外の知識を問うなら false にしてください。\n\n"
        )
    return (
        scope
        + f"抜粋:\n---\n{passage}\n---\n\n"
        f"問題: {stem}\n選択肢:\n{listed}\n\n"
        '出力形式: {"answer": 0, "reason": "根拠になった抜粋の記述", '
        '"unique": true, "in_scope": true, "scope_reason": "出題範囲との関係", "flawed": []}\n'
        "unique は、抜粋から正解が一意に決まるなら true、決まらないなら false です。\n"
        "flawed は日本語として壊れている選択肢の添字の配列です（なければ空配列）。"
    )


def _normalise(text: str) -> str:
    """Strip punctuation and spacing so quoting differences don't defeat matching."""
    return re.sub(r"[\s、。「」『』（）()･・,.:：;；]", "", text or "")


def grounded(evidence: str, passage: str) -> bool:
    """Is the quoted evidence actually in the passage?

    Models paraphrase when asked to quote, so this is a containment test on
    normalised text rather than equality. A short fragment can match by accident,
    hence the length floor.
    """
    normalised_evidence = _normalise(evidence)
    if len(normalised_evidence) < EVIDENCE_MIN_CHARS:
        return False
    return normalised_evidence in _normalise(passage)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def is_duplicate(stem: str, existing_stems: list[str], embed=None) -> bool:
    """Reject a stem that restates one already in the bank.

    Falls back to exact-match on normalised text when embeddings are
    unavailable, so a broken embedding model degrades the check instead of
    disabling generation.
    """
    normalised = _normalise(stem)
    if any(_normalise(other) == normalised for other in existing_stems):
        return True
    if not existing_stems:
        return False
    embed = embed or ollama_client.embed
    try:
        vector = embed(stem)
        for other in existing_stems:
            if cosine(vector, embed(other)) >= DUPLICATE_THRESHOLD:
                return True
    except Exception as exc:  # embeddings are an optimisation, never a blocker
        logger.warning("duplicate check degraded to exact match: %s", exc)
        time.sleep(_OLLAMA_BACKOFF_SECONDS)
    return False


def verify(
    passage: str,
    stem: str,
    choices: list[str],
    answer: int,
    model: str = "",
    node_title: str = "",
    keywords: str = "",
) -> tuple[bool, str]:
    """Second opinion on a question. Returns (agrees, reason-when-not)."""
    try:
        data = ollama_client.generate_json(
            _verify_prompt(passage, stem, choices, node_title, keywords),
            system=_VERIFY_SYSTEM,
            model=model or settings.model,
        )
    except ollama_client.OllamaError as exc:
        time.sleep(_OLLAMA_BACKOFF_SECONDS)
        return False, f"検証を実行できませんでした: {exc}"
    if not isinstance(data, dict):
        return False, "検証の応答を解釈できませんでした"
    if node_title and data.get("in_scope") is not True:
        reason = str(data.get("scope_reason", "")).strip()
        return False, f"シラバスの出題範囲に適合しません: {reason}".rstrip()
    if data.get("unique") is not True:
        # 厳密に真 boolean のみ採用：欠落や "false"/"true" 等の文字列は判断不能として棄却。
        reason = str(data.get("reason", "")).strip()
        return False, f"抜粋から正解が一意に決まりません: {reason}".rstrip()
    try:
        verified_answer = int(data.get("answer", -1))
    except (TypeError, ValueError):
        return False, "検証の応答に正解が含まれていませんでした"
    if verified_answer < 0:
        return False, f"検証側が正解を決められませんでした: {data.get('reason', '')}".strip()
    if verified_answer != answer:
        return False, (
            f"検証側は {chr(65 + verified_answer)} を正解と判断しました"
            f"（作問側は {chr(65 + answer)}）: {data.get('reason', '')}"
        ).strip()
    flawed = _flawed_labels(data.get("flawed"), len(choices))
    if flawed:
        # Not a wrong answer, so it is held rather than dropped: the fix is
        # usually a one-character edit a human can make faster than a rerun.
        return False, f"選択肢 {'・'.join(flawed)} の日本語が壊れています"
    return True, ""


def _flawed_labels(raw, choice_count: int) -> list[str]:
    """Turn the verifier's `flawed` indices into A/B/C labels, ignoring junk."""
    if not isinstance(raw, list):
        return []
    labels = []
    for value in raw:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < choice_count:
            labels.append(chr(65 + index))
    return sorted(set(labels))


def questions_from_passage(
    node_title: str,
    keywords: str,
    passage: str,
    count: int = 3,
    model: str = "",
) -> list[dict]:
    """Ask the model for questions grounded in one passage. No checks yet."""
    data = ollama_client.generate_json(
        _generate_prompt(node_title, keywords, passage, count),
        system=_GENERATE_SYSTEM,
        model=model or settings.model,
    )
    items = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        choices = [str(choice).strip() for choice in item.get("choices", []) if str(choice).strip()]
        try:
            answer = int(item.get("answer", -1))
        except (TypeError, ValueError):
            continue
        results.append({
            "stem": str(item.get("stem", "")).strip(),
            "choices": choices,
            "answer": answer,
            "explanation": str(item.get("explanation", "")).strip(),
            "evidence": str(item.get("evidence", "")).strip(),
        })
    return results


def screen(candidate: dict, passage: str, existing_stems: list[str], embed=None) -> tuple[str, str]:
    """Run the cheap gates. Returns (verdict, reason).

    verdict is "ok" (proceed to verification), "drop" (never store it), or
    "hold" (store for a human to look at).
    """
    problems = checks.check(candidate["stem"], candidate["choices"], candidate["answer"])
    if problems:
        return "drop", " / ".join(problems)
    if not grounded(candidate["evidence"], passage):
        # The model invented a quote. That is exactly the failure this app
        # exists to prevent, so the item is dropped rather than held.
        return "drop", "根拠として引用された文が抜粋に見つかりません"
    if is_duplicate(candidate["stem"], existing_stems, embed=embed):
        return "drop", "既存の問題と重複しています"
    return "ok", ""


def generate_for_node(
    exam_id: int,
    node_path: str,
    target: int = 5,
    model: str = "",
    progress=None,
) -> dict:
    """Collect material for one syllabus node and fill the bank from it.

    Returns a summary the job layer can show. Nothing here raises on a single
    bad candidate: one unusable passage should not abandon the run.
    """
    from . import materials, web

    def report(text: str) -> None:
        if progress:
            progress(text)
        logger.info("[%s] %s", node_path, text)

    node = next(
        (item for item in bank.list_syllabus(exam_id) if item["path"] == node_path),
        None,
    )
    if node is None:
        raise LookupError(f"シラバス項目が見つかりません: {node_path}")

    exam = bank.get_exam(exam_id)
    summary = {"verified": 0, "held": 0, "dropped": 0, "materials": 0, "reasons": []}

    report("素材を集めています…")
    collected = materials.ensure(exam_id, node, exam["name"])
    summary["materials"] = len(collected)
    if not collected:
        # "the topic has no pages" and "search is throttled right now" need
        # opposite responses, so never merge them into one message.
        summary["reasons"].append(
            web.last_search_note()
            or "素材を取得できませんでした（項目名とキーワードで記事が見つかりません）"
        )
        return summary

    existing = [item["stem"] for item in bank.list_questions(exam_id, limit=500)]

    # Visit the first passage of every source before the second passage of any
    # source. A source-by-source scan fills the target from whichever row sorts
    # first, even when several independent sources were collected.
    pending = [
        (material, iter(web.passages(material["text"])))
        for material in collected
    ]
    while pending:
        next_round = []
        for material, passages in pending:
            try:
                passage = next(passages)
            except StopIteration:
                continue
            next_round.append((material, passages))
            if summary["verified"] >= target:
                report(f"目標の{target}問に到達しました")
                return summary
            try:
                candidates = questions_from_passage(
                    node["title"], node["keywords"], passage, model=model
                )
            except ollama_client.OllamaError as exc:
                summary["reasons"].append(f"生成に失敗: {exc}")
                time.sleep(_OLLAMA_BACKOFF_SECONDS)
                continue

            for candidate in candidates:
                if summary["verified"] >= target:
                    report(f"目標の{target}問に到達しました")
                    return summary
                verdict, reason = screen(candidate, passage, existing)
                if verdict == "drop":
                    summary["dropped"] += 1
                    summary["reasons"].append(reason)
                    continue

                agrees, disagreement = verify(
                    passage, candidate["stem"], candidate["choices"], candidate["answer"],
                    model=model, node_title=node["title"], keywords=node["keywords"],
                )
                status = "verified" if agrees else "held"
                if settings.web_search_url and material.get("provenance", {}).get("terms", {}).get("status") not in {"approved", "conditional"}:
                    status = "held"
                    disagreement = (disagreement + " / " if disagreement else "") + "公開前に情報源の利用条件を確認してください"
                bank.add_question(
                    exam_id, node_path, candidate["stem"], candidate["choices"],
                    candidate["answer"],
                    explanation=candidate["explanation"],
                    evidence=candidate["evidence"],
                    source_refs=[material["url"]],
                    status=status,
                    origin="generated",
                    hold_reason=disagreement,
                    source_details=[{"url": material["url"], "fetched_at": material.get("fetched_at", ""),
                                     **material.get("provenance", {})}],
                )
                existing.append(candidate["stem"])
                summary["verified" if status == "verified" else "held"] += 1
                report(
                    f"採用 {summary['verified']} / 要確認 {summary['held']} / 破棄 {summary['dropped']}"
                )
        pending = next_round
    return summary
