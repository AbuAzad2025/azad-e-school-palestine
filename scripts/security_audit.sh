#!/usr/bin/env bash
# scripts/security_audit.sh — Dependency audit + security checks
# Usage: bash scripts/security_audit.sh
# Requires: pip-audit (pip install pip-audit)

set -euo pipefail

FAILED=0

echo "========================================"
echo "  Security Audit — Azad E-School"
echo "========================================"
echo ""

# 1. pip-audit: scan for known vulnerabilities
echo "[1/4] pip-audit — scanning dependencies..."
if command -v pip-audit &> /dev/null; then
    pip-audit --desc --output audit-report.txt --format human 2>/dev/null || {
        echo "  pip-audit found vulnerabilities. See audit-report.txt"
        FAILED=1
    }
elif python -m pip_audit --version &> /dev/null 2>&1; then
    python -m pip_audit --desc --output audit-report.txt --format human 2>/dev/null || {
        echo "  pip-audit found vulnerabilities. See audit-report.txt"
        FAILED=1
    }
else
    echo "  WARNING: pip-audit not found. Install: pip install pip-audit"
    echo "  Skipping dependency audit."
fi

# 2. Check requirements.txt for pinned versions
echo ""
echo "[2/4] Checking pinned versions in requirements.txt..."
if [ -f requirements.txt ]; then
    UNPINNED=$(grep -E "^[^#].*>=.*$" requirements.txt | grep -v -E ">[=0-9]" | head -20)
    if [ -n "$UNPINNED" ]; then
        echo "  WARNING: These dependencies use >= (not pinned):"
        echo "$UNPINNED" | sed 's/^/    /'
        echo "  Consider pinning exact versions for reproducibility."
    else
        echo "  OK: All dependencies have version constraints."
    fi
else
    echo "  WARNING: requirements.txt not found."
fi

# 3. Check for hardcoded secrets in source
echo ""
echo "[3/4] Scanning for hardcoded secrets..."
SECRET_PATTERNS='(password|secret|api_key|token|private_key)\s*=\s*["\x27][A-Za-z0-9+/=]{8,}'
HITS=$(grep -rniE "$SECRET_PATTERNS" app/ --include="*.py" 2>/dev/null | \
    grep -v -E "(hash_password|verify_password|SECRET_KEY|CSRF|_token|api_key.*=.*cfg|config|os\.getenv|\.env)" | \
    grep -v "test" | \
    head -20)
if [ -n "$HITS" ]; then
    echo "  WARNING: Potential hardcoded secrets found:"
    echo "$HITS" | sed 's/^/    /'
    FAILED=1
else
    echo "  OK: No hardcoded secrets found."
fi

# 4. Check .env is in .gitignore
echo ""
echo "[4/4] Checking .env protection..."
if [ -f .gitignore ]; then
    if grep -q "^\.env$" .gitignore 2>/dev/null; then
        echo "  OK: .env is in .gitignore."
    else
        echo "  WARNING: .env is NOT in .gitignore!"
        FAILED=1
    fi
else
    echo "  WARNING: .gitignore not found."
fi

echo ""
echo "========================================"
if [ "$FAILED" -eq 0 ]; then
    echo "  Result: PASS — No critical issues."
else
    echo "  Result: FAIL — Review warnings above."
fi
echo "========================================"
exit $FAILED
