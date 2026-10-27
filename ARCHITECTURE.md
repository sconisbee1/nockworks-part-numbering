# Schema and review notes

## Schema delta

* `product_template`: stored `nw_part_category_id`, `nw_part_type_id`,
  `nw_base_part_number`, `nw_numbering_state`, `nw_next_variant` (1–100).
  Existing template numbering names remain computed compatibility fields.
* `product_product`: existing classification, assigned flag and full-number
  columns remain; add stored related `nw_base_part_number` and integer
  `nw_variant_number` (0 for unsuffixed, 1–99 for variants). A computed display
  string renders two digits in forms; the list formatter retains integer sorting.
* `nockworks_reference_allocation`: globally unique reference, family link and
  immutable family-ID snapshot, nullable suffix (0 for base), product link and
  original-ID snapshot, retirement flag, reason and Odoo audit fields.
  Links use SET NULL so deleting a SKU/family cannot delete its reservations.
* Conversion dialog is transient; permanent review evidence lives in allocation
  records and template chatter. Chatter follows normal Odoo retention/access
  rules; the allocation ledger has no public create/write/delete path.
* SQL constraints: unique family base; ledger reference and family/suffix;
  partial live product family/suffix index; assignment/reference equality and
  range checks. `nw_default_code_namespace_unique` covers managed-format native
  references, including unnumbered/manual products and archived products.
* `nw_reserve_product_reference()` and `nw_reference_reservation` reserve native
  references at the database boundary and reject tombstone reuse. Existing
  references are seeded before enabling these protections.

Migration `19.0.2.0.0/post-migrate.py` backfills metadata/reservations only.
No product ID, issued SKU reference, stock quantity or historical relationship
is migrated. Conflicting data stops upgrade. The old per-type counter remains
in place; suffix allocation does not consume additional base sequence values.

## View strategy

Extend `product.product_template_only_form_view`,
`product.product_product_tree_view`, `product.product_search_form_view`,
`product.product_variant_easy_edit_view` and `product.product_normal_form_view`.
Keep `product.product_variant_action` and its native filtering/navigation.
The template-only parent avoids propagating template controls into variant forms.
The stock dependency supplies the native product/web dependencies; browser tests
add no production module dependency.

## Future administrator correction (not implemented)

Use a dedicated authorization group and product-bound review action, never a
writable suffix field. Require reason, old/new preview, explicit approval and
operational review for inventory, lots, manufacturing and commercial history.
Use the same family lock and ledger; reject every previously allocated suffix,
including retired/deleted allocations. Advance the high-water mark without
releasing skipped values or moving counters backward. Retire the previous
reference permanently and record actor/time, product ID, reason and approvals.

Changing a reference retains foreign-key identity but does not update printed
labels, external integrations or historical text snapshots. Such corrections
consume finite suffix capacity and can create traceability ambiguities.

## Limits requiring deployment review

* Production's installed Odoo revision, custom overrides and combined views
  must be checked in staging; tests use the official Odoo 19 Community image.
* The native list action chooses its list by view priority. Another addon can
  change that selection; the browser test proves selection in the tested stack.
* Historical material identity is a human determination, never inferred from
  attribute order or current stock.
* Upgrades cannot recover reservations for records deleted before this release.
* Database superusers and trusted server Python can bypass application security;
  client context flags and ordinary ORM/RPC/import operations cannot.
* Uninstallation is not a supported rollback: reservations are permanent data.
