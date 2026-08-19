"""Read-only DynamoDB control-state + paper status probe (SAFE, no writes)."""
import datetime as dt
import boto3
from dotenv import load_dotenv
import os

load_dotenv()
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')

table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)


def _scan_all(**kwargs):
    """Paginated scan — a single table.scan() returns ONE page (<=1MB scanned).

    trading-data is ~2.3MB, so a bare scan silently drops rows that hash into
    page 2+ (e.g. ETHUSDT vs BTCUSDT POSITION# keys). Loop LastEvaluatedKey.
    """
    items = []
    lek = None
    while True:
        if lek:
            kwargs['ExclusiveStartKey'] = lek
        resp = table.scan(**kwargs)
        items.extend(resp.get('Items', []))
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
    return items


# 1. Control state
ctrl = table.get_item(Key={'pk': 'CONTROL', 'sk': 'system'}).get('Item') or {}
print("=== CONTROL/system ===")
print(ctrl if ctrl else "(missing -> bots HALT (fail-closed); set a state to trade)")

# 2. Open positions (POSITION#* with pos != 0)
print("\n=== OPEN POSITIONS (pos != 0) ===")
positions = _scan_all(
    FilterExpression='begins_with(pk, :p)',
    ExpressionAttributeValues={':p': 'POSITION#'},
)
open_pos = [p for p in positions if float(p.get('pos', 0)) != 0]
for p in open_pos:
    print(p)
if not open_pos:
    print("(none)")

# 3. Recent signals (last 20 SIGNAL#*)
print("\n=== RECENT SIGNALS (SIGNAL#*) ===")
sigs = _scan_all(
    FilterExpression='begins_with(pk, :p)',
    ExpressionAttributeValues={':p': 'SIGNAL#'},
)
sigs.sort(key=lambda x: str(x.get('ts', 0)), reverse=True)
for s in sigs[:20]:
    print(s)
print(f"(total signals: {len(sigs)})")

# 4. Today's run markers
today = dt.date.today().isoformat()
print(f"\n=== RUN markers (today={today}) ===")
run_rows = _scan_all(
    FilterExpression='begins_with(pk, :p) AND sk = :t',
    ExpressionAttributeValues={':p': 'RUN#', ':t': today},
)
for r in run_rows:
    print(r)
if not run_rows:
    print("(none yet today)")
