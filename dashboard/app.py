"""Trading system dashboard — read-only cockpit + 3 safe controls.

Reads live data from DynamoDB. Controls write flags to DynamoDB that the
bot reads. No arbitrary order entry here.
"""
import os
import datetime as dt

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)

CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
EQUITIES = ["AAPL", "MSFT", "SPY", "MCD"]

st.set_page_config(page_title="Trading System", page_icon="📈", layout="wide")


@st.cache_data(ttl=15)
def latest(pk, limit=1):
    """Latest record for a partition key (sorted desc by sk)."""
    r = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=limit)
    return r.get("Items", [])


@st.cache_data(ttl=15)
def get_control():
    r = table.get_item(Key={"pk": "CONTROL", "sk": "system"})
    return r.get("Item", {})


def set_control(**fields):
    item = {"pk": "CONTROL", "sk": "system", "ts": int(dt.datetime.now(dt.UTC).timestamp())}
    item.update(fields)
    table.put_item(Item=item)
    st.cache_data.clear()


st.title("📈 Trading System")

# --- Control state banner ---
ctrl = get_control()
state = ctrl.get("state", "RUNNING")
if state == "PAUSED":
    st.warning("⚠️ Bot is PAUSED")
elif state == "KILLED":
    st.error("🛑 Bot is KILLED — all trading halted")
else:
    st.success("✅ Bot is RUNNING")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Crypto prices", value="")
    for sym in CRYPTO:
        rows = latest(f"QUOTE#{sym}", 1)
        if rows:
            st.metric(sym, f"${float(rows[0]['price']):,.2f}")
with col2:
    st.metric("Equities — latest close", value="")
    for sym in EQUITIES:
        rows = latest(f"OHLCV#{sym}", 1)
        if rows:
            c = float(rows[0]["close"])
            st.metric(sym, f"${c:,.2f}")
with col3:
    st.subheader("Data health")
    st.write(f"Last checked: {dt.datetime.now(dt.UTC).strftime('%H:%M:%S UTC')}")
    st.write("DynamoDB table: `trading-data`")
    st.write("S3 bucket: `trading-datalake-920641308584`")

# --- Controls ---
st.divider()
st.subheader("🕹️ Controls")
st.caption("Safe controls only — no order entry here. These set flags the bot reads.")
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("⏸️ Pause bot", use_container_width=True):
        set_control(state="PAUSED")
        st.rerun()
with c2:
    if st.button("🧹 Flatten positions", use_container_width=True):
        set_control(flatten="true")
        st.rerun()
with c3:
    if st.button("🛑 KILL SWITCH", type="primary", use_container_width=True):
        set_control(state="KILLED")
        st.rerun()

st.caption("Flatten/kill flags are read by the bot loop. They persist in DynamoDB until cleared.")
