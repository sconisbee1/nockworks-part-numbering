# RFQ product creation fix — 19.0.2.1.2

Odoo 19 calls product.product.write() from its sales-price onchange on a NewId.
The old family lock tested recordset truthiness, then generated IN () from an
unsaved template. The new regression reproduces that exact PostgreSQL SyntaxError
against 2e12439.

## Changes

- Filter family locks to actual saved IDs before access checks, flushing, SQL or
  cache invalidation. NewId(origin=...) is also excluded: .ids can expose its
  origin and is not a sufficient persistence test.
- Apply pseudo-record writes with Odoo update() in the form cache, for both the
  variant and delegated template. Never substitute _origin or allocate a number
  for an unsaved record. Empty writes safely return.
- Only saved templates enter the allocation service. Normal create()/write()
  still enforce classification, reference immutability, sorted FOR UPDATE locks,
  the atomic classification counter and permanent allocation ledger.
- Keep identifier injection checks on pseudo-records as well as persisted ORM
  calls. Imports/RPC use the same persisted checks and database protections.
- No schema, SQL trigger, constraint, migration, core or unrelated addon changes.
  Existing codes are not renumbered. No manual overrides added.

## Verification — 29 October 2026

The complete existing Docker integration harness passed against Odoo 19 Community
with stock, mrp, sale_stock and purchase_stock installed:

- Clean install: **74 tests, 0 failed, 0 errors**.
- Native RFQ browser tour: Create and Edit, sales-price/cost onchange, product
  save, selection into the purchase line and completed RFQ save.
- Native Variants smart button/list/form browser tour.
- Inventory Form creation; RFQ product Form creation with classification defaults;
  subsequent editing; empty/new/origin pseudo-records; category onchange;
  protected identifier rejection; existing allocation/stock/manufacturing tests.
- Two simultaneous connections: six dynamic native variants (suffixes 01–06),
  distinct base numbers for simultaneous new products, duplicate manual-reference
  race rejected and invalid deferred ownership rejected on real COMMIT.
- Upgrade from original main and exact 3270759; repeated upgrades preserve
  IDs, references, stock/MO/BoM relationships, counters and SQL guard definitions.
- Before-fix reproduction: the new pseudo-record test fails with WHERE id IN ().
- Python compilation and git diff whitespace checks passed.

The Windows run used the existing tests/integration/run.sh with only its local
root path adapted for Git Bash; no test semantics were changed. Raw logs are
retained locally in .test-runtime/artifacts and rfq-*.log (ignored by Git).
Hosted CI results and production verification are separate evidence.

## Deployment and rollback

Use the established Compose services in /home/ubuntu/odoo19 and the existing
inner addon at addons/nockworks/nockworks_part_numbering. Do not uninstall it.

1. Stop web workers/jobs for a consistent backup. Preserve the deployed addon.
2. Take a custom-format PostgreSQL dump and matching NW-Flow filestore archive;
   checksum them, compare archived filestore content, restore the database into
   an isolated verification database and compare business-data fingerprints.
3. Upgrade the restored database using the candidate addon, no HTTP/cron, with
   an isolated matching filestore. Run the RFQ Form smoke in a transaction that
   is rolled back. Compare all existing product IDs/codes, allocations, counters
   and stock/manufacturing/purchase/sales table fingerprints.
4. Replace only this addon and upgrade nockworks_part_numbering in NW-Flow with
   other workers stopped. Verify installed version 19.0.2.1.2 and deployed source
   hashes, run the rollback-only RFQ smoke, compare the same fingerprints, then
   start web and check internal/public HTTP and the native RFQ dialog.
5. Preserve backups and logs under backups/nw-rfq-<UTC timestamp>. Rollback before
   writes resume uses the matching old addon, database and filestore. Keep web
   stopped during restoration. Restore with pg_restore --exit-on-error and use
   the previous image/config; verify fingerprints before starting web. Never
   blindly restore over post-deployment business transactions: retain a forensic
   backup and prefer a forward fix. Never reuse externally issued references.

No production deployment is implied by the test results above. Record the actual
release hash, backup location and live checks separately after deployment.