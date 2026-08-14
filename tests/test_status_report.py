"""status_report _sk_time: robust TRADE sk/time parsing (ISO vs date#epoch)."""
import re

import pytest

import status_report
from status_report import _sk_time


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
