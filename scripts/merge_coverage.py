#!/usr/bin/env python3
"""Merge Cobertura XML coverage reports from Backend and Frontend into a unified summary.

Usage:
    python scripts/merge_coverage.py backend.xml frontend.xml [--summary-file FILE]

Outputs a combined coverage table to stdout and optionally writes a
GitHub Actions job summary markdown file.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET


def parse_cobertura(path: str) -> dict:
    """Parse a Cobertura XML file and return aggregated metrics."""
    tree = ET.parse(path)
    root = tree.getroot()

    lines_valid = int(root.get("lines-valid", 0))
    lines_covered = int(root.get("lines-covered", 0))
    branches_valid = int(root.get("branches-valid", 0))
    branches_covered = int(root.get("branches-covered", 0))

    packages: list[dict] = []
    for pkg in root.findall(".//package"):
        pkg_name = pkg.get("name", "unknown")
        pkg_lines = int(pkg.get("lines-valid", 0))
        pkg_covered = int(pkg.get("lines-covered", 0))
        pkg_branches = int(pkg.get("branches-valid", 0))
        pkg_branches_cov = int(pkg.get("branches-covered", 0))
        packages.append(
            {
                "name": pkg_name,
                "lines_valid": pkg_lines,
                "lines_covered": pkg_covered,
                "branches_valid": pkg_branches,
                "branches_covered": pkg_branches_cov,
            }
        )

    return {
        "lines_valid": lines_valid,
        "lines_covered": lines_covered,
        "branches_valid": branches_valid,
        "branches_covered": branches_covered,
        "packages": packages,
    }


def pct(covered: int, valid: int) -> str:
    if valid == 0:
        return "N/A"
    return f"{covered / valid * 100:.1f}%"


def merge(backend: dict, frontend: dict) -> dict:
    """Combine two coverage reports into one."""
    return {
        "lines_valid": backend["lines_valid"] + frontend["lines_valid"],
        "lines_covered": backend["lines_covered"] + frontend["lines_covered"],
        "branches_valid": backend["branches_valid"] + frontend["branches_valid"],
        "branches_covered": backend["branches_covered"] + frontend["branches_covered"],
    }


def build_markdown(
    backend: dict,
    frontend: dict,
    combined: dict,
) -> str:
    """Build a GitHub-flavored Markdown summary table."""
    bl = pct(backend["lines_covered"], backend["lines_valid"])
    bb = pct(backend["branches_covered"], backend["branches_valid"])
    fl = pct(frontend["lines_covered"], frontend["lines_valid"])
    fb = pct(frontend["branches_covered"], frontend["branches_valid"])
    cl = pct(combined["lines_covered"], combined["lines_valid"])
    cb = pct(combined["branches_covered"], combined["branches_valid"])

    def row(icon: str, label: str, lc: str, bc: str, d: dict) -> str:
        lv = f"{d['lines_covered']}/{d['lines_valid']}"
        bv = f"{d['branches_covered']}/{d['branches_valid']}"
        return f"| {icon} **{label}** | **{lc}** | **{bc}** | {lv} | {bv} |"

    lines = [
        "## 📊 Unified Code Coverage Report",
        "",
        "| Scope | Line Coverage | Branch Coverage | Lines (covered/valid) | Branches (covered/valid) |",
        "|:------|:-------------|:----------------|:----------------------|:-------------------------|",
        row("🐍", "Backend (Python)", bl, bb, backend),
        row("🟨", "Frontend (JS)", fl, fb, frontend),
        row("🏁", "Combined", cl, cb, combined),
        "",
    ]

    # Overall line percentage for quick reference
    if combined["lines_valid"] > 0:
        overall = combined["lines_covered"] / combined["lines_valid"] * 100
        lines.append(f"> **Overall line coverage: {overall:.1f}%** across {combined['lines_valid']} lines of code.")
    else:
        lines.append("> **No coverage data available.**")

    lines.append("")
    return "\n".join(lines)


def write_github_summary(markdown: str) -> None:
    """Write to $GITHUB_STEP_SUMMARY if running in GitHub Actions."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")
        print("✅ Coverage summary written to GITHUB_STEP_SUMMARY")
    else:
        print("ℹ️  Not running in GitHub Actions — skipping GITHUB_STEP_SUMMARY")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge Cobertura XML coverage reports")
    parser.add_argument("backend", help="Path to backend coverage XML (e.g. coverage.xml)")
    parser.add_argument("frontend", help="Path to frontend coverage XML (e.g. coverage/js/coverage.xml)")
    parser.add_argument(
        "--output-xml",
        help="Optional: write merged Cobertura XML to this path",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.backend):
        print(f"❌ Backend coverage file not found: {args.backend}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.frontend):
        print(f"❌ Frontend coverage file not found: {args.frontend}", file=sys.stderr)
        sys.exit(1)

    backend = parse_cobertura(args.backend)
    frontend = parse_cobertura(args.frontend)
    combined = merge(backend, frontend)

    md = build_markdown(backend, frontend, combined)
    print(md)
    write_github_summary(md)

    # Write PR comment file if requested via env
    comment_path = os.environ.get("COVERAGE_COMMENT_PATH")
    if comment_path:
        with open(comment_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"✅ Coverage comment written to {comment_path}")

    # Print a short one-liner for quick CI log scanning
    if combined["lines_valid"] > 0:
        overall = combined["lines_covered"] / combined["lines_valid"] * 100
        print(f"🎯 Combined coverage: {overall:.1f}% ({combined['lines_covered']}/{combined['lines_valid']} lines)")


if __name__ == "__main__":
    main()
