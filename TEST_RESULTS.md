# Local verification — 27 October 2026

Implementation branch: `feature/product-variant-numbering`.
Baseline addon: `988dacd6ad4bb8bc6565a554a6206e2c0f1ffa75` (`19.0.1.1.0`).
Implemented addon: `19.0.2.0.0`.

## Runtime

* Official Odoo 19 Community: `19.0-20261015`.
* Odoo image digest: `sha256:27f920e002c43a1af7022a68f3cc17db71a2f9f3348800cb050721ce54893e49`.
* PostgreSQL: `16.15`.
* Chrome: `156.0.8078.47`, with python3-websocket in the test image.
* Inventory, Manufacturing, Sales/Stock and Purchase/Stock installed together.
* Isolated Docker network; no published production-facing ports or production data.

## Results

| Check | Result |
|---|---|
| Clean installation of current addon with stock/MRP/sales/purchase | Passed |
| Clean-install model and Chrome suite before final migration edge-case test | 28 tests, 0 failed, 0 errors |
| Final complete addon suite | 30 tests, 0 failed, 0 errors; browser executed, not skipped |
| Native Variants smart button → list → easy-edit form | Chrome tour succeeded |
| Separate committed PostgreSQL connections | 6 dynamic native variants through 2 simultaneous workers; suffixes 01–06, no duplicates |
| Real old-addon installation → upgrade to final implementation | Passed |
| Repeated upgrade and fixture verification | Passed |
| Python compilation in Odoo runtime | Passed |
| Bash integration harness syntax | Passed |
| Git diff whitespace check | Passed |

The model suite covers single products, ordinary references, 2/3 variants,
multiple attributes, reorder, archive/reactivate (single and multi), deletion and
recreation, copying and copy-context security, namespace collisions, permanent
ledger protections, fake RPC context flags, imports, direct attribute-line
creation, controlled conversion, exhaustion/rollback, dynamic/no-variant
attributes (including later non-variant edits), database constraints, inherited views, stock/MRP/work orders and
variant-specific BoMs. Migration tests also cover idempotent metadata adoption
and preserving unissued classification without allocating a number.

The real old-version fixture retained SKU ID 1 and `150-01-0004`, archived
independently numbered variants, `LEGACY-42`, seven tracked units, its lot, BoM,
MO, finished-move IDs and next base counter. No reference changed during either
upgrade. Concurrency serialization errors in logs are expected and retried as
whole transactions, matching Odoo's request-layer semantics.

## Evidence and limits

Local raw logs are intentionally Git-ignored: `clean-final-test.log`,
`final-regression.log`, `concurrency-final.log`, `baseline-final.log`,
`fixture-final.log`, `upgrade-final.log`, `upgrade-final-check.log`,
`repeated-upgrade.log`, and `repeated-verify.log`.

`tests/integration/run.sh` automates the same checks for Linux CI and preserves
its logs/screenshots in `.test-runtime/artifacts`. Its syntax was checked locally;
local Docker stages were invoked from PowerShell. Hosted GitHub Actions results
are separate from these local results.

Production data, installed custom NockWorks addons, external integrations and
the deployed Odoo revision were not accessed. A restored-production staging
rehearsal and separate deployment/conversion approvals remain necessary.
No merge or production deployment has occurred.

## Pre-merge integrity verification

The final expanded suite passed **67 tests**, with zero failures/errors. It adds
37 tests over the original 30, covering manual departure/reclaim, deletion,
family cascades, SQL ownership/immutability, NULL handling, private ORM/RPC access,
protected context defaults, provenance checks and repeated initialization.

Independent transactions also passed native suffix allocation, a competing
manual-reference race and rejection of an invalid final state on real COMMIT.
Both original-main and exact-3270759 intermediate databases were upgraded and
repeatedly verified after tracked V200 conversion. Detailed evidence, confirmed
before-fix failures and limits are recorded in INTEGRITY_REVIEW.md.

Raw local evidence: integrity-before.log, integrity-cascade-before.log,
integrity-rpc-327.log, integrity-context-before.log, integrity-clean.log,
integrity-release-suite.log, integrity-concurrency.log, integrity-check-main.log,
integrity-review-check.log and nw_integrity_*-verify-*.log. These logs are Git-ignored.
