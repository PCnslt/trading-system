#!/bin/bash
# mine.sh search "<query>" [num]   |   mine.sh fetch <url> [maxchars]
cd /home/ubuntu/trading-system
export SERPER_API_KEY=$(grep '^SERPER_API_KEY=' .env | cut -d= -f2)
case "$1" in
  search)
    N=${3:-8}
    ./venv/bin/python - "$2" "$N" <<'PY'
import sys
from ddgs import DDGS
q, n = sys.argv[1], int(sys.argv[2])
with DDGS() as d:
    res = list(d.text(q, max_results=n))
for r in res:
    print("*", (r.get("title") or "")[:110])
    print("  ", r.get("href") or "")
    print("  ", (r.get("body") or "").replace("\n", " ")[:300])
PY
    ;;
  fetch)
    M=${3:-40000}
    curl -s --max-time 90 "https://r.jina.ai/$2" | head -c "$M"
    ;;
esac
