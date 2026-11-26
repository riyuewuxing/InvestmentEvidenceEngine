import hashlib

from investment_evidence_engine.snapshot_integrity import raw_snapshot_matches


def test_all_artifacts_are_required_and_independently_rehashed():
    bodies = {"ledger": b"original ledger", "graph": b"original graph", "gaps": b"original gaps"}
    expected = {k: hashlib.sha256(v).hexdigest() for k, v in bodies.items()}
    required = frozenset(bodies)
    assert raw_snapshot_matches(bodies, expected, required=required)
    for key in required:
        assert not raw_snapshot_matches(bodies | {key: b"changed"}, expected, required=required)
        assert not raw_snapshot_matches({k: v for k, v in bodies.items() if k != key},
                                        expected, required=required)
        assert not raw_snapshot_matches(bodies, expected | {key: "x"*64}, required=required)
    assert not raw_snapshot_matches({}, {}, required=frozenset())
    assert not raw_snapshot_matches(bodies, expected | {"extra": "a"*64}, required=required)
