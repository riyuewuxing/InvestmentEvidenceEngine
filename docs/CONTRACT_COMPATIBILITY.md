# Contract Compatibility Matrix

Updated: 2026-09-04

## Current supported surface

- Engine package: `0.1.x`
- ExecutionRequest schema: `1.0`
- ExecutionResult schema: `1.0`
- Python runtime: `>=3.11`
- Canonical consumer architecture: private `riyuewuxing/touzizhuanjia` Commander V2
- Safety invariant: `public_data_only=true`, `decision_authority=false`
- Additive M5 operation: `MARKET_UNIVERSE` (schema envelope remains `1.0`)

## Compatibility policy

| Change | Compatibility | Required action |
|---|---|---|
| Add optional output metric/artifact metadata | backward-compatible | regression + relevant runtime test |
| Add a new OperationKind | contract extension | update both repos, dispatcher, tests, docs; pin new executor commit |
| Add optional request parameter inside an existing operation | backward-compatible only if default behavior is unchanged | operation regression |
| Rename/remove request field | breaking | new schema major/minor contract and consumer migration |
| Change canonical hash payload | breaking | coordinated request/result/admission migration |
| Change `public_data_only` or `decision_authority` invariant | forbidden | not an allowed compatibility change |
| Change PIT availability semantics | governance-sensitive | explicit migration + historical replay regression |
| Change artifact-path/hash semantics | integrity-sensitive | coordinated private admission regression |

## Pinning rule

Private consumers must record the exact Public executor commit in `ExecutionResult.executor.commit`.
A moving branch name is not sufficient provenance. Until a tag/release write surface is available,
commit SHA is the authoritative executable version pin.

## Cross-repo rule

A result is not admitted merely because the Engine workflow succeeded. The private consumer must
verify request/result binding, subject/executor provenance and observed artifact bytes. This
compatibility matrix does not weaken private `EvidenceAdmission`.

## Current accepted snapshots

- First Public vertical-slice executor: `86887ff40fee3166629f6e14d7531fe9542cc266`
- E6 scope-limited branch evidence is recorded in `docs/E6_RUNTIME_ACCEPTANCE.md` at
  `e9ba2736d22ebb15bf5ecccccf7be85e5231a9c1`; as of 2026-09-02 it has not been promoted to
  `main`.
- V2-M5 Gate1 accepted executor: `1161a8a91657b4d1e4719e513025956b1720938c`;
  subject: `riyuewuxing/touzizhuanjia@c4525244b250042e360b3cd55f3657ca89a1a5d6`.
  Gate1 is `PASS_WITH_EXPLICIT_WARNINGS`; M5 overall remains `ACCEPTANCE_PENDING`.
- Public `main` remains `db41a018447977e2203aed61239892dfbefbe1ac`. A later documentation
  follow-up commit is not an executor pin.

## V2-M5 implementation status

`MARKET_UNIVERSE` is an additive operation extension. It returns a compact public-only candidate
universe with normalized `records`, source/provider provenance, request-bound `as_of`, UTC
`retrieved_at`, quote-date quality state, listing overlap, and artifact hash. It does not return
forecast, advice, or portfolio weights. The accepted Gate1 executor is
`1161a8a91657b4d1e4719e513025956b1720938c`; its status is
`PASS_WITH_EXPLICIT_WARNINGS`, while M5 overall remains `ACCEPTANCE_PENDING`. The final remote
universe reported 5555 rows with `WARN`; AKShare primary failed, paged Sina fallback succeeded,
listing cross-check was unavailable, quote date was UNKNOWN, and downstream
`OPPORTUNITY_SCAN` was `WARN` with 20 candidates and 2 rules. Private admission of actual bytes
was WARN/verified/integrity verified/admissible, with the tamper case BLOCKed. Provider health was
successful overall but recorded AKShare daily BLOCK (`RemoteDisconnected`) and BaoStock PASS with
33 rows. Security triage was PASS with 5 sealed findings ignored, 0 unexpected findings, and 0
dependency vulnerabilities. The preceding monolithic Sina `JSONDecodeError` was fixed by bounded
paged retries. Full immutable evidence is in
`docs/V2_M5_GATE1_RUNTIME_ACCEPTANCE_2026-09-04.md`; existing E6 acceptance run facts are unchanged.

Gate1 request SHA256 is `d54eedf22a26f9a03a4b9118b96e3dec51b41d7847206d265563113c30da94e6` and
result SHA256 is `76b168935dffef49eb12514c44dd65229e19ddd815631aaebf4aa020e9aefaae`.

As part of this additive slice, `ExecutionOperation.operation_id` is restricted to an ASCII
artifact-path-safe segment (`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`); separators and traversal IDs are
rejected. This is artifact-path integrity hardening, not permission to supply arbitrary paths.

The AKShare endpoint names and public spot field contract follow the
[official data documentation](https://akshare.akfamily.xyz/data/stock/stock.html).
