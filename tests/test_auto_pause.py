"""Auto-pause on sustained reconcile MISMATCH (GAP-1).

The reconcile daemon (bot/reconcile_daemon.py) flips CONTROL/system -> PAUSED
after MISMATCH_PAUSE_THRESHOLD consecutive 45s MISMATCH cycles, closing the
unprotected-position window between detection (~45s) and the next bot run
(up to 15min intraday / 24h daily).

Rules under test:
  * a single MISMATCH must NOT pause;
  * 2+ consecutive MISMATCHes MUST pause;
  * UNKNOWN (a transient gateway blip) must NEVER advance the streak or pause;
  * only a verified MATCH resets the streak.
"""
from reconcile_daemon import evaluate_auto_pause, MISMATCH_PAUSE_THRESHOLD


def test_threshold_is_two():
    assert MISMATCH_PAUSE_THRESHOLD == 2


def test_single_mismatch_does_not_pause():
    streak, pause = evaluate_auto_pause('MISMATCH', 0)
    assert streak == 1
    assert pause is False


def test_two_consecutive_mismatches_pause():
    streak, pause = evaluate_auto_pause('MISMATCH', MISMATCH_PAUSE_THRESHOLD - 1)
    assert streak == MISMATCH_PAUSE_THRESHOLD
    assert pause is True


def test_sustained_mismatch_keeps_pausing():
    # once past the threshold, every further MISMATCH cycle still says pause
    # (so the daemon keeps re-asserting PAUSED if a human resumes mid-mismatch).
    streak, pause = evaluate_auto_pause('MISMATCH', MISMATCH_PAUSE_THRESHOLD)
    assert streak == MISMATCH_PAUSE_THRESHOLD + 1
    assert pause is True


def test_unknown_never_advances_or_pauses():
    streak, pause = evaluate_auto_pause('UNKNOWN', 0)
    assert streak == 0 and pause is False

    # UNKNOWN is neutral: it neither advances NOR resets a building MISMATCH
    # streak (a gateway blip must not halt the system, and must not give a real
    # missing-stop a free pass).
    streak, pause = evaluate_auto_pause('UNKNOWN', 1)
    assert streak == 1 and pause is False


def test_match_resets_streak():
    streak, pause = evaluate_auto_pause('MATCH', 3)
    assert streak == 0 and pause is False
