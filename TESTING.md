# Testing

Run the full disposable Linux/Docker harness from a checkout with Git history:

```sh
bash tests/integration/run.sh
```

The harness builds an Odoo 19 Community + Chrome test image, installs the addon
with `mrp`, `sale_stock` and `purchase_stock`, runs model/security/stock/MRP tests
and a real browser tour, creates native dynamic variants in concurrent committed
PostgreSQL transactions, then installs the pinned old addon and upgrades its
legacy fixture twice. Logs/screenshots are retained under
`.test-runtime/artifacts/`; only harness-owned containers/network/volume are
removed. No production host, database, port or credentials are used.

The browser dependency `python3-websocket` and Chrome are test-image dependencies,
not addon dependencies. The harness fails if the browser case is skipped.
A persistent test filestore accompanies the test database for every process.

For a preconfigured Odoo test environment:

```sh
odoo -d disposable_test -i nockworks_part_numbering,mrp,sale_stock,purchase_stock \
  --without-demo=all --test-enable --test-tags /nockworks_part_numbering \
  --stop-after-init
```

The concurrency and upgrade fixture scripts run through `odoo shell` and commit
intentionally. Use only disposable databases. The concurrency test retries whole
transactions on PostgreSQL serialization/deadlock errors and asserts distinct
permanent suffixes. The upgrade fixture checks the original V200 SKU ID and
`150-01-0004`, archived independently numbered variants, ordinary references,
stock quantity, lot, MO, finished moves, BoM and sequence counter.

GitHub Actions runs the same harness on feature-branch pushes and pull requests.
Local test results are recorded in `TEST_RESULTS.md`; a workflow file is not
itself evidence that hosted CI has run.

The integrity extension additionally upgrades a clone through exact commit
3270759, reproduces old departed references/deletions, converts V200 with tracked
history under both old and current implementations, and compares all SQL guard,
function, constraint and index definitions after repeated upgrades. The optional
rpc_before_fix.py script is a deliberately successful reproduction for an isolated
2.0.0 test database only; it must not be used against production. Corrected RPC
rejection is covered by the normal model suite.
