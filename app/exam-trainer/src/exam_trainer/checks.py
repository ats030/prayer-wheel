"""Machine checks on a question's shape. No LLM involved.

These run before any model is asked to verify anything: everything caught here
is caught deterministically, in microseconds, and a model asked to judge a
malformed question tends to answer about its content instead of its form.

The length rule exists because a generated set where the correct choice is
consistently the longest is answerable without knowing the subject — the item
then measures test-taking skill, not knowledge.
"""

from __future__ import annotations

# A distractor that merely restates the answer in other words is not caught
# here (that needs meaning); this is the crude structural pass.
MIN_CHOICES = 3
MAX_CHOICES = 6
# Ratio of the correct choice's length to the mean of the others. Japanese
# definitional answers are legitimately wordier than their distractors ("原理が
# 分かると知能と見なされない" against "人間を超える時点"), so 1.6 fired on ordinary
# questions; 2.0 still catches the "right answer is the long hedged one" tell.
LENGTH_RATIO_LIMIT = 2.0
# Below this, the ratio stops meaning anything: among 3-5 character choices a
# single extra word doubles the length.
MIN_MEAN_LENGTH_FOR_RATIO = 12

# Options that make the item about exam technique rather than the subject.
BANNED_CHOICE_PATTERNS = (
    "上記すべて", "すべて正しい", "いずれも正しい", "上記のいずれでもない",
    "該当なし", "すべて誤り", "いずれも誤り", "全て正しい", "全て誤り",
)


def check(stem: str, choices: list[str], answer: int) -> list[str]:
    """Return a list of problems; empty means the shape is acceptable."""
    problems: list[str] = []
    stem = (stem or "").strip()
    cleaned = [(choice or "").strip() for choice in (choices or [])]

    if len(stem) < 10:
        problems.append("問題文が短すぎます")
    if not (MIN_CHOICES <= len(cleaned) <= MAX_CHOICES):
        problems.append(f"選択肢は{MIN_CHOICES}〜{MAX_CHOICES}個にしてください")
    if any(not choice for choice in cleaned):
        problems.append("空の選択肢があります")
    if len(set(cleaned)) != len(cleaned):
        problems.append("選択肢が重複しています")
    if not isinstance(answer, int) or not (0 <= answer < len(cleaned)):
        problems.append("正解の指定が選択肢の範囲外です")
        return problems

    for banned in BANNED_CHOICE_PATTERNS:
        if any(banned in choice for choice in cleaned):
            problems.append(f"「{banned}」型の選択肢は使いません")
            break

    others = [len(choice) for index, choice in enumerate(cleaned) if index != answer]
    if others and cleaned[answer]:
        mean_other = sum(others) / len(others)
        if (
            mean_other >= MIN_MEAN_LENGTH_FOR_RATIO
            and len(cleaned[answer]) / mean_other >= LENGTH_RATIO_LIMIT
        ):
            problems.append("正解の選択肢だけが長く、内容を知らなくても当てられます")

    return problems
