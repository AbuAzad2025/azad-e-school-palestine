#!/usr/bin/env bash
# scripts/lighthouse.sh — Lighthouse CI against local dev server
# Usage: bash scripts/lighthouse.sh [URL]
# Requires: lighthouse CLI (npm install -g lighthouse)

set -euo pipefail

URL="${1:-http://localhost:5000}"

echo "Running Lighthouse against $URL ..."
echo "Budget: Performance >= 80, Accessibility >= 90"

if ! command -v lighthouse &> /dev/null; then
  echo "ERROR: lighthouse not found. Install with: npm install -g lighthouse"
  exit 1
fi

lighthouse "$URL" \
  --output=json \
  --output-path=./lighthouse-report.json \
  --chrome-flags="--headless --no-sandbox" \
  --only-categories=performance,accessibility \
  --quiet

# Parse scores
PERF=$(python3 -c "import json; d=json.load(open('lighthouse-report.json')); print(int(d['categories']['performance']['score']*100))" 2>/dev/null || echo "0")
A11Y=$(python3 -c "import json; d=json.load(open('lighthouse-report.json')); print(int(d['categories']['accessibility']['score']*100))" 2>/dev/null || echo "0")

echo "Performance: $PERF/100 (budget: >= 80)"
echo "Accessibility: $A11Y/100 (budget: >= 90)"

FAILED=0
if [ "$PERF" -lt 80 ]; then
  echo "FAIL: Performance score $PERF < 80"
  FAILED=1
fi
if [ "$A11Y" -lt 90 ]; then
  echo "FAIL: Accessibility score $A11Y < 90"
  FAILED=1
fi

if [ "$FAILED" -eq 0 ]; then
  echo "PASS: All Lighthouse budgets met."
  exit 0
else
  echo "FAIL: Lighthouse budgets not met."
  exit 1
fi
