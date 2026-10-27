"""Execute with old addon before upgrade, and current addon after upgrade."""
import json
import os

if os.environ.get('NW_UPGRADE_PHASE') == 'before':
    category = env['nockworks.part.category'].create({'name': 'Upgrade manufactured', 'code': '150'})
    part_type = env['nockworks.part.type'].create({'name': 'Body', 'code': '01', 'category_id': category.id, 'next_number': 4})
    template = env['product.template'].create({'name': 'V200 upgrade fixture', 'is_storable': True, 'tracking': 'lot',
        'nw_part_category_id': category.id, 'nw_part_type_id': part_type.id})
    template.action_generate_nw_part_number()
    product = template.product_variant_id
    lot = env['stock.lot'].create({'name': 'HISTORY-ABS', 'product_id': product.id})
    env['stock.quant']._update_available_quantity(product, env.ref('stock.stock_location_stock'), 7, lot_id=lot)
    component = env['product.product'].create({'name': 'Upgrade component', 'is_storable': True})
    bom = env['mrp.bom'].create({'product_tmpl_id': template.id, 'product_id': product.id,
        'bom_line_ids': [(0, 0, {'product_id': component.id, 'product_qty': 1})]})
    mo = env['mrp.production'].create({'product_id': product.id, 'product_qty': 2, 'bom_id': bom.id})
    mo.action_confirm()
    attribute = env['product.attribute'].create({'name': 'Legacy material'})
    values = env['product.attribute.value'].create([{'name': name, 'attribute_id': attribute.id} for name in ('ABS', 'ABS-FR')])
    multi = env['product.template'].create({'name': 'Legacy independently numbered', 'attribute_line_ids': [(0, 0, {
        'attribute_id': attribute.id, 'value_ids': [(6, 0, values.ids)]})]})
    for variant in multi.product_variant_ids:
        variant.write({'nw_part_category_id': category.id, 'nw_part_type_id': part_type.id})
        variant.action_generate_nw_part_number()
    multi.product_variant_ids[0].active = False
    ordinary = env['product.product'].create({'name': 'Untouched ordinary', 'default_code': 'LEGACY-42'})
    snapshot = {'template': template.id, 'product': product.id, 'reference': product.default_code,
        'lot': lot.id, 'bom': bom.id, 'mo': mo.id, 'moves': mo.move_finished_ids.ids,
        'multi': multi.id, 'multi_refs': {str(p.id): p.default_code for p in multi.with_context(active_test=False).product_variant_ids},
        'ordinary': ordinary.id, 'next_number': part_type.next_number, 'type': part_type.id}
    env['ir.config_parameter'].set_param('nw.upgrade.fixture', json.dumps(snapshot))
    env.cr.commit()
    print('UPGRADE FIXTURE CREATED', snapshot, flush=True)
else:
    snapshot = json.loads(env['ir.config_parameter'].get_param('nw.upgrade.fixture'))
    product = env['product.product'].browse(snapshot['product'])
    template = env['product.template'].browse(snapshot['template'])
    assert product.exists() and product.default_code == snapshot['reference'] == '150-01-0004'
    assert product.nw_variant_number == 0 and template.nw_numbering_state == 'single'
    assert template.nw_base_part_number == snapshot['reference']
    assert env['stock.lot'].browse(snapshot['lot']).product_id == product
    assert env['mrp.bom'].browse(snapshot['bom']).product_id == product
    mo = env['mrp.production'].browse(snapshot['mo'])
    assert mo.product_id == product and mo.move_finished_ids.ids == snapshot['moves']
    assert env['stock.quant']._get_available_quantity(product, env.ref('stock.stock_location_stock'), lot_id=env['stock.lot'].browse(snapshot['lot'])) == 7
    multi = env['product.template'].browse(snapshot['multi'])
    assert multi.nw_numbering_state == 'legacy'
    assert {str(p.id): p.default_code for p in multi.with_context(active_test=False).product_variant_ids} == snapshot['multi_refs']
    assert env['product.product'].browse(snapshot['ordinary']).default_code == 'LEGACY-42'
    assert env['nockworks.part.type'].browse(snapshot['type']).next_number == snapshot['next_number']
    print('UPGRADE PASS: IDs, issued references, archived variant, stock, lots, MO, moves, BoM and counters unchanged', flush=True)
