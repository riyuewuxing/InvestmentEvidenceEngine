from datetime import UTC, date, datetime, timedelta

import pytest

from investment_evidence_engine.session_observation import (
    advance_ratio,
    auction_reference_status,
    breadth_count,
    breadth_percentage,
    dated_daily_flow_reference,
    pool_count,
    quote_reference_status,
    session_window_status,
    structure_filter_status,
)

DAY = date(2026, 11, 27)


def stamp(value):
    return datetime.fromisoformat(f"2026-11-27T{value}+08:00")


@pytest.mark.parametrize(("stage", "start", "end", "expected"), [
    ("PREMARKET", "08:29:59", "08:30:00", "TOO_EARLY"),
    ("PREMARKET", "08:30:00", "09:14:59", "WITHIN_WINDOW"),
    ("PREMARKET", "09:14:59", "09:15:00", "WINDOW_MISSED"),
    ("OPEN_AUCTION", "09:25:59", "09:26:00", "TOO_EARLY"),
    ("OPEN_AUCTION", "09:26:00", "09:29:59", "WITHIN_WINDOW"),
    ("OPEN_AUCTION", "09:29:59", "09:30:00", "WINDOW_MISSED"),
    ("EOD", "14:45:00", "14:59:59", "WITHIN_WINDOW"),
    ("EOD", "14:59:59", "15:00:00", "WINDOW_MISSED"),
    ("EOD", "15:00:00", "15:00:01", "WINDOW_MISSED"),
    ("POST_CLOSE", "14:59:59", "15:00:01", "TOO_EARLY"),
    ("POST_CLOSE", "15:35:00", "15:36:00", "WITHIN_WINDOW"),
])
def test_session_boundaries(stage, start, end, expected):
    assert session_window_status(stage, session=DAY, started_at=stamp(start).astimezone(UTC),
                                 finished_at=stamp(end), trading_day=True) == expected


def test_no_calendar_or_cross_day_does_not_assume_session():
    start = stamp("14:45:00")
    for calendar, status in ((None, "CALENDAR_UNKNOWN"), (False, "NON_TRADING_DAY")):
        assert session_window_status("EOD", session=DAY, started_at=start,
                                     finished_at=start, trading_day=calendar) == status
    assert session_window_status("EOD", session=DAY, started_at=start,
                                 finished_at=start + timedelta(days=1), trading_day=True) == "SESSION_MISMATCH"
    assert session_window_status("EOD", session=DAY, started_at=start.replace(tzinfo=None),
                                 finished_at=start, trading_day=True) == "INVALID_CLOCK"


@pytest.mark.parametrize(("market", "retrieved", "cutoff", "expected"), [
    ("09:25:00", "09:25:50", "09:26:00", "CHRONOLOGY_ONLY"),
    ("09:25:00", "09:26:01", "09:26:00", "AFTER_CUTOFF_OR_INVALID_ORDER"),
    ("09:20:00", "09:25:50", "09:26:00", "NOT_AUCTION_RESULT_TIME"),
    ("09:30:00", "09:30:01", "09:30:01", "NOT_AUCTION_RESULT_TIME"),
    ("09:25:00", "09:25:50", "09:25:59", "OUTSIDE_AUCTION_REVIEW_WINDOW"),
    (None, "09:25:50", "09:26:00", "SOURCE_TIME_UNKNOWN"),
])
def test_auction_cutoff(market, retrieved, cutoff, expected):
    assert auction_reference_status(session=DAY, market_at=stamp(market) if market else None,
                                    retrieved_at=stamp(retrieved), cutoff=stamp(cutoff),
                                    trading_day=True) == expected


def test_empty_pool_and_incomplete_denominator():
    class Empty:
        columns = ("code",)
        empty = True

        def __len__(self):
            return 0

    assert pool_count(None) is None
    assert pool_count([]) is None
    assert pool_count(Empty()) == 0
    assert advance_ratio(5, None, 0) is None
    assert advance_ratio(5, float("inf"), 0) is None
    assert advance_ratio(5, 0, 0) == 100
    assert advance_ratio(0, 0, 0) is None


def test_quote_time_is_not_collection_or_execution_time():
    assert quote_reference_status(session=DAY, market_at=stamp("14:44:00"),
                                  retrieved_at=stamp("14:45:00")) == "CHRONOLOGY_ONLY"
    assert quote_reference_status(session=DAY, market_at=stamp("14:42:59"),
                                  retrieved_at=stamp("14:45:00")) == "QUOTE_STALE"
    assert quote_reference_status(session=DAY, market_at=stamp("14:45:01"),
                                  retrieved_at=stamp("14:45:00")) == "QUOTE_AFTER_RETRIEVAL"
    assert quote_reference_status(session=DAY, market_at=stamp("15:00:00"),
                                  retrieved_at=stamp("15:00:00")) == "QUOTE_OUTSIDE_TAIL"
    assert quote_reference_status(session=DAY, market_at=None,
                                  retrieved_at=stamp("14:45:00")) == "QUOTE_TIME_UNKNOWN"


def test_structure_filters_preserve_missing_zero_and_threshold_equality():
    limits = {"timeline_above_avg_ratio": 80., "tail_30m_slope_min": 0.,
              "tail_30m_amount_share_min": None, "intraday_drawback_max": 3.,
              "require_main_inflow": False}
    observed = {"timeline_above_avg_ratio": 80., "tail_30m_return_pct": 0.,
                "intraday_drawback_pct": 3.}
    assert structure_filter_status(observed, limits) == "MATCH"
    assert structure_filter_status(observed | {"tail_30m_return_pct": None}, limits) == "UNAVAILABLE"
    assert structure_filter_status(observed | {"intraday_drawback_pct": 3.01}, limits) == "EXCLUDED"
    assert structure_filter_status(observed | {"timeline_above_avg_ratio": float("nan")}, limits) == "UNAVAILABLE"
    limits["require_main_inflow"] = True
    assert structure_filter_status(observed, limits) == "UNAVAILABLE"
    assert structure_filter_status(observed | {"main_net_inflow_10k": 0.}, limits) == "EXCLUDED"
    assert structure_filter_status(observed | {"main_net_inflow_10k": 1.}, limits) == "MATCH"


def test_daily_flow_scope_does_not_leak_future_or_fill_missing_zero():
    rows = [{"date": "2026-11-28", "mainNetInflow": 1000000},
            {"date": "2026-11-27", "mainNetInflow": 0},
            {"date": "2026-11-26", "mainNetInflow": 100000}]
    assert dated_daily_flow_reference(rows, session=DAY, cutoff=stamp("14:45:00")) == (
        None, "DAILY_FLOW_NOT_INTRADAY")
    assert dated_daily_flow_reference(rows, session=DAY, cutoff=stamp("15:01:00")) == (
        0., "DATED_DAILY_REFERENCE_ONLY")
    assert dated_daily_flow_reference(rows[:1], session=DAY, cutoff=stamp("15:01:00")) == (
        None, "FLOW_SESSION_UNAVAILABLE")
    assert dated_daily_flow_reference(rows + [{"date": "2026-11-27", "mainNetInflow": 100}],
                                      session=DAY, cutoff=stamp("15:01:00")) == (
        None, "FLOW_DUPLICATE_CONFLICT")
    assert dated_daily_flow_reference([{"date": "2026-11-27", "mainNetInflowYuan": 10000,
                                        "mainNetInflowWan": 2}], session=DAY, cutoff=stamp("15:01:00")) == (
        None, "FLOW_UNIT_CONFLICT")


def test_pool_schema_and_duplicate_identities_are_not_zero_or_counts():
    class Pool:
        def __init__(self, codes, columns=("code",)):
            self.codes = codes
            self.columns = columns
            self.empty = not codes

        def __len__(self):
            return len(self.codes)

        def __getitem__(self, key):
            return self

        def tolist(self):
            return self.codes

    assert pool_count(Pool([], ())) is None
    assert pool_count(Pool([], ("wrong",))) is None
    assert pool_count(Pool([], ("代码",)), identity_column="代码") == 0
    assert pool_count(Pool(["000001", "600000"])) == 2
    assert pool_count(Pool(["000001", "000001"])) is None
    assert pool_count(Pool(["000001", None])) is None
    assert pool_count(Pool(["000001", "1"])) is None
    assert pool_count(Pool(["000001"], ("code", "code"))) is None
    assert advance_ratio(5.5, 2, 0) is None
    assert advance_ratio(True, 2, 0) is None
    assert advance_ratio(5., 5., 0.) == 50.


def test_tail_market_time_cannot_mask_post_close_retrieval():
    assert quote_reference_status(session=DAY, market_at=stamp("14:59:59"),
                                  retrieved_at=stamp("15:00:00").astimezone(UTC)) == "QUOTE_RETRIEVAL_OUTSIDE_TAIL"


@pytest.mark.parametrize(("aliases", "expected"), [
    ({"mainNetInflowYuan": 10000, "mainNetInflow": 20000}, (None, "FLOW_UNIT_CONFLICT")),
    ({"mainNetInflowWan": 1, "mainNetInflow": 20000}, (None, "FLOW_UNIT_CONFLICT")),
    ({"mainNetInflowYuan": 0, "mainNetInflowWan": 0, "mainNetInflow": 0}, (0., "DATED_DAILY_REFERENCE_ONLY")),
    ({"mainNetInflowYuan": 0, "mainNetInflow": "bad"}, (None, "FLOW_VALUE_UNKNOWN")),
])
def test_all_explicit_flow_aliases_must_agree(aliases, expected):
    assert dated_daily_flow_reference([{"date": DAY.isoformat()} | aliases],
                                      session=DAY, cutoff=stamp("15:01:00")) == expected


@pytest.mark.parametrize("value", [-1, 100.01, 10**400, float("inf"), float("nan"), True, "50", None])
def test_invalid_breadth_percentage_is_unknown(value):
    assert breadth_percentage(value) is None


@pytest.mark.parametrize("value", [-1, 1.5, float("inf"), float("nan"), True, "5", None])
def test_invalid_breadth_count_is_unknown(value):
    assert breadth_count(value) is None


def test_breadth_boundaries_preserve_actual_zero():
    assert breadth_count(0) == 0
    assert breadth_count(5.) == 5
    assert breadth_percentage(0) == 0
    assert breadth_percentage(100.) == 100
