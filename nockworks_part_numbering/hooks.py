"""Idempotent metadata adoption. Never changes an issued SKU reference or ID."""
import re

PATTERN = r'^[0-9]{3}-[0-9]{2}-[0-9]{4}(-[0-9]{2})?$'


def initialize(env):
    cr = env.cr
    cr.execute('''SELECT default_code, array_agg(id) FROM product_product
        WHERE default_code ~ %s GROUP BY default_code HAVING count(*) > 1''', [PATTERN])
    duplicates = cr.fetchall()
    if duplicates:
        raise RuntimeError('NockWorks upgrade stopped: duplicate managed references require review: %s' % duplicates)
    cr.execute('''SELECT id FROM product_product WHERE nw_part_number_assigned
        AND default_code IS DISTINCT FROM nw_part_number''')
    if cr.fetchall():
        raise RuntimeError('NockWorks upgrade stopped: assigned references differ from Internal Reference. Review data; no references were changed.')
    # Preserve the old single-SKU classification proxies as family metadata,
    # including products not yet numbered. SQL backfill must not run allocation.
    cr.execute('''UPDATE product_template template
        SET nw_part_category_id = product.nw_part_category_id,
            nw_part_type_id = product.nw_part_type_id
        FROM product_product product
        WHERE product.product_tmpl_id = template.id
          AND template.nw_numbering_state = 'none'
          AND template.nw_part_category_id IS NULL AND template.nw_part_type_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM product_product other
              WHERE other.product_tmpl_id = template.id AND other.id != product.id)''')
    # Reserve existing managed-namespace references, including manual references.
    cr.execute('''INSERT INTO nockworks_reference_allocation
        (reference, product_id, original_product_id, reason, retired, create_uid, write_uid, create_date, write_date)
        SELECT default_code, id, id, 'Preserved existing reference; no renumbering', FALSE, %s, %s, NOW(), NOW()
        FROM product_product WHERE default_code ~ %s
        ON CONFLICT (reference) DO NOTHING''', [env.uid, env.uid, PATTERN])
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
            cr.execute('''UPDATE nockworks_reference_allocation SET family_id = %s, family_key = %s, suffix = 0
                WHERE reference = %s''', [template_id, template_id, product.nw_part_number])
            cr.execute('UPDATE product_product SET nw_base_part_number = %s WHERE id = %s', [product.nw_part_number, product.id])
        else:
            cr.execute("UPDATE product_template SET nw_numbering_state = 'legacy' WHERE id = %s", [template_id])
    # A partial index covers collisions with unnumbered/manual products too.
    cr.execute("CREATE UNIQUE INDEX IF NOT EXISTS nw_default_code_namespace_unique ON product_product(default_code) WHERE default_code ~ '" + PATTERN + "'")
    cr.execute('''CREATE OR REPLACE FUNCTION nw_reserve_product_reference() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE allocation nockworks_reference_allocation%%ROWTYPE;
    BEGIN
        IF NEW.default_code IS NULL OR NEW.default_code !~ '%s' THEN RETURN NEW; END IF;
        INSERT INTO nockworks_reference_allocation
            (reference, product_id, original_product_id, reason, retired, create_date, write_date)
            VALUES (NEW.default_code, NEW.id, NEW.id, 'Internal Reference reservation', FALSE, NOW(), NOW())
            ON CONFLICT (reference) DO NOTHING;
        SELECT * INTO allocation FROM nockworks_reference_allocation WHERE reference = NEW.default_code FOR UPDATE;
        IF allocation.retired OR allocation.product_id IS DISTINCT FROM NEW.id THEN
            RAISE EXCEPTION 'NockWorks reference %% is permanently reserved', NEW.default_code USING ERRCODE = '23505', CONSTRAINT = 'nw_reference_reserved';
        END IF;
        RETURN NEW;
    END; $$''' % PATTERN)
    cr.execute('DROP TRIGGER IF EXISTS nw_reference_reservation ON product_product')
    cr.execute('''CREATE TRIGGER nw_reference_reservation AFTER INSERT OR UPDATE OF default_code ON product_product
        FOR EACH ROW EXECUTE FUNCTION nw_reserve_product_reference()''')
    env.invalidate_all()


def post_init_hook(env):
    initialize(env)
