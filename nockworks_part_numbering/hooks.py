"""Idempotent metadata adoption and transactional installation of integrity guards.
No issued product reference, product ID or historical business FK is rewritten.
"""
import re
from odoo.tools import file_open

PATTERN = r'^[0-9]{3}-[0-9]{2}-[0-9]{4}(-[0-9]{2})?$'
TRIGGERS = (
    ('product_product', 'nw_reference_reservation'),
    ('product_product', 'nw_product_integrity'),
    ('product_template', 'nw_family_integrity'),
    ('nockworks_reference_allocation', 'nw_allocation_integrity'),
    ('nockworks_reference_allocation', 'nw_allocation_permanence'),
)


def initialize(env):
    env.flush_all()
    cr = env.cr
    cr.execute("SELECT set_config('nockworks.actor_uid', %s, true)", [str(env.uid)])
    # Drain already valid deferred events before replacing trigger definitions.
    # This intentionally refuses corrupt data in an already protected schema.
    cr.execute('SET CONSTRAINTS ALL IMMEDIATE')
    cr.execute('SET CONSTRAINTS ALL DEFERRED')
    cr.execute('LOCK TABLE product_template, product_product, nockworks_reference_allocation IN SHARE ROW EXCLUSIVE MODE')
    for table, trigger in TRIGGERS:
        cr.execute('DROP TRIGGER IF EXISTS %s ON %s' % (trigger, table))
    cr.execute('''SELECT default_code, array_agg(id) FROM product_product
        WHERE default_code ~ %s GROUP BY default_code HAVING count(*) > 1''', [PATTERN])
    duplicates = cr.fetchall()
    if duplicates:
        raise RuntimeError('NockWorks upgrade stopped: duplicate managed references require review: %s' % duplicates)
    cr.execute('''SELECT id FROM product_product WHERE nw_part_number_assigned
        AND (default_code IS DISTINCT FROM nw_part_number OR nw_part_number !~ %s)''', [PATTERN])
    if cr.fetchall():
        raise RuntimeError('NockWorks upgrade stopped: malformed or inconsistent issued references; no references were changed.')
    cr.execute('''UPDATE product_template template
        SET nw_part_category_id = product.nw_part_category_id, nw_part_type_id = product.nw_part_type_id
        FROM product_product product WHERE product.product_tmpl_id = template.id
          AND template.nw_numbering_state = 'none'
          AND template.nw_part_category_id IS NULL AND template.nw_part_type_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM product_product other
              WHERE other.product_tmpl_id = template.id AND other.id != product.id)''')
    cr.execute('''SELECT p.id FROM product_product p LEFT JOIN nockworks_part_type t ON t.id = p.nw_part_type_id
        WHERE p.nw_part_number_assigned AND (p.nw_part_category_id IS NULL OR t.id IS NULL
            OR t.category_id IS DISTINCT FROM p.nw_part_category_id)''')
    if cr.fetchall():
        raise RuntimeError('NockWorks upgrade stopped: assigned references have missing or inconsistent classifications; review provenance. No references were changed.')
    # Normalize historical NULL-as-false flags before active-owner indexing.
    cr.execute('UPDATE nockworks_reference_allocation SET retired = FALSE WHERE retired IS NULL')
    # Upgrade pre-review allocations without inventing or reassigning identities.
    cr.execute("UPDATE nockworks_reference_allocation SET kind = CASE WHEN suffix IS NULL THEN 'manual' WHEN suffix = 0 THEN 'base' ELSE 'variant' END")
    cr.execute('''UPDATE nockworks_reference_allocation a SET family_id = p.product_tmpl_id, family_key = p.product_tmpl_id
        FROM product_product p WHERE a.product_id = p.id AND a.family_id IS NULL AND a.family_key IS NULL
          AND a.reference = p.default_code AND NOT a.retired''')
    cr.execute('''UPDATE nockworks_reference_allocation a SET retired = TRUE,
        release_reason = COALESCE(release_reason, 'Preserved departed reference during integrity upgrade')
        WHERE NOT retired AND (
            (kind = 'manual' AND product_id IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM product_product p WHERE p.id = a.product_id AND p.default_code = a.reference))
            OR (product_id IS NULL AND original_product_id > 0)
            OR (family_key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM product_template t WHERE t.id = a.family_key)))''')
    cr.execute('''UPDATE nockworks_reference_allocation SET product_id = NULL,
        released_at = COALESCE(released_at, NOW()), released_by = COALESCE(released_by, %s),
        release_reason = COALESCE(release_reason, reason, 'Preserved historical retirement') WHERE retired''', [env.uid])
    cr.execute('''INSERT INTO nockworks_reference_allocation
        (reference, kind, family_id, family_key, product_id, original_product_id, reason, retired,
         create_uid, write_uid, create_date, write_date)
        SELECT default_code, 'manual', product_tmpl_id, product_tmpl_id, id, id,
            'Preserved existing reference; no renumbering', FALSE, %s, %s, NOW(), NOW()
        FROM product_product WHERE default_code ~ %s ON CONFLICT (reference) DO NOTHING''', [env.uid, env.uid, PATTERN])
    cr.execute('''SELECT product_tmpl_id, array_agg(id) FROM product_product
        WHERE nw_part_number_assigned GROUP BY product_tmpl_id''')
    for template_id, assigned_ids in cr.fetchall():
        cr.execute('SELECT id FROM product_product WHERE product_tmpl_id = %s', [template_id])
        all_ids = [row[0] for row in cr.fetchall()]
        cr.execute('SELECT nw_numbering_state FROM product_template WHERE id = %s', [template_id])
        if cr.fetchone()[0] != 'none':
            continue
        product = env['product.product'].browse(assigned_ids[0])
        if len(all_ids) == 1 and re.fullmatch(r'[0-9]{3}-[0-9]{2}-[0-9]{4}', product.nw_part_number or ''):
            cr.execute('''UPDATE product_template SET nw_base_part_number = %s, nw_part_category_id = %s,
                nw_part_type_id = %s, nw_numbering_state = 'single' WHERE id = %s''',
                [product.nw_part_number, product.nw_part_category_id.id or None, product.nw_part_type_id.id or None, template_id])
            cr.execute('''UPDATE nockworks_reference_allocation SET family_id = %s, family_key = %s, suffix = 0, kind = 'base'
                WHERE reference = %s AND product_id = %s AND NOT retired''', [template_id, template_id, product.nw_part_number, product.id])
            cr.execute('UPDATE product_product SET nw_base_part_number = %s WHERE id = %s', [product.nw_part_number, product.id])
        else:
            cr.execute("UPDATE product_template SET nw_numbering_state = 'legacy' WHERE id = %s", [template_id])
    cr.execute('DROP INDEX IF EXISTS nw_default_code_namespace_unique')
    cr.execute("CREATE UNIQUE INDEX nw_default_code_namespace_unique ON product_product(default_code) WHERE default_code ~ '" + PATTERN + "'")
    cr.execute('DROP INDEX IF EXISTS nw_reference_active_owner_unique')
    cr.execute('CREATE UNIQUE INDEX nw_reference_active_owner_unique ON nockworks_reference_allocation(product_id) WHERE product_id IS NOT NULL AND retired IS FALSE')
    with file_open('nockworks_part_numbering/sql/guards.sql', 'r') as source:
        cr.execute(source.read())
    # Audit the entire adopted state once, not just newly touched rows.
    cr.execute('SELECT nw_assert_family(id) FROM product_template')
    cr.execute('SELECT nw_assert_allocation(id) FROM nockworks_reference_allocation')
    env.invalidate_all()


def post_init_hook(env):
    initialize(env)
