#!/usr/bin/env bash
# Phase 1 evidence: regression tests, mutation check, launch override check.
# Writes everything to evidence/phase1/. Run from anywhere:
#   bash evaluation/scripts/phase1_evidence.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/evidence/phase1"
mkdir -p "$OUT"
source /opt/ros/humble/setup.bash
cd "$ROOT"

echo "== regression tests"
PYTHONPATH=src/yoru_core:$PYTHONPATH python3 -m pytest src/yoru_core/test -v -p no:cacheprovider \
    --junitxml="$OUT/pytest_junit.xml" > "$OUT/pytest.txt" 2>&1
tail -1 "$OUT/pytest.txt"

echo "== mutation check (tests must FAIL on a modified rule)"
TMP="$(mktemp -d)"
{
    for mutation in "s/'w_P': 0.3,/'w_P': 0.31,/" \
                    "s/confidence >= confirm_at and c1/confidence > confirm_at and c1/" \
                    "s/and fp_risk != 'high')/)/"; do
        rm -rf "$TMP/yoru_core" && cp -r src/yoru_core "$TMP/"
        sed -i "$mutation" "$TMP/yoru_core/yoru_core/confirmation_rule.py"
        result="$(PYTHONPATH="$TMP/yoru_core:$PYTHONPATH" python3 -m pytest "$TMP/yoru_core/test" -q \
                  -p no:cacheprovider 2>&1 | tail -1)"
        echo "mutation: $mutation"
        echo "  result: $result"
    done
} | tee "$OUT/mutation_check.txt"
rm -rf "$TMP"

echo "== launch override check"
source install/setup.bash
python3 evaluation/scripts/phase1_launch_overrides.py | tee "$OUT/launch_override_check.txt"
