"""Seed/verify conversion and departed references, for both 3270759 and current code.
Run through odoo shell in disposable integration databases. Commits are intentional.
"""
import json
import os
from odoo.exceptions import ValidationError

parameters = env['ir.config_parameter']
original = json.loads(parameters.get_param('nw.upgrade.fixture'))
if os.environ.get('NW_INTEGRITY_PHASE') == 'before':
    template = env['product.template'].browse(original['template'])
    product = env['product.product'].browse(original['product'])
    attribute = env['product.attribute'].create({'name': 'Integrity conversion material'})
    values = env['product.attribute.value'].create([{'name': name, 'attribute_id': attribute.id} for name in ('ABS', 'ABS-FR')])
    env['nockworks.variant.conversion'].create({'template_id': template.id, 'first_value_id': values[0].id,
        'confirmed': True, 'reason': 'Fixture: original seven tracked units and original MO/lot are all ABS.'}).action_confirm()
    assert product.id == original['product'] and product.default_code == '150-01-0004-01'
    template.attribute_line_ids.value_ids = values
    manual = env['product.product'].create({'name': 'Manual changed', 'default_code': '777-01-0042'})
    manual.default_code = '777-01-0043'
    cleared = env['product.product'].create({'name': 'Manual cleared', 'default_code': '777-01-0050'})
    cleared.default_code = False
    part_type = env['nockworks.part.type'].browse(original['type'])
    def family(name):
        return env['product.template'].create({'name': name, 'nw_part_category_id': part_type.category_id.id,
            'nw_part_type_id': part_type.id, 'attribute_line_ids': [(0, 0, {'attribute_id': attribute.id,
            'value_ids': [(6, 0, values.ids)]})]})
    surviving = family('Deleted combination fixture')
    deleted = surviving.product_variant_ids[0]
    deleted_id, deleted_reference = deleted.id, deleted.default_code
    deleted.unlink()
    deleted_family = family('Deleted family fixture')
    deleted_family_refs = [deleted_family.nw_base_part_number] + deleted_family.product_variant_ids.mapped('default_code')
    deleted_family_id = deleted_family.id
    version = env['ir.module.module'].search([('name', '=', 'nockworks_part_numbering')], limit=1).latest_version
    if version == '19.0.2.0.0':
        # The pre-review family cascade defect is reproduced separately. Seed
        # old completed deletions using the supported child-first route.
        deleted_family.product_variant_ids.unlink()
        if deleted_family.exists():
            deleted_family.unlink()
    else:
        deleted_family.unlink()
    references = {str(p.id): p.default_code for p in env['product.product'].with_context(active_test=False).search([])}
    ledger = env['nockworks.reference.allocation'].sudo().search([])
    ledger_ids = {a.reference: a.id for a in ledger}
    snapshot = {'original': original, 'manual': manual.id, 'cleared': cleared.id,
        'deleted_id': deleted_id, 'deleted_reference': deleted_reference,
        'deleted_family_id': deleted_family_id, 'deleted_family_refs': deleted_family_refs,
        'references': references, 'ledger_ids': ledger_ids, 'counter': part_type.next_number,
        'converted_refs': template.product_variant_ids.mapped('default_code')}
    parameters.set_param('nw.integrity.fixture', json.dumps(snapshot))
    env.cr.commit()
    print('INTEGRITY FIXTURE COMMITTED: original SKU ID retained, conversion 150-01-0004 -> 150-01-0004-01, manual changes/clear, variant/family deletion', flush=True)
else:
    snapshot = json.loads(parameters.get_param('nw.integrity.fixture'))
    current = {str(p.id): p.default_code for p in env['product.product'].with_context(active_test=False).search([])}
    assert current == snapshot['references'], (current, snapshot['references'])
    assert env['nockworks.part.type'].browse(original['type']).next_number == snapshot['counter']
    product = env['product.product'].browse(original['product'])
    assert product.default_code == '150-01-0004-01'
    assert env['stock.lot'].browse(original['lot']).product_id == product
    assert env['mrp.bom'].browse(original['bom']).product_id == product
    mo = env['mrp.production'].browse(original['mo'])
    assert mo.product_id == product and mo.move_finished_ids.ids == original['moves']
    assert env['stock.quant']._get_available_quantity(product, env.ref('stock.stock_location_stock'), lot_id=env['stock.lot'].browse(original['lot'])) == 7
    ledger = env['nockworks.reference.allocation'].sudo().search([])
    assert {a.reference: a.id for a in ledger} == snapshot['ledger_ids']
    retired_refs = ['150-01-0004', '777-01-0042', '777-01-0050', snapshot['deleted_reference']] + snapshot['deleted_family_refs']
    for reference in retired_refs:
        allocation = ledger.filtered(lambda a: a.reference == reference)
        assert len(allocation) == 1 and allocation.retired and not allocation.product_id, reference
        try:
            with env.cr.savepoint():
                env['product.product'].create({'name': 'Must not reclaim', 'default_code': reference})
        except ValidationError:
            pass
        else:
            raise AssertionError('Retired reference was reused: ' + reference)
    base = ledger.filtered(lambda a: a.reference == '150-01-0004')
    assert base.original_product_id == product.id and base.family_key == product.product_tmpl_id.id
    manual = env['product.product'].browse(snapshot['manual'])
    try:
        with env.cr.savepoint():
            manual.default_code = '777-01-0042'
    except ValidationError:
        pass
    else:
        raise AssertionError('Same SKU reclaimed departed manual reference')
    assert manual.default_code == '777-01-0043'
    for allocation in ledger.filtered(lambda a: not a.retired and a.product_id):
        assert allocation.product_id.default_code == allocation.reference
        assert allocation.product_id.product_tmpl_id.id == allocation.family_key == allocation.family_id.id
        assert allocation.product_id.id == allocation.original_product_id
    env.cr.execute("SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname LIKE 'nw_%' ORDER BY tgname")
    guard_snapshot = env.cr.fetchall()
    assert len(guard_snapshot) == 5, guard_snapshot
    env.cr.execute("SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN ('nw_default_code_namespace_unique', 'nw_reference_active_owner_unique') ORDER BY indexname")
    indexes = env.cr.fetchall()
    assert len(indexes) == 2
    env.cr.execute('''SELECT proname, pg_get_functiondef(oid) FROM pg_proc WHERE proname IN
        ('nw_reference_actor', 'nw_guard_allocation', 'nw_reserve_product_reference', 'nw_assert_product',
         'nw_assert_allocation', 'nw_assert_family', 'nw_check_numbering_integrity') ORDER BY proname''')
    functions = env.cr.fetchall()
    assert len(functions) == 7
    env.cr.execute('''SELECT c.relname, con.conname, pg_get_constraintdef(con.oid) FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid WHERE c.relname IN
        ('product_template', 'product_product', 'nockworks_reference_allocation') AND con.conname LIKE '%nw_%'
        ORDER BY c.relname, con.conname''')
    constraints = env.cr.fetchall()
    assert any(row[1] == 'nw_allocation_shape' for row in constraints)
    fingerprint = json.dumps({'triggers': guard_snapshot, 'indexes': indexes, 'functions': functions, 'constraints': constraints})
    previous = parameters.get_param('nw.integrity.guards')
    assert not previous or previous == fingerprint, 'Upgrade changed guard/index definitions'
    parameters.set_param('nw.integrity.guards', fingerprint)
    env.cr.execute('SET CONSTRAINTS ALL IMMEDIATE')
    env.cr.commit()
    print('INTEGRITY UPGRADE PASS: all IDs/references/counters preserved; base and suffix tombstones permanent; current ownership consistent; tracked stock/MO/BoM unchanged; guard definitions stable', flush=True)
