#!/usr/bin/env python3
"""Stage 6: attach the verdict + the live-measured Robinhood off-hours cost
evidence to research/overnight_24h_edge_results.json.

The off-hours cost numbers are READ from two files produced independently in this
repo (research/rh_book_cost.json = level-2 book walk for a $250 clip, and
research/overnight_cost_results.json = Robinhood 24_7 5-minute historicals by
session).  They are quoted, not re-derived, and labelled as such.
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
OUT_JSON = os.path.join(_ROOT, "research", "overnight_24h_edge_results.json")
BOOK = os.path.join(_ROOT, "research", "rh_book_cost.json")
SESS = os.path.join(_ROOT, "research", "overnight_cost_results.json")

res = json.load(open(OUT_JSON))
ext = {}

if os.path.exists(BOOK):
    d = json.load(open(BOOK))
    per_sess = {}
    for sess, names in d.items():
        rts = [v["roundtrip_bp"] for v in names.values()
               if isinstance(v, dict) and v.get("roundtrip_bp") is not None]
        qs = [v["quoted_spread_bp"] for v in names.values()
              if isinstance(v, dict) and v.get("quoted_spread_bp") is not None]
        if rts:
            per_sess[sess] = {
                "n_symbols": len(rts),
                "roundtrip_bp_median": round(st.median(rts), 1),
                "roundtrip_bp_mean": round(st.mean(rts), 1),
                "roundtrip_bp_min": round(min(rts), 1),
                "roundtrip_bp_max": round(max(rts), 1),
                "roundtrip_bp_pct_under_10": round(100 * sum(1 for r in rts if r < 10) / len(rts), 1),
                "quoted_spread_bp_median": round(st.median(qs), 1),
            }
    ext["rh_offhours_book_cost_250usd_clip"] = {
        "source_file": "research/rh_book_cost.json (produced independently in this repo)",
        "what": "level-2 book walk, cost of buying then selling a $250 clip, ROUND TRIP bp",
        "caveat": "premarket snapshots (~09:17/09:23 ET), not the 16:00-20:00 evening session; "
                  "a handful of names show broken/stale quotes (SIRI 745-885bp)",
        "by_session": per_sess,
    }

if os.path.exists(SESS):
    d = json.load(open(SESS))
    ovn = [r["sessions"]["overnight"]["vol_share_pct"] for r in d]
    post = [r["sessions"]["post"]["vol_share_pct"] for r in d]
    posthl = [r["sessions"]["post"]["hl_bp_mean"] for r in d
              if r["sessions"]["post"].get("hl_bp_mean") is not None]
    ext["rh_session_liquidity"] = {
        "source_file": "research/overnight_cost_results.json (produced independently in this repo)",
        "what": "Robinhood get_equity_historicals bounds=24_7, 5-minute bars, 2026-08-10..2026-08-25",
        "n_symbols": len(d),
        "overnight_2000_0400_vol_share_pct_median": round(st.median(ovn), 4),
        "overnight_2000_0400_vol_share_pct_max": round(max(ovn), 4),
        "post_1600_2000_vol_share_pct_median": round(st.median(post), 3),
        "post_1600_2000_hl_range_bp_median": round(st.median(posthl), 1),
        "finding": "the true overnight window (20:00-04:00 ET) printed ZERO volume for all "
                   "36 sampled names over two weeks; the 16:00-20:00 evening session carries a "
                   "median 0.73% of the day's volume",
    }

res["external_cost_evidence"] = ext

walls = res["cost_walls"]["by_variant"]
best = max(walls.items(), key=lambda kv: kv[1]["wall_pf13_oos_excl_covid_bp"])
res["verdict"] = {
    "decision": "NO-GO",
    "one_line": "The close-to-next-open gap is real and stable but is only +5 to +15bp gross; "
                "no variant holds PF>=1.3 OOS above a ~6bp round-trip cost, and a real "
                "Robinhood off-hours round trip on a $250 clip costs ~45bp (median), "
                "with a hard 1-tick floor of ~4.7bp on the sub-$50 universe.",
    "best_variant_by_cost_wall_excl_covid": {
        "name": best[0], **best[1]},
    "max_wall_bp_any_variant_excl_covid": res["cost_walls"]["best_wall_bp"],
    "cost_wall_that_kills_it_bp": {
        "pf13_wall_best_case": res["cost_walls"]["best_wall_bp"],
        "physical_1_tick_floor_smallcap_bp": res["universe"]["smallcap_median_tick1_bp"],
        "measured_rh_offhours_roundtrip_median_bp":
            ext.get("rh_offhours_book_cost_250usd_clip", {})
               .get("by_session", {}).get("premarket_0917", {}).get("roundtrip_bp_median"),
        "required_flat_cost_stress_results": "at flat 10bp round trip every broad variant is "
                                             "negative or PF<1.05 OOS; at 20/30/40bp all are negative",
    },
    "entry_switch_answer": "NO — moving the deployed RSI(2) dip entry from the next open into "
                           "the evening session is worth +4.1bp (small caps, t=1.97) / +12.0bp "
                           "(large caps, t=6.55) OOS gross. The small-cap number is below the "
                           "1-tick floor (4.7bp) let alone the ~22bp extra off-hours half-spread, "
                           "so the switch is value-destroying on exactly the names a $700 "
                           "whole-share account trades.",
}
json.dump(res, open(OUT_JSON, "w"), indent=2, default=str)
print(json.dumps(res["verdict"], indent=2))
print(json.dumps(ext, indent=2)[:2000])
