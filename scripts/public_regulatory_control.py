"""Public-only regulatory source observation; never print document bodies."""
import json
import sys
from datetime import UTC, datetime

from investment_evidence_engine.sources import DEFAULT_OFFICIAL_SOURCES, fetch_official_spec


def main():
    name = sys.argv[1]
    spec = DEFAULT_OFFICIAL_SOURCES[name]
    try:
        result, failures = fetch_official_spec(spec, timeout=8.0)
        print(json.dumps({
            "source_id": name, "status": "IDENTITY_TOKENS_OBSERVED",
            "resolved_url": result.url, "content_sha256": result.content_sha256,
            "content_type": result.content_type, "fallback_count": len(failures),
            "observed_at": datetime.now(UTC).isoformat(),
            "decision_authority": False,
        }, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"source_id": name, "status": "UNAVAILABLE",
                          "error_type": type(exc).__name__, "decision_authority": False}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
