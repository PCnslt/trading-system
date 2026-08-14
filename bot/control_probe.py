"""Read-only DynamoDB control-state + paper status probe (SAFE, no writes)."""
import datetime as dt
import boto3
from dotenv import load_dotenv
import os

load_dotenv()
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')

table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)

# 1. Control state
ctrl = table.get_item(Key={'pk': 'CONTROL', 'sk': 'system'}).get('Item') or {}
print("=== CONTROL/system ===")
print(ctrl if ctrl else "(missing -> bots HALT (fail-closed); set a state to trade)")

# 2. Open positions (POSITION#* with pos != 0)
print("\n=== OPEN POSITIONS (pos != 0) ===")
resp = table.scan(
    FilterExpression='begins_with(pk, :p)',
    ExpressionAttributeValues={':p': 'POSITION#'},
)
positions = resp.get('Items', [])
open_pos = [p for p in positions if float(p.get('pos', 0)) != 0]
for p in open_pos:
    print(p)
if not open_pos:
    print("(none)")

# 3. Recent signals (last 20 SIGNAL#*)
print("\n=== RECENT SIGNALS (SIGNAL#*) ===")
resp = table.scan(
    FilterExpression='begins_with(pk, :p)',
    ExpressionAttributeValues={':p': 'SIGNAL#'},
)
sigs = resp.get('Items', [])
sigs.sort(key=lambda x: str(x.get('ts', 0)), reverse=True)
for s in sigs[:20]:
    print(s)
print(f"(total signals: {len(sigs)})")

# 4. Today's run markers
today = dt.date.today().isoformat()
print(f"\n=== RUN markers (today={today}) ===")
resp = table.scan(
    FilterExpression='begins_with(pk, :p) AND sk = :t',
    ExpressionAttributeValues={':p': 'RUN#', ':t': today},
)
for r in resp.get('Items', []):
    print(r)
if not resp.get('Items'):
    print("(none yet today)")
