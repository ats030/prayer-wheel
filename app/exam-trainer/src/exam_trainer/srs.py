"""Spaced repetition (SM-2).

Why SM-2 and not FSRS: FSRS schedules better, but it needs a fitted parameter
set per user and a review history to fit it against — neither exists on day one.
SM-2 needs nothing and is good enough to stop the "review everything every day"
failure. The review log stores what FSRS would need (timestamp, correctness,
elapsed time, grade), so the scheduler can be swapped later and replayed over
the existing history instead of restarting from zero.

Grades follow SM-2's 0-5 quality scale. The UI only produces four of them
(`grade_for`), because a self-report with six levels is noise: what the app can
observe is whether the answer was right and how long it took.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MIN_EASE = 1.3
# Anything below this counts as a lapse and restarts the interval.
PASS_GRADE = 3
# Answering correctly but slowly should not earn the same interval as answering
# instantly; 20s is roughly where a recalled answer turns into a worked-out one.
SLOW_ANSWER_MS = 20_000


@dataclass
class CardState:
    interval: int = 0     # days until the next review
    ease: float = 2.5
    reps: int = 0
    lapses: int = 0


def grade_for(correct: bool, elapsed_ms: int, unsure: bool = False) -> int:
    """Map what the UI can actually observe onto SM-2's quality scale."""
    if not correct:
        # 2 = wrong but the right answer felt familiar once shown; 1 = blank.
        return 1 if unsure else 2
    if unsure:
        return 3
    return 4 if elapsed_ms > SLOW_ANSWER_MS else 5


def schedule(state: CardState, grade: int, now: dt.datetime | None = None) -> tuple[CardState, dt.datetime]:
    """Return the next card state and when it is due.

    A failed card goes back to a 1-day interval rather than to the same day.
    Same-day re-asks feel productive but mostly measure short-term memory, and
    they crowd out cards that are genuinely due.
    """
    now = now or dt.datetime.now(dt.UTC)
    if grade < PASS_GRADE:
        next_state = CardState(
            interval=1,
            ease=max(MIN_EASE, state.ease - 0.20),
            reps=0,
            lapses=state.lapses + 1,
        )
        return next_state, now + dt.timedelta(days=1)

    if state.reps == 0:
        interval = 1
    elif state.reps == 1:
        interval = 6
    else:
        interval = max(1, round(state.interval * state.ease))

    ease = state.ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    next_state = CardState(
        interval=interval,
        ease=max(MIN_EASE, ease),
        reps=state.reps + 1,
        lapses=state.lapses,
    )
    return next_state, now + dt.timedelta(days=interval)
