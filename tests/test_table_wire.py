from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from investment_evidence_engine.table_wire import pack_frame, unpack_frame


def test_exact_scalar_transport():
    frame = pd.DataFrame([["000001", 0, 9_007_199_254_740_993, 1.2345678901234567,
                           pd.Timestamp("2026-09-30"), Decimal("0.0123400"), pd.NA],
                          ["000002", False, None, np.nan, pd.NaT, None, ""]],
                         columns=["code", "zero", "int", "float", "date", "decimal", "unknown"],
                         dtype=object)
    out = unpack_frame(pack_frame(frame))
    assert out.iloc[0].tolist() == ["000001", 0, 9_007_199_254_740_993, 1.2345678901234567,
                                    "2026-09-30T00:00:00", "0.0123400", None]
    assert out.iloc[1].tolist() == ["000002", False, None, None, None, None, ""]
    assert out.iloc[1]["zero"] is False


def test_empty_and_invalid_tables():
    assert unpack_frame(None) is None
    out = unpack_frame(pack_frame(pd.DataFrame(columns=["code"])))
    assert out.empty and list(out.columns) == ["code"]
    with pytest.raises(ValueError):
        pack_frame(pd.DataFrame([[1, 2]], columns=["a", "a"]))
    with pytest.raises(ValueError):
        pack_frame(pd.DataFrame({"a": [object()]}))
    with pytest.raises(ValueError):
        unpack_frame({"columns": ["a"], "rows": [[1, 2]]})
    with pytest.raises(ValueError):
        unpack_frame({"columns": ["a"], "rows": [[{"fake": 1}]]})
    with pytest.raises(ValueError):
        unpack_frame({"columns": ["a"], "rows": [[float("inf")]]})
    with pytest.raises(ValueError):
        pack_frame(pd.DataFrame({"a": range(10001)}))
