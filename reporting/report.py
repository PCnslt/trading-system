"""Return-channel report writer — the single canonical place task results land.

Every dispatched task (webhook / cron) MUST finish by calling :func:`append_report`
so its outcome is recorded in ``~/trading-system/REPORTS.md`` (human-readable)
and ``REPORTS.json`` (JSON sidecar). The ``GET /reports`` pull endpoint
(``trading-reports.service`` on :8645) serves the JSON sidecar back to the
laptop, which is behind NAT and cannot receive a true push webhook.

Ordering: both files grow chronologically (append). The API reverses them so
"latest" comes first. ``commits`` and ``blockers`` are lists (may be empty).

CLI:
    python3 reporting/report.py \
        --task "One-line task description" \
        --summary "What was actually done" \
        --commit abc123def --commit 456def789 \
        --blocker "Optional blocker / next step"

Library:
    from reporting.report import append_report
    append_report("task", "summary", commits=["sha"], blockers=["next step"])
"""

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone

# Canonical file locations (next to each other, per task spec).
_TARGET_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD_PATH = os.path.join(_TARGET_DIR, "REPORTS.md")
JSON_PATH = os.path.join(_TARGET_DIR, "REPORTS.json")


def _now_iso() -> str:
    """Local (ET) ISO-8601 timestamp with offset, for the report entry."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_reports() -> list[dict]:
    """Return all report entries in chronological (append) order."""
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    reports = data.get("reports", []) if isinstance(data, dict) else []
    return [r for r in reports if isinstance(r, dict)]


def _render_md(reports: list[dict]) -> str:
    """Render the full REPORTS.md from the entries (chronological)."""
    header = [
        "# Task Completion Reports",
        "",
        "> Canonical return-channel log. Every dispatched task appends here "
        "(newest at bottom, chronological).",
        "> Machine-readable mirror: `REPORTS.json`. Pull path: `GET /reports` on :8645.",
        "",
    ]
    blocks = []
    for r in reports:
        ts = r.get("ts", "")
        task = r.get("task", "(no task)")
        summary = r.get("summary", "")
        commits = r.get("commits", []) or []
        blockers = r.get("blockers", []) or []
        lines = [f"## {ts} — {task}", ""]
        lines.append(f"- **Summary**: {summary}")
        if commits:
            lines.append("- **Commits**: " + " ".join(f"`{c}`" for c in commits))
        if blockers:
            lines.append("- **Blockers**:")
            lines.extend(f"  - {b}" for b in blockers)
        blocks.append("\n".join(lines))
    body = "\n\n---\n\n".join(blocks)
    if body:
        body += "\n"
    return "\n".join(header) + "\n" + body


def _atomic_write(path: str, text: str) -> None:
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".reports.", suffix=".tmp", dir=d, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_report(
    task: str,
    summary: str,
    commits: list[str] | None = None,
    blockers: list[str] | None = None,
    ts: str | None = None,
) -> dict:
    """Append one report entry to REPORTS.json + REPORTS.md atomically.

    Returns the entry dict written. ``commits``/``blockers`` are lists of
    strings (commit SHAs, blocker/next-step notes); empty lists are the default.
    """
    entry = {
        "ts": ts or _now_iso(),
        "task": (task or "").strip(),
        "summary": (summary or "").strip(),
        "commits": [str(c).strip() for c in (commits or []) if str(c).strip()],
        "blockers": [str(b).strip() for b in (blockers or []) if str(b).strip()],
    }
    reports = load_reports()
    reports.append(entry)

    payload = {"updated": _now_iso(), "reports": reports}
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    _atomic_write(JSON_PATH, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(MD_PATH, _render_md(reports))

    # Mirror to the VPS→laptop SQS channel (best-effort; never blocks/fails the append).
    try:
        from reporting.sqs_publisher import publish_report
    except Exception:  # noqa: BLE001 — channel is an optional fast-path
        publish_report = None
    if publish_report is not None:
        publish_report(entry)

    return entry


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Append a task-completion report.")
    ap.add_argument("--task", required=True, help="One-line task description")
    ap.add_argument("--summary", required=True, help="What was actually done")
    ap.add_argument("--commit", action="append", default=[], help="Commit SHA (repeatable)")
    ap.add_argument("--blocker", action="append", default=[], help="Blocker/next step (repeatable)")
    ap.add_argument("--ts", default=None, help="Override ISO timestamp (default: now)")
    args = ap.parse_args()
    entry = append_report(args.task, args.summary, args.commit, args.blocker, args.ts)
    print(json.dumps(entry, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
