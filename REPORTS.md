# Task Completion Reports

> Canonical return-channel log. Every dispatched task appends here (newest at bottom, chronological).
> Machine-readable mirror: `REPORTS.json`. Pull path: `GET /reports` on :8645.

## 2026-08-16T12:00:25-04:00 — Return channel — VPS→laptop reporting (GET /reports pull endpoint)

- **Summary**: Built the PULL return channel: reporting/report.py (append_report → REPORTS.md + REPORTS.json, canonical), reporting/report_server.py (stdlib HTTP server :8645, HMAC-SHA256 auth reusing laptop-task webhook secret), trading-reports.service (enabled+running). Verified end-to-end: /health 200, /reports 401 w/o sig + 200 w/ valid HMAC, limit/since params, newest-first ordering.
- **Commits**: `a8be23eb86c9854b5acb0b2c28aa034baad3f13b`
- **Blockers**:
  - SG ingress for :8645 is NOT open: trading-vps-role lacks ec2:AuthorizeSecurityGroupIngress. Owner must run 'aws ec2 authorize-security-group-ingress' for tcp 8645 (laptop IP, mirrors 8644 rule) before the laptop can reach /reports over the public internet.
