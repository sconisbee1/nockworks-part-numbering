# NockWorks Part Numbering — Odoo 19

Version `19.0.2.1.0` extends the existing addon with product-family numbering.
The runtime dependency remains `stock`; Manufacturing, Sales and Purchasing use
native `product.product.default_code` and product IDs.

## Normal workflow

Create a product, select Part Category and Part Type, configure its native
**Attributes & Variants** tab, then save. Once both classifications are present,
the existing per-type allocator generates one family base automatically. The
Generate Part Number action remains available and is idempotent.

* A single stock-managed SKU receives `CCC-TT-NNNN`.
* A family with meaningful stock variants receives `CCC-TT-NNNN-01`, `-02`, etc.
* Dynamic variants receive a number when Odoo actually creates the SKU.
* Attributes configured never to create variants do not create suffixes.

Configure initial attributes before issuing an unsuffixed SKU reference. Once
an unsuffixed number is issued, adding variant attributes requires the reviewed
conversion below, even if the product has no stock yet.

Inspect numbers through Odoo's existing **Variants** smart button. Its native
list shows attribute tags, family base, a zero-padded numerically sortable suffix,
and Internal Reference. Both native variant forms show the same information.
No suffix is an attribute, and no separate variant manager exists.

## Stable identity and references

The stored family base is `product.template.nw_base_part_number`. The existing
SKU `nw_part_number` remains a read-only compatibility mirror of authoritative
`product.product.default_code`. The native template `default_code` keeps Odoo's
computed/inverse semantics and is not the family base.

`nw_variant_number` is a permanent allocation, not an attribute encoding. A
family counter and immutable `nockworks.reference.allocation` ledger reserve
01–99. Archived SKUs retain numbers. Deleted SKUs leave permanent reservations;
recreating their combination receives a new number. Reordering attributes never
renumbers surviving products. Families never revert to unsuffixed numbering.
Copies receive a fresh base and fresh allocations.

Family row locks serialize generation, conversion and SKU creation. Counter and
ledger changes roll back with failed transactions. Odoo's request layer retries
serialization failures; external jobs must retry the entire transaction too.

Database protections include ledger reference/family-suffix uniqueness, live
SKU suffix uniqueness, reference equality and range checks, a unique index over
the managed Internal Reference namespace and a reservation trigger. Manual or
unmanaged products cannot claim a live or deleted reserved reference. Nonmanaged
references such as `LEGACY-42` keep normal Odoo editing behaviour.

UI, import, RPC and automated ORM creation use the same services. Old boolean
context flags cannot bypass restrictions. Internal capabilities use object
identity and private methods unavailable through RPC. No manual suffix override
is included, including for administrators.

## Existing products and upgrades

Installation/upgrade never renumbers an existing SKU, changes its ID, rewrites
stock/history foreign keys or automatically assigns variant suffixes.

The idempotent post-install/post-migration routine reserves existing managed
references. A sole numbered SKU is adopted into stored family metadata while
keeping its issued reference. Families with independently numbered legacy SKUs
are marked for separate review, including archived SKUs. Ordinary products are
left unchanged. Base counters are never reset or inferred from current SKUs.

Duplicate managed Internal References or inconsistent assigned references stop
the upgrade for review; they are never silently repaired. Historical references
deleted before this release cannot be reconstructed from source or current data.
Reconcile those from backups/audit records before production rollout if needed.

## Controlled single-SKU conversion

An Inventory manager opens **Review Conversion to Variants** on an issued
single-SKU template. The dialog identifies the SKU/reference and counts stock,
lot, movement, BoM, manufacturing and order usage in installed modules. Counts
are a review aid, not proof of historical material identity.

1. Inspect source records and establish which attribute value accurately
   represents all original stock and history.
2. Select that original value, document the review and explicitly confirm it.
3. The service adds only that value first, verifies the original SKU ID survives,
   retires the old reference and assigns suffix 01 in one transaction.
4. Add further values through Odoo's native Attributes & Variants tab. New SKUs
   automatically receive suffixes 02 onward.

Mixed or unknown history requires a separate operational plan. Legacy families
with multiple independently numbered SKUs are deliberately blocked from this
single-SKU conversion. There is no general consolidation tool in this release.
The ledger preserves the retired reference and review reason; template chatter
records the operator, original SKU, old/new references and chosen value.

See [DEPLOYMENT.md](DEPLOYMENT.md), [TESTING.md](TESTING.md) and
[ARCHITECTURE.md](ARCHITECTURE.md). The actual addon remains the inner
`nockworks_part_numbering/` directory; existing category/type configuration and
base allocation are retained.

## Pre-merge integrity hardening

See [INTEGRITY_REVIEW.md](INTEGRITY_REVIEW.md) for the review of commit 3270759,
confirmed defects, corrections and expanded test evidence. Leaving a manual
managed-format reference now retires it permanently, including for the same SKU.
Archival preserves ownership. The database validates the final ledger/SKU/family
state at commit, and protected RPC context defaults cannot forge assignments.
The 2.1 migration changes metadata and guards only; it never renumbers products.
