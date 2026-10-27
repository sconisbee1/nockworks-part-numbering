#!/usr/bin/env bash
# Disposable integration environment only. Requires Docker, Git and Bash.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
root="$PWD"
suite="nw-variants-${GITHUB_RUN_ID:-local}-$$"
network="$suite-net"
db="$suite-db"
files="$suite-files"
password="isolated-test-only"
image="nw-odoo19-test"
artifacts="$root/.test-runtime/artifacts"
baseline="$root/.test-runtime/baseline"
review="$root/.test-runtime/pr327"
mkdir -p "$artifacts" "$baseline" "$review"
chmod 777 "$artifacts"
cleanup() {
    docker rm -f "$db" >/dev/null 2>&1 || true
    docker volume rm "$files" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker build -t "$image" -f tests/integration/Dockerfile .
docker network create "$network"
docker volume create "$files"
docker run -d --name "$db" --network "$network" -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=postgres postgres:16
for attempt in {1..60}; do
    if docker exec "$db" pg_isready -U odoo; then break; fi
    sleep 1
done
run_odoo() {
    docker run --rm -i --shm-size=1g --network "$network" -e HOST="$db" -e USER=odoo -e PASSWORD="$password" -e NW_INTEGRITY_PHASE="${NW_INTEGRITY_PHASE:-after}" \
        -v "$root:/mnt/extra-addons:ro" -v "$files:/var/lib/odoo" -v "$artifacts:/mnt/test-artifacts" "$image" odoo "$@"
}
run_odoo -d nw_clean -i nockworks_part_numbering,mrp,sale_stock,purchase_stock --without-demo=all \
    --test-enable --test-tags /nockworks_part_numbering --stop-after-init --http-port=8079 \
    --screenshots=/mnt/test-artifacts 2>&1 | tee "$artifacts/clean-install.log"
if grep -Eq 'skipped TestNativeVariantUI|[1-9][0-9]* failed,|[1-9][0-9]* error\(s\)' "$artifacts/clean-install.log"; then exit 1; fi
run_odoo shell -d nw_clean --no-http < tests/integration/concurrency.py 2>&1 | tee "$artifacts/concurrency.log"
grep -q 'CONCURRENCY PASS' "$artifacts/concurrency.log"
git archive 988dacd6ad4bb8bc6565a554a6206e2c0f1ffa75 | tar -x -C "$baseline"
docker run --rm --network "$network" -e HOST="$db" -e USER=odoo -e PASSWORD="$password" \
    -v "$baseline:/mnt/extra-addons:ro" -v "$files:/var/lib/odoo" "$image" odoo -d nw_upgrade \
    -i nockworks_part_numbering,mrp,sale_stock,purchase_stock --without-demo=all --stop-after-init 2>&1 | tee "$artifacts/old-install.log"
docker run --rm -i --network "$network" -e HOST="$db" -e USER=odoo -e PASSWORD="$password" -e NW_UPGRADE_PHASE=before \
    -v "$baseline:/mnt/old-addons:ro" -v "$files:/var/lib/odoo" "$image" odoo shell -d nw_upgrade \
    --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/old-addons --no-http \
    < tests/integration/upgrade_fixture.py 2>&1 | tee "$artifacts/old-fixture.log"
# Clone the pristine original-version fixture, then upgrade only that clone to
# the exact pre-review PR commit, so 2.0.0 -> 2.1.0 is tested independently.
docker exec "$db" createdb -U odoo -T nw_upgrade nw_review_upgrade
docker run --rm --user root --entrypoint sh -v "$files:/var/lib/odoo" "$image" -c \
    'if [ -d /var/lib/odoo/filestore/nw_upgrade ]; then cp -a /var/lib/odoo/filestore/nw_upgrade /var/lib/odoo/filestore/nw_review_upgrade; fi'
git archive 3270759 | tar -x -C "$review"
docker run --rm --network "$network" -e HOST="$db" -e USER=odoo -e PASSWORD="$password" \
    -v "$review:/mnt/extra-addons:ro" -v "$files:/var/lib/odoo" "$image" odoo -d nw_review_upgrade \
    -u nockworks_part_numbering --stop-after-init 2>&1 | tee "$artifacts/review-old-upgrade.log"
docker run --rm -i --network "$network" -e HOST="$db" -e USER=odoo -e PASSWORD="$password" -e NW_INTEGRITY_PHASE=before \
    -v "$review:/mnt/extra-addons:ro" -v "$files:/var/lib/odoo" "$image" odoo shell -d nw_review_upgrade --no-http \
    < tests/integration/integrity_fixture.py 2>&1 | tee "$artifacts/review-old-fixture.log"
run_odoo -d nw_upgrade -u nockworks_part_numbering --stop-after-init 2>&1 | tee "$artifacts/upgrade.log"
run_odoo shell -d nw_upgrade --no-http < tests/integration/upgrade_fixture.py 2>&1 | tee "$artifacts/upgrade-verification.log"
grep -q 'UPGRADE PASS' "$artifacts/upgrade-verification.log"
# Repeated upgrade must also preserve references and allocation state.
run_odoo -d nw_upgrade -u nockworks_part_numbering --stop-after-init 2>&1 | tee "$artifacts/repeated-upgrade.log"
run_odoo shell -d nw_upgrade --no-http < tests/integration/upgrade_fixture.py 2>&1 | tee "$artifacts/repeated-verification.log"
grep -q 'UPGRADE PASS' "$artifacts/repeated-verification.log"
# Convert the current-version fixture too, with tracked stock and MO history.
NW_INTEGRITY_PHASE=before run_odoo shell -d nw_upgrade --no-http < tests/integration/integrity_fixture.py \
    2>&1 | tee "$artifacts/current-conversion.log"
for database in nw_upgrade nw_review_upgrade; do
    for iteration in 1 2; do
        run_odoo -d "$database" -u nockworks_part_numbering --stop-after-init \
            2>&1 | tee "$artifacts/$database-upgrade-$iteration.log"
        run_odoo shell -d "$database" --no-http < tests/integration/integrity_fixture.py \
            2>&1 | tee "$artifacts/$database-integrity-$iteration.log"
        grep -q 'INTEGRITY UPGRADE PASS' "$artifacts/$database-integrity-$iteration.log"
    done
done
printf 'All NockWorks integration checks passed. Evidence: %s\n' "$artifacts"
