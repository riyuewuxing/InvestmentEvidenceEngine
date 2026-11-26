"""Fixed public control quote observations; raw bytes temporary only."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.historical_capture import SH, PublicSecurity
from investment_evidence_engine.quote_reference import acquire_quote, crosscheck_quotes, parse_quote, quote_reference


def main():
    results=[]
    for subject in (PublicSecurity(symbol="600519",asset_type="STOCK"),
                    PublicSecurity(symbol="510050",asset_type="ETF")):
        found=[]
        failures=[]
        with TemporaryDirectory() as temp:
            for provider in ("tencent","sina"):
                try:
                    raw,obs=acquire_quote(subject,provider)
                    path=Path(temp)/(provider+".bin")
                    path.write_bytes(raw)
                    reopened=path.read_bytes()
                    assert hashlib.sha256(reopened).hexdigest()==obs.raw_response_sha256
                    assert parse_quote(reopened,subject,provider,obs.observed_at)==obs
                    found.append(obs)
                except (ValueError,OSError) as exc:
                    failures.append({"provider":provider,"error_type":type(exc).__name__})
            clock=datetime.now(SH)
            rows=[quote_reference(obs,now=clock) for obs in found]
            for row in rows:
                row["actual_raw_bytes_rehash"]="MATCH"
            crosscheck=crosscheck_quotes(*found,now=clock) if len(found)==2 else {"status":"SOURCE_UNAVAILABLE"}
            results.append({"subject":subject.model_dump(mode="json"),"observations":rows,
                            "failures":failures,"crosscheck":crosscheck})
    print(json.dumps({"controls":results,"raw_provider_bytes_uploaded":False,"decision_authority":False}))
    # A smoke of current top-of-book requires both controls, but does not
    # demand source equality on asynchronous continuously changing markets.
    return 0 if all(any(row["status"]=="OBSERVED_TOP_OF_BOOK_ONLY" for row in result["observations"])
                    for result in results) else 2


if __name__=="__main__":
    raise SystemExit(main())
