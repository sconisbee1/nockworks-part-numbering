# Deployment and rollback — approval required

No production deployment is performed by this change. Confirm actual Compose
service names, database name, addon mounts and the deployed Odoo revision before
using these steps. The existing INSTALL_ODOO19.md explains the inner-addon mount.

## Preflight in a restored staging database

1. Record the current addon commit/version, Odoo image digest and addon mounts.
2. Stop/suspend writes and scheduled jobs for the production upgrade window.
3. Take and verify a complete PostgreSQL backup and matching filestore backup.
   Test restoration before deployment. Preserve the old addon image/checkout.
4. Restore the backup into isolated staging; block outbound integrations/jobs.
5. Audit active and archived SKUs, duplicate managed-format Internal References,
   assignment/reference mismatches, classifications, counters and any known
   deleted historical references. Preserve an ID/reference and stock snapshot.
6. Test the upgrade and regression suite against that restored data. Resolve
   reported conflicts only through a separately reviewed data correction.

## Approved deployment window

1. Mount the reviewed inner `nockworks_part_numbering` directory at the existing
   extra-addons location; preserve every other addon and volume.
2. With other Odoo workers/jobs stopped, run a single upgrade process using the
   existing configuration: `odoo -d <database> -u nockworks_part_numbering
   --stop-after-init --no-http`. Supply actual database connectivity/config.
3. Review logs for successful migration and absence of failed constraints.
4. Compare all pre-existing product IDs/references, counters, stock quantities,
   lots, moves, MOs and BoM relationships against the snapshot. No SKU reference
   should change merely from upgrade.
5. Restart normal workers and verify native template/variant list/easy/full
   forms, reference search, permissions and archive/reactivation in staging.
6. Verify new variants in an approved test family. Convert a real existing SKU
   only after its separate history review and explicit conversion approval.
7. Retain backups, snapshots, reviewed code and test evidence with the release.

## Rollback

If upgrade fails, keep workers stopped, inspect the error and verify transaction
rollback. Do not retry by changing references automatically or dropping guards.

After a successful upgrade or any issued suffix/conversion, reverting Python
alone is insufficient. Stop writes, preserve a forensic backup of the current
state, then restore the matching pre-upgrade database, filestore and old addon
revision together. Verify IDs/references/quantities before restarting services.
Account explicitly for transactions and issued external labels since the backup;
never silently reuse a reference already issued outside the restored database.
For a busy system, prefer a reviewed forward fix to losing post-upgrade business
transactions. Do not uninstall the addon as a rollback mechanism.
