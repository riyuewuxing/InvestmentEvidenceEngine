# Data License, Redistribution, and Artifact Retention Policy

Updated: 2026-09-02

## Purpose

`InvestmentEvidenceEngine` is a public research executor. Public code licensing does not imply
that data returned by an upstream website or data service may be republished without restriction.

## Conservative default

1. Raw bulk market/company datasets are transient runner inputs, not repository assets.
2. The Engine should retain compact derived evidence: metrics, small excerpts required for
   verification, hashes, provenance, benchmark reports, and charts.
3. Large raw datasets, caches, and provider dumps must not be committed to Git.
4. Public workflow artifacts should use the shortest practical retention period.
   Current policy: normal evidence <= 7 days; scale benchmark artifacts <= 3 days.
5. Before adding a new provider, record both:
   - software/package license;
   - upstream data/service terms or redistribution limitations.
6. If redistribution rights are unclear, treat raw redistribution as **not approved**.
7. Tushare credentials/tokens must never enter this Public repository.

## Current provider posture

### AKShare

AKShare's code repository is MIT-licensed, while its own project statement describes provided
data as intended for academic research/reference and warns about data risk/interface removal.
Therefore this project does not interpret the MIT software license as a blanket license to
redistribute every upstream dataset fetched through AKShare.

### BaoStock

Package/client code licensing and upstream data rights are separate questions. Use the service
for research computation, retain compact derived evidence, and avoid bulk republication unless
the underlying rights are separately established.

### Tushare

Tushare is governed by its own user agreement and account/service terms. This Public Engine
must not embed a token, mirror bulk Tushare data, or assume account access conveys redistribution
rights.

### Exchange / regulator sources

SSE, SZSE, CSRC and CNINFO material is used as official evidence with source URL, retrieval
context and content hash. The Engine should preserve only the material needed for evidence and
not act as a general document mirror.

## GitHub Actions storage

The Engine intentionally sets short retention in workflow YAML to reduce storage and
redistribution exposure.

## Review trigger

Re-review this policy before:
- adding a new provider;
- publishing a bulk dataset;
- increasing artifact retention;
- changing from research-only to any commercial distribution model;
- exposing provider-derived data through a public API.
