# Contract Compatibility Matrix

Updated: 2026-09-02

## Current supported surface

- Engine package: `0.1.x`
- ExecutionRequest schema: `1.0`
- ExecutionResult schema: `1.0`
- Python runtime: `>=3.11`
- Canonical consumer architecture: private `riyuewuxing/touzizhuanjia` Commander V2
- Safety invariant: `public_data_only=true`, `decision_authority=false`

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
- E6 scale/governance branch acceptance is recorded in `docs/E6_RUNTIME_ACCEPTANCE.md` after the
  branch gates are frozen and promoted to `main`.
