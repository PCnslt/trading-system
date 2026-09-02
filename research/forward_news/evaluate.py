"""Forward news — prediction generator (simple hypotheses) + evaluation framework.

Predictions are generated at observed_at (info boundary) and stored immutably
BEFORE outcomes exist. Outcomes are resolved later and appended separately —
never modifying the original prediction.
"""
import json, boto3
from datetime import datetime, timezone

B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')

# Simple pre-registered hypotheses (velocity x reaction sign). NOT optimized.
HYPOTHESES = {
    'H1_velocity_continuation': 'high news velocity -> same-direction continuation',
    'H2_velocity_reversal':      'high news velocity -> reversal',
    'H3_neg_reaction_hi_vel_cont': 'large negative reaction + high velocity -> continuation',
    'H4_neg_reaction_lo_vel_rev':  'large negative reaction + low velocity -> reversal',
    'H5_pos_reaction_hi_vel_cont': 'large positive reaction + high velocity -> continuation',
    'H6_pos_reaction_lo_vel_rev':  'large positive reaction + low velocity -> reversal',
}

def generate_predictions(events):
    """Attach a naive prediction to each event (velocity proxy: event has no velocity yet at single-observation time, so flag as pending)."""
    out = []
    for e in events:
        out.append(dict(
            signal_id=e['event_id'] + '_pred',
            timestamp=e['observed_at_utc'],
            symbol=e['symbol'],
            direction=None,          # filled by a market-state-aware step once price is joined
            predicted_edge=None,
            confidence='LOW',
            model_version='forward-v0',
            reason='pending_price_join',
        ))
    return out

def resolve_outcomes(predictions):
    """Append a resolved-outcome skeleton (realized returns filled by a later price-join step)."""
    for p in predictions:
        p.update(dict(realized_return_5m=None, realized_return_15m=None,
                      realized_return_30m=None, realized_return_60m=None,
                      max_favorable_excursion=None, max_adverse_excursion=None,
                      outcome_timestamp=None, status='UNRESOLVED'))
    return predictions

def evaluation_summary(events_key='news/events/events.jsonl', pred_key='news/predictions/predictions.jsonl'):
    """Report accumulated forward observation counts (genuine, no backfill)."""
    def _load(key):
        try:
            body = s3.get_object(Bucket=B, Key=key)['Body'].read().decode()
            return [json.loads(l) for l in body.splitlines() if l.strip()]
        except s3.exceptions.NoSuchKey:
            return []
    ev = _load(events_key); pr = _load(pred_key)
    syms = sorted({e['symbol'] for e in ev})
    days = sorted({e['observed_at_utc'][:10] for e in ev})
    return dict(events=len(ev), unique_symbols=len(syms), unique_days=len(days),
                predictions=len(pr), resolved=sum(1 for p in pr if p.get('status')=='RESOLVED'))

if __name__ == '__main__':
    print(json.dumps(evaluation_summary(), indent=2))
