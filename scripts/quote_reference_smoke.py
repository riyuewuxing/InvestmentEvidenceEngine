"""Fixed public controls; exact raw wire receipts rehashed in temporary storage."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.historical_capture import SH, PublicSecurity
from investment_evidence_engine.quote_receipt import (
    capture_quotes,
    load_latest_quote,
    persist_quote_receipt,
)


def main():
    results=[]
    for subject in (PublicSecurity(symbol="600519",asset_type="STOCK"),
                    PublicSecurity(symbol="510050",asset_type="ETF")):
        receipt=capture_quotes(subject)
        with TemporaryDirectory() as temp:
            digest,computed=persist_quote_receipt(Path(temp),receipt)
            loaded=load_latest_quote(Path(temp),subject,now=datetime.now(SH))
            assert loaded["receipt_sha256"]==digest
            assert loaded["receipt_rehashed"] and loaded["raw_payloads_rehashed"]
            assert loaded["failures"]==computed["failures"]
            results.append(loaded)
    print(json.dumps({"controls":results,"raw_provider_bytes_uploaded":False,"decision_authority":False}))
    return 0 if all(result["status"]=="OBSERVED_TOP_OF_BOOK_ONLY" for result in results) else 2


if __name__=="__main__":
    raise SystemExit(main())
