"""Independent exact-rational arithmetic controls; synthetic prices only."""
from datetime import date, timedelta
from fractions import Fraction
from itertools import groupby
from math import prod

import pytest

from investment_evidence_engine.momentum_profile import momentum_metrics, momentum_profile


@pytest.mark.parametrize("bps", [10, 20, 30])
def test_binary_exposure_matches_independent_round_trip_product(bps):
    # Independently partition consecutive invested runs; each incurs two fees.
    # The production recurrence is intentionally not used to construct the oracle.
    gross = [Fraction(11, 10), Fraction(9, 10), Fraction(7, 5),
             Fraction(6, 5), Fraction(4, 5), Fraction(21, 20)]
    exposure = [1, 1, 0, 1, 0, 1]
    friction = Fraction(10000 - bps, 10000)
    runs = [
        list(items) for active, items in groupby(zip(exposure, gross, strict=True),
                                                key=lambda pair: pair[0]) if active
    ]
    expected = prod(friction**2 * prod(ratio for _, ratio in run) for run in runs)
    result = momentum_metrics([float(value) for value in gross], exposure, bps)
    assert result["net_price_change_pct"] == pytest.approx(float(100*(expected-1)))
    assert result["unit_weight_turnover"] == 2*len(runs)
    assert result["invested_intervals"] == sum(len(run) for run in runs)


def test_open_drawdown_includes_entry_and_terminal_exit_cost():
    result = momentum_metrics([0.8, 0.5], [1, 1], 10)
    terminal = Fraction(999, 1000)**2 * Fraction(4, 5) * Fraction(1, 2)
    assert result["max_observed_open_drawdown_pct"] == pytest.approx(float(100*(1-terminal)))
    assert result["net_price_change_pct"] == pytest.approx(float(100*(terminal-1)))


def test_split_boundaries_purge_and_causal_signal_from_explicit_index_oracle():
    n = 459
    dates = tuple(date(2025, 1, 1) + timedelta(days=i) for i in range(n))
    closes = [100 + i/10 for i in range(n)]
    opens = [100 + i/20 for i in range(n)]
    result = momentum_profile(dates, closes, opens)
    groups = [(21, 281), (284, 368), (371, 457)]
    for segment, (first, last) in zip(result["segments"], groups, strict=True):
        assert segment["first_entry_open"] == dates[first].isoformat()
        assert segment["terminal_open"] == dates[last+1].isoformat()
        assert segment["intervals"] == last-first+1
        for stress in segment["stress"]:
            # Monotonic close means the signal equals full exposure; open returns telescope.
            friction = (10000-stress["one_way_bps"])/10000
            expected = 100*(opens[last+1]/opens[first]*friction**2-1)
            assert stress["signal_rule"]["net_price_change_pct"] == pytest.approx(expected)
            assert stress["signal_rule"] == stress["constant_invested"]
    # A close printed at the final interval or later is unavailable to that interval.
    modified = closes.copy()
    modified[457:] = [1.0, 10000.0]
    assert momentum_profile(dates, modified, opens) == result
