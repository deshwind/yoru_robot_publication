"""Statistics used in the summary tables, checked against reference values.

Run: python3 -m pytest evaluation/tests -q
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from summarise import bootstrap_ci, describe, wilson  # noqa: E402


@pytest.mark.parametrize('k, n, low, high', [
    # Wilson score intervals (95 %), reference values from Newcombe (1998),
    # Statistics in Medicine 17:857-872, Table I, and standard calculators
    (81, 263, 0.2553, 0.3662),
    (15, 148, 0.0624, 0.1605),
    (0, 20, 0.0, 0.1611),
    (20, 20, 0.8389, 1.0),
    (10, 20, 0.2993, 0.7007),
])
def test_wilson_reference_values(k, n, low, high):
    p, lo, hi = wilson(k, n)
    assert p == pytest.approx(k / n)
    assert lo == pytest.approx(low, abs=5e-4)
    assert hi == pytest.approx(high, abs=5e-4)


def test_wilson_empty():
    assert all(np.isnan(x) for x in wilson(0, 0))


def test_bootstrap_ci_is_reproducible_and_covers_the_mean():
    values = np.random.default_rng(1).normal(10.0, 2.0, size=20)
    a = bootstrap_ci(values, np.random.default_rng(5))
    b = bootstrap_ci(values, np.random.default_rng(5))
    assert a == b
    assert a[0] < values.mean() < a[1]
    # about the normal-theory width 2 * 1.96 * sd / sqrt(n)
    expected = 2 * 1.96 * values.std(ddof=1) / np.sqrt(len(values))
    assert (a[1] - a[0]) == pytest.approx(expected, rel=0.15)


def test_describe_ignores_nan_and_matches_numpy():
    stat = describe([1.0, 2.0, 3.0, 4.0, float('nan')], np.random.default_rng(0))
    assert stat['n'] == 4
    assert stat['mean'] == pytest.approx(2.5)
    assert stat['sd'] == pytest.approx(np.std([1, 2, 3, 4], ddof=1))
    assert (stat['q1'], stat['median'], stat['q3']) == (1.75, 2.5, 3.25)
    assert describe([float('nan')], np.random.default_rng(0)) == {'n': 0}
