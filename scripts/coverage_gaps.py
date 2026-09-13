#!/usr/bin/env python3
"""Coverage ratchet — per-file gap report + fail-under gate.

Reads the backend and frontend Cobertura XML reports, renders a GitHub-flavored
Markdown report (combined summary + per-file gap tables), and enforces a
monotonic ratchet:

- ``--check``  : exit 1 when coverage drops below the recorded threshold
                 (.github/coverage-threshold.json). Never blocks a *new*
                 maximum — the threshold only moves via ``--update``.
- ``--update`` : when a scope reaches 100.0% lines, persist the threshold so
                 the gate permanently holds that line.

Usage (CI):
    python scripts/coverage_gaps.py "$BACKEND_XML" "$FRONTEND_XML" \\
        --comment-file /tmp/coverage-comment.md --check

Usage (local):
    python scripts/coverage_gaps.py coverage.xml coverage/js/cobertura-coverage.xml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

THRESHOLD_PATH = Path(".github/coverage-threshold.json")
TOP_N = 15


def parse_cobertura(path: str) -> dict:
    """Parse a Cobertura XML file into per-file and aggregate metrics."""
    root = ET.parse(path).getroot()
    agg = {
        "lines_valid": int(root.get("lines-valid", 0)),
        "lines_covered": int(root.get("lines-covered", 0)),
        "branches_valid": int(root.get("branches-valid", 0)),
        "branches_covered": int(root.get("branches-covered", 0)),
    }
    files: list[dict] = []
    for cls in root.findall(".//class"):
        fname = cls.get("filename", cls.get("name", "unknown"))
        lines = cls.findall("./lines/line")
        misses: list[int] = []
        branches_total = 0
        branches_hit = 0
        for ln in lines:
            hits = int(ln.get("hits", 0))
            if hits == 0:
                misses.append(int(ln.get("number", 0)))
            if ln.get("branch") == "true":
                cond = ln.find("conditions")
                if cond is not None:
                    for c in cond.findall("condition"):
                        branches_total += int(c.get("coverage", "0%").rstrip("%") or 0) and 0
                        branches_total += 1
                        if int(c.get("coverage", "0%").rstrip("%") or 0) == 100:
                            branches_hit += 1
        lv = len(lines)
        lc = lv - len(misses)
        files.append(
            {
                "name": fname.replace("\\", "/"),
                "lines_valid": lv,
                "lines_covered": lc,
                "misses": misses,
                "branches_valid": branches_total,
                "branches_covered": branches_hit,
            }
        )
    # XML root aggregates are authoritative for totals (dedup across packages)
    agg["files"] = files
    return agg


def pct(covered: int, valid: int) -> float:
    return (covered / valid * 100) if valid else 100.0


def fmt_pct(covered: int, valid: int) -> str:
    return "N/A" if valid == 0 else f"{covered / valid * 100:.2f}%"


def scope_rows(name: str, icon: str, data: dict) -> list[str]:
    lv, lc = data["lines_valid"], data["lines_covered"]
    bv, bc = data["branches_valid"], data["branches_covered"]
    return [
        f"| {icon} **{name}** | **{fmt_pct(lc, lv)}** | **{fmt_pct(bc, bv)}** | {lc}/{lv} | {bc}/{bv} |",
    ]


def gap_table(data: dict, top_n: int = TOP_N) -> list[str]:
    """Render the worst files by missed-line count (only files with gaps)."""
    gapped = sorted(
        (f for f in data["files"] if f["lines_covered"] < f["lines_valid"]),
        key=lambda f: (-(f["lines_valid"] - f["lines_covered"]), f["name"]),
    )
    if not gapped:
        return ["**🎯 No uncovered lines — this scope is at 100% line coverage.**", ""]
    out = [
        f"<details open><summary>🔎 <b>Per-file gaps</b> — {len(gapped)} file(s), "
        f"{sum(f['lines_valid'] - f['lines_covered'] for f in gapped)} missed line(s)</summary>",
        "",
        "| File | Line Coverage | Missed Lines |",
        "|:-----|:-------------|:-------------|",
    ]
    for f in gapped[:top_n]:
        file_pct = pct(f["lines_covered"], f["lines_valid"])
        misses = ",".join(str(m) for m in f["misses"][:25])
        if len(f["misses"]) > 25:
            misses += "…"
        out.append(f"| `{f['name']}` | {file_pct:.1f}% | {misses} |")
    out += ["", "</details>", ""]
    return out


def load_threshold() -> dict:
    if THRESHOLD_PATH.exists():
        return json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    return {"backend": 0.0, "frontend": 0.0}


def save_threshold(t: dict) -> None:
    THRESHOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    THRESHOLD_PATH.write_text(json.dumps(t, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Coverage gap report + ratchet gate")
    parser.add_argument("backend", help="Backend Cobertura XML path")
    parser.add_argument("frontend", help="Frontend Cobertura XML path")
    parser.add_argument("--comment-file", help="Write the full Markdown report here")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when a scope is below its recorded threshold (ratchet)",
    )  # noqa: DAT105
    parser.add_argument(
        "--update",
        action="store_true",
        help="Persist threshold for any scope that reached 100.0%% lines",
    )
    args = parser.parse_args()

    backend = parse_cobertura(args.backend)
    frontend = parse_cobertura(args.frontend)

    combined = {
        "lines_valid": backend["lines_valid"] + frontend["lines_valid"],
        "lines_covered": backend["lines_covered"] + frontend["lines_covered"],
        "branches_valid": backend["branches_valid"] + frontend["branches_valid"],
        "branches_covered": backend["branches_covered"] + frontend["branches_covered"],
    }

    lines = [
        "## 📊 Unified Code Coverage Report",
        "",
        "| Scope | Line Coverage | Branch Coverage | Lines (covered/valid) | Branches (covered/valid) |",
        "|:------|:-------------|:----------------|:----------------------|:-------------------------|",
        *scope_rows("Backend (Python)", "🐍", backend),
        *scope_rows("Frontend (JS)", "🟨", frontend),
        *scope_rows("Combined", "🏁", combined),
        "",
    ]
    overall = pct(combined["lines_covered"], combined["lines_valid"])
    lines.append(f"> **Overall line coverage: {overall:.2f}%** across {combined['lines_valid']} lines.")
    lines.append("")

    # Per-file gap tables (the actionable part of the report)
    lines.append("### 🐍 Backend gaps")
    lines += gap_table(backend)
    lines.append("### 🟨 Frontend gaps")
    lines += gap_table(frontend)

    report = "\n".join(lines)
    print(report)

    if args.comment_file:
        Path(args.comment_file).write_text(report, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")

    # ── Ratchet mechanics ────────────────────────────────────────────
    threshold = load_threshold()
    if args.update:
        changed = False
        bl, fl = pct(backend["lines_covered"], backend["lines_valid"]), pct(
            frontend["lines_covered"], frontend["lines_valid"]
        )
        if bl >= 100.0 and threshold.get("backend", 0) < 100:
            threshold["backend"] = 100.0
            changed = True
        if fl >= 100.0 and threshold.get("frontend", 0) < 100:
            threshold["frontend"] = 100.0
            changed = True
        if changed:
            save_threshold(threshold)
            print(f"🔒 Ratchet locked: {threshold}")
        else:
            print("ℹ️  Ratchet unchanged (no scope at 100% yet)")

    status = 0
    if args.check:
        bl, fl = pct(backend["lines_covered"], backend["lines_valid"]), pct(
            frontend["lines_covered"], frontend["lines_valid"]
        )
        req_b = threshold.get("backend", 0.0)
        req_f = threshold.get("frontend", 0.0)
        if bl < req_b:
            print(f"❌ Backend coverage {bl:.2f}% < ratchet {req_b:.2f}%", file=sys.stderr)
            status = 1
        if fl < req_f:
            print(f"❌ Frontend coverage {fl:.2f}% < ratchet {req_f:.2f}%", file=sys.stderr)
            status = 1
        if status == 0:
            print(f"✅ Ratchet gate passed (backend≥{req_b:.2f}%, frontend≥{req_f:.2f}%)")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
