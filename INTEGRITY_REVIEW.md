# PR #1 pre-merge integrity review

Reviewed baseline: `3270759` (addon `19.0.2.0.0`). Corrected addon: `19.0.2.1.0`.
The reviewed commit should not be merged unchanged. No merge or production
deployment was performed during this review.

## Confirmed findings and corrections

| Finding at 3270759 | Evidence | Correction |
|---|---|---|
| **P1: Public create RPC can forge numbering through context defaults.** The explicit-values check runs before Odoo applies `default_*` values. A product creator without Inventory-manager privileges could create a supposedly assigned legacy number. | Actual `odoo.service.model.call_kw` reproduction on an isolated exact-3270759 addon; transaction committed. `integrity-rpc-327.log`. | Reject protected identifier defaults at public create/copy boundaries; validate context-selected target templates; strip client defaults from privileged ledger creation. |
| **P2: Departed manual references are not retired.** Clearing/changing a managed-format manual Internal Reference leaves the old ledger owner active; the same SKU can reclaim it. | Failing before-fix tests for clear/change/reclaim; corrected tests verify failed reclaims roll back atomically. | Retire and detach current ownership on reference departure, with immutable identity snapshots and release audit metadata. Reclaim is forbidden even for the original SKU. |
| **P2: Ledger ownership is not fully enforced.** Template, SKU, stored base, suffix and reference can disagree; a retired converted base retains a stale current-product link. | Before-fix SQL tests accepted mismatched family and suffix data. Conversion left the old base linked as a current owner. | Deferred constraint triggers validate the final graph at commit; immediate reservation checks and immutable ledger guards protect reassignment. Conversion detaches the old base owner while keeping original IDs. |
| **P2: Private ORM helpers lack capability/access checks.** Some helpers sudo-write allocations or update counters before establishing authority. | Direct ORM calls under the public user could reserve/retire references or increment a counter; a writer could call private assignment on an unnumbered SKU. | Require the identity-only internal capability plus caller record access checks and strict allocation/family preconditions. Helpers cannot mint their own assignment authority. |
| **P2: Family cascade deletion can fail on ledger foreign keys.** The two ownership links can leave an intermediate product FK pointing at a deleted SKU. | Exact-3270759 family deletion failed with `nockworks_reference_allocation_product_id_fkey`; original trace retained in `integrity-cascade-before.log`. | Before-update ledger guard detaches the live SKU owner when either ownership FK is released, preserving a retired tombstone. Direct family-deletion regression passes. |
| **P2: Historical SQL NULL retirement flags undermine active-status queries/indexing.** Python reads NULL as false, but `retired IS FALSE` excludes it. | SQL inspection found NULL on every persisted generated allocation in the old test family. | Normalize old flags without changing references; require non-null false/true status, add a unique active-owner index and NULL-safe shape/counter checks. |

Private underscore methods were already blocked by Odoo 19's real RPC dispatcher;
that was verified with dispatcher-level tests. The public-create context-default
bypass is a separate, confirmed remote-call path. Trusted Python/DB-owner code
remains outside an ordinary client's security boundary.

## Resulting lifecycle

* Archive/reactivate: same product ID, reference and active allocation; no retirement.
* Clear/change an ordinary managed-format manual reference: retire the old claim,
  clear its live owner, retain original product/family snapshots, timestamp/user
  and reason. A new reference gets its own reservation.
* Clear/change an assigned NockWorks reference: rejected outside reviewed conversion.
* Delete a variant/family: retire affected allocations; never delete/release the
  reservation or reset the suffix/base counters.
* Family bases remain reserved even when no SKU uses the unsuffixed reference.
* Controlled V200 conversion keeps the original SKU ID and maps its reference
  from `150-01-0004` to `150-01-0004-01`; ABS-FR receives `-02` normally. The old
  base is retained as a retired reservation, with the original SKU ID snapshot.

Reservations cover issued managed-format references. Unrelated ordinary values
such as `LEGACY-42` keep normal Odoo editing behaviour. Previously unallocated
manual-format references can cause a future allocation collision; the allocator
raises an error rather than overwriting or silently skipping issued references.

## Corrective schema and migration

`19.0.2.1.0/post-migrate.py` installs the final guards and audits the complete graph.
Existing family/SKU references, IDs, quantities and business foreign keys are not
rewritten. The old 2.0 migration also uses the current idempotent initializer when
upgrading directly from the original main version.

Added ledger fields: allocation kind, release timestamp/user/reason. Retirement
is now explicitly non-null. Database guards comprise five module triggers,
seven supporting functions, permanent reference/family-suffix uniqueness, live
SKU-suffix uniqueness, a unique active-owner index and NULL-safe shape/range
checks. Cross-table constraints are deferred so valid allocation/conversion
stages can complete atomically, and invalid final state cannot commit.

Migration retires departed old manual claims and deleted-owner tombstones,
detaches previously retired owners and preserves allocation IDs. Unknown
historical family ownership is left unknown; it is not inferred from a SKU
that now holds a different reference. Malformed, inconsistent or unclassified
assigned references stop upgrade for review without being renumbered.

## Verification

* Initial targeted before-fix suite: **12 failures on 3270759**, zero test errors;
  each reproduction subsequently passed after correction.
* Exact-3270759 authenticated product-creator RPC forgery: **confirmed**, including
  a committed transaction; corrected dispatcher regression rejects it.
* Final suite: **67 passed, zero failures/errors**, including the actual Chrome
  Variants smart-button/list/easy-form tour, native variants, imports, MRP, stock,
  provenance checks, record access and lifecycle/ownership edge cases.
* Clean install: passed; original-main and exact-3270759 upgrade paths passed.
* Two repeated upgrades on each converted fixture: passed with unchanged product
  IDs/references, counters, allocation IDs and trigger/function/index/constraint
  definitions. V200's original tracked seven units, lot, BoM, MO and move IDs stayed
  attached to the original SKU.
* Six native dynamic variants allocated through two independent committed
  PostgreSQL connections: unique permanent suffixes 01–06.
* A raw suffix/ledger mismatch failed on **real COMMIT** and rolled back.
* Two simultaneous manual claimants: one committed owner, one rejected claimant,
  no duplicate references or orphan allocations.

The original GitHub Actions run for 3270759 completed successfully:
https://github.com/sconisbee1/nockworks-part-numbering/actions/runs/40562492265
The other superseded runs were cancelled, not failing implementation checks.
That green run lacked these edge cases. The updated CI harness now runs the
expanded suite, both upgrade paths, conversions with tracked history and repeated
schema-definition checks. Hosted results for the corrective commit are recorded
separately after the run completes.

## Remaining risks and final-review requirements

* Rehearse against a restored production database and the actual installed custom
  addons. Third-party server code must use native creation/public generation,
  rather than treating private helpers as an unrestricted API.
* Old reference-use history, actor/time or original family membership cannot be
  reconstructed where 3270759 did not record it. Discovered departures are marked
  at migration time. Previously reclaimed or valid-looking forged legacy numbers
  require historical audit; do not infer provenance from today's fields alone.
* Invalid legacy ownership/classification now blocks upgrade. Resolve it through
  an explicitly reviewed data procedure, never automatic renumbering.
* Database-owner SQL and trusted Python can disable protections; this release
  protects ordinary UI/import/RPC/ORM clients and detects invalid committed state.
* Deployment still requires approval, backup and staging verification. Rollback
  restores matching database, filestore and addon versions; uninstalling or merely
  reverting Python is not a safe rollback for issued identifiers.
