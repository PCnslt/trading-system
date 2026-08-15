"""status_report: TRADE sk/time parsing + ground-truth liveness/freshness re-key."""
import datetime as dt
import re

import pytest

import status_report
from status_report import _sk_time


# --- _sk_time: robust TRADE sk/time parsing (ISO vs date#epoch) ---
def test_sk_time_prefers_ts_epoch():
    out = _sk_time({'ts': 1755000000, 'sk': 'garbage'})
    assert re.match(r'^\d{2}:\d{2}:\d{2}$', out)


def test_sk_time_iso_slice():
    assert _sk_time({'sk': '2026-08-14T13:45:00.123456+00:00'}) == '13:45:00'


def test_sk_time_date_epoch():
    out = _sk_time({'sk': '2026-08-14#1755000000'})
    assert re.match(r'^\d{2}:\d{2}:\d{2}$', out)


def test_sk_time_missing():
    assert _sk_time({}) == '--:--:--'
    assert _sk_time({'sk': 'short'}) == '--:--:--'


# --- ground-truth re-key: flat session (fresh bars + no signal = healthy) ---

def _s3_double(date_str):
    """Fake S3 client returning one archived-bar object for `date_str`."""
    class S3:
        def __init__(self):
            self.calls = []

        def list_objects_v2(self, **kw):
            self.calls.append(kw)
            return {
                'Contents': [{'Key': f'futures-bars/intraday/MES/15min/{date_str}.json'}],
                'IsTruncated': False,
            }
    return S3()


def test_latest_intraday_bar_date_reads_key_date():
    assert status_report._latest_intraday_bar_date(client=_s3_double('2026-08-15')) == '2026-08-15'


def test_latest_intraday_bar_date_picks_max_date():
    class S3:
        def list_objects_v2(self, **kw):
            return {
                'Contents': [
                    {'Key': 'futures-bars/intraday/MES/5min/2026-08-13.json'},
                    {'Key': 'futures-bars/intraday/MES/15min/2026-08-14.json'},
                    {'Key': 'futures-bars/intraday/MES/15min/2026-08-12.json'},
                ],
                'IsTruncated': False,
            }
    assert status_report._latest_intraday_bar_date(client=S3()) == '2026-08-14'


def test_latest_intraday_bar_date_empty_is_none():
    class EmptyS3:
        def list_objects_v2(self, **kw):
            return {'Contents': [], 'IsTruncated': False}
    assert status_report._latest_intraday_bar_date(client=EmptyS3()) is None


def test_intraday_bars_status_fresh_is_ok():
    assert status_report._intraday_bars_status('2026-08-15', '2026-08-15') == ('ok', 'archived 2026-08-15')


def test_intraday_bars_status_weekend_is_ok_not_stale():
    # Sat 2026-08-15 with last archive Fri 2026-08-14 = market closed, NOT stale.
    st, note = status_report._intraday_bars_status('2026-08-14', '2026-08-15')
    assert st == 'ok'
    assert 'stale' not in note


def test_intraday_bars_status_old_is_stale():
    st, _ = status_report._intraday_bars_status('2026-08-01', '2026-08-15')
    assert st == 'stale'


def test_intraday_bars_status_missing_is_stale():
    st, _ = status_report._intraday_bars_status(None, '2026-08-15')
    assert st == 'stale'


def test_intraday_ran_today_from_bar_archive(fake_table):
    assert status_report._intraday_ran_today('2026-08-15', tbl=fake_table, latest_bar_date='2026-08-15') is True


def test_intraday_ran_today_from_run_marker(fake_table):
    fake_table.items[('RUN#live_intraday', '2026-08-15')] = {'pk': 'RUN#live_intraday', 'sk': '2026-08-15'}
    assert status_report._intraday_ran_today('2026-08-15', tbl=fake_table, latest_bar_date=None) is True


def test_intraday_ran_today_false_when_neither(fake_table):
    assert status_report._intraday_ran_today('2026-08-15', tbl=fake_table, latest_bar_date=None) is False


def test_flat_session_renders_healthy_not_stale(monkeypatch, fake_table):
    """Regression: fresh bars + no signal = healthy, NOT 'not run today' / 'stale'."""
    monkeypatch.setattr(status_report, 'table', fake_table)
    monkeypatch.setattr(status_report, '_latest_intraday_bar_date', lambda: '2026-08-15')
    monkeypatch.setattr(status_report, '_now_utc',
                        lambda: dt.datetime(2026, 8, 15, 23, 45, tzinfo=dt.timezone.utc))

    intra = '\n'.join(status_report.report_intraday())
    health = '\n'.join(status_report.report_health())

    assert 'bot ran today' in intra
    assert 'not run today' not in intra
    assert 'IBKR intraday bars: ok' in health
    assert 'IBKR intraday bars: stale' not in health


def test_no_archive_and_no_signal_renders_not_run(monkeypatch, fake_table):
    """Counter-case: no bar archive + no RUN# marker = genuinely 'not run'."""
    monkeypatch.setattr(status_report, 'table', fake_table)
    monkeypatch.setattr(status_report, '_latest_intraday_bar_date', lambda: None)
    monkeypatch.setattr(status_report, '_now_utc',
                        lambda: dt.datetime(2026, 8, 15, 23, 45, tzinfo=dt.timezone.utc))

    intra = '\n'.join(status_report.report_intraday())
    health = '\n'.join(status_report.report_health())

    assert 'no bar archive today' in intra
    assert 'IBKR intraday bars: stale' in health
