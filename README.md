# NockWorks Part Numbering

`nockworks_part_numbering` adds permanent engineering/SKU part numbers to Odoo 18 Community without changing or reusing Odoo's accounting and inventory `product.category` hierarchy.

## Number format

Numbers use `CCC-TT-NNNN`, for example `100-03-0047`:

- `CCC`: a three-digit NockWorks Part Category code.
- `TT`: a two-digit Part Type code, unique within its category.
- `NNNN`: a per-Category/Type sequence from `0001` through `9999`.

The assigned number is written both to the module's immutable Part Number field and the SKU's standard `default_code` (Internal Reference).

## Data and SKU architecture

`nockworks.part.category` and `nockworks.part.type` are independent engineering classifications. They do not inherit from, modify, or replace `product.category`.

Odoo 18 stores `default_code` on `product.product`; `product.template.default_code` is a computed/inverse convenience field for a template with one variant. Accordingly, the authoritative NockWorks fields and allocation action are on `product.product`, so each physical variant can receive its own number. `product.template` exposes proxy fields and the same button only when it has exactly one variant. For a multi-variant template, open each Product Variant and generate its number there.

## Sequence and concurrency safety

Allocation is a single conditional PostgreSQL `UPDATE ... RETURNING` against the selected Part Type row. PostgreSQL takes a row lock for that update, so concurrent transactions cannot reserve the same value. Issuing `9999` atomically marks the sequence exhausted; later attempts raise a clear error. A database unique constraint independently protects generated part numbers.

`next_number` cannot be decreased, deletion and archival never alter it, and an exhausted sequence cannot be restarted. Failed transactions roll back both the product assignment and reservation together.

## Installation

1. Copy `nockworks_part_numbering` into a configured custom addons directory.
2. Restart Odoo and update the Apps list.
3. Install **NockWorks Part Numbering**.

The module depends only on the standard `stock` module. Installation does not assign numbers or alter existing Internal References.

## Configuration

Inventory managers configure classifications at:

`Inventory > Configuration > NockWorks Part Numbering > Part Categories / Part Types`

Codes must retain their leading zeroes and contain exactly three or two decimal digits respectively. Managers can advance `next_number`, but cannot decrease it because that could reuse an issued number. Internal users have read access so classifications are selectable on products; only Inventory managers can create or edit them.

## Normal workflow

1. Open a product with one variant, or open a specific Product Variant for a multi-variant template.
2. Select Part Category and Part Type.
3. Click **Generate Part Number**.

After assignment, the classification and number are read-only in the normal UI. Server-side checks also reject changes to the classification, assignment, generated number, or a divergent `default_code`. Products outside this numbering system retain normal Internal Reference behavior.

Duplicating a product or template never copies its assigned NockWorks number. If the source Internal Reference was the generated number, the copy's Internal Reference is cleared. Classification retention is not guaranteed by Odoo's variant regeneration and should be reviewed before generating the copy's new number.

## Tests

Run with an Odoo 18 source checkout and test database, for example:

```text
odoo-bin -d test_db --addons-path=addons,/path/to/custom-addons \
  -i nockworks_part_numbering --test-enable --stop-after-init \
  --test-tags /nockworks_part_numbering
```

The suite covers validation, uniqueness, formatting, independent sequences, copying, legacy references, exhaustion, invalid classifications, immutability, deletion/archive behavior, ordinary products, and variant-specific numbering. The allocation SQL is intentionally atomic; true two-connection concurrency is best additionally exercised in the deployment's PostgreSQL integration pipeline.
