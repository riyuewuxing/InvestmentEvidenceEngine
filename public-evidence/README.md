# Fixed public-domain evidence retention

This is a narrowly scoped historical-document retention control, not permission to publish vendor data or company filings.

## BLS Employment Situation — August 2025

- Origin: U.S. Bureau of Labor Statistics. Archive: [FRASER item 701336](https://fraser.stlouisfed.org/title/employment-situation-144/august-2025-701336).
- [Exact PDF](https://fraser.stlouisfed.org/files/docs/releases/bls/bls_employnews_202508.pdf).
- Rights: [BLS copyright policy](https://www.bls.gov/opub/copyright-information.htm) states BLS publications are public domain except previously copyrighted photographs and illustrations. This is a government statistical release with BLS tables and charts. Attribution to BLS; no endorsement implied.
- Declared release: 2025-09-05 08:30 EDT. Not an independently established first-public-availability or capture timestamp.
- Observed 2026-11-26 10:33:43.735329 UTC in public run 45802410702, then 12:33:06.001861 UTC in [run 45820629764](https://github.com/riyuewuxing/InvestmentEvidenceEngine/actions/runs/45820629764) at 9a5dbdc80eab44cbc28b12fdff4bc64d68c56445.
- SHA-256: d91f1329ce9e7a13c875cdaf56ebafd1cda360a13162800833c46888fa3d0516; 559888 bytes, 40 pages. Git blob d0adb3094c323c07e5891e470222b86d5d4b29ba.
- Actual base64 chunks 0–182 were recovered from the second run; independent caller-side decoding/rehash matched. Stored original bytes are verified offline by public regression.
- Initially reported August change +22,000; subsequent archive revisions are not part of this retained object. No historical observation before 2026-11-26 claimed. Not PIT-safe, not a recommendation, not an execution authorization.

[Stored exact original](sha256/d91f1329ce9e7a13c875cdaf56ebafd1cda360a13162800833c46888fa3d0516.pdf).

## Two later original releases (same August measurement)

Both documents from the same BLS upstream; not independent surveys. Same source copyright policy applies. Each re-observation at 0401bcb3c9f467652cfaf5e79181b94dacb96e76, public run [45821037999](https://github.com/riyuewuxing/InvestmentEvidenceEngine/actions/runs/45821037999), was recovered by complete numbered base64 chunks and independently rehashed before the Git blob write.

| Declared release (ET) | August jobs | Bytes | Observed UTC (2026-11-26) | SHA-256 / stored original |
|---|---:|---:|---|---|
| 2025-11-20 08:30 EST | -4,000 | 578129 | 12:35:35.442319 | [1a2e1d55…](sha256/1a2e1d55c2a86ee7d471f957d2ffd0763a55beee95b0e2beb2106010475b46d7.pdf) |
| 2025-12-16 08:30 EST | -26,000 | 591295 | 12:35:42.932059 | [6408e381…](sha256/6408e38172c272f3d8416f01873d3bc40d11c9ceb90933feb4939830cd63f6d2.pdf) |

Source PDFs: https://fraser.stlouisfed.org/files/docs/releases/bls/bls_employnews_202509.pdf and https://fraser.stlouisfed.org/files/docs/releases/bls/bls_employnews_202511.pdf. Git blobs a506d0597bc4893bc03d31f9f1d588db80b277c1 and de4d587b867a698fef08da771ff86ad674d3fd52. Total three original files 1,729,312 bytes. Offline test reopens each actual PDF and checks original SHA, page count, parsed release identity and chain linkage. No proof of completeness beyond these three known releases, no historical capture or decision authority. Original BLS publication dates are distinct from actual observation.
