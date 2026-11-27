from datetime import date
from types import SimpleNamespace

from investment_evidence_engine import public_etf_dealing_close_control as control


def fake_series(*, missing=False, wrong=False):
    rows = []
    for symbol, sessions in control.TARGETS.items():
        for provider in ("sina", "tencent"):
            bars = []
            for session in sessions:
                if missing and provider == "tencent" and session == "2026-09-07":
                    continue
                close = 2.045 if wrong and session == "2026-08-27" else (
                    2.044 if session == "2026-08-27" else 1.0
                )
                bars.append(SimpleNamespace(session=date.fromisoformat(session), close=close))
            rows.append(SimpleNamespace(subject_id=symbol, source_label=provider, closes=bars))
    return {}, rows


def test_close_control_requires_both_sources_and_issuer_match(monkeypatch):
    monkeypatch.setattr(control, "observe_pair", lambda *a, **kw: fake_series())
    result = control.run_control()
    assert result["status"] == "WARN"
    assert result["daily_close_does_not_prove_intraday_resume_or_fill"]
    assert not result["decision_authority"]
    monkeypatch.setattr(control, "observe_pair", lambda *a, **kw: fake_series(missing=True))
    assert control.run_control()["status"] == "BLOCK"
    monkeypatch.setattr(control, "observe_pair", lambda *a, **kw: fake_series(wrong=True))
    assert control.run_control()["status"] == "BLOCK"
