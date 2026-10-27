"""Before-fix proof at 3270759, against disposable old-version DB only."""
from odoo.service.model import call_kw
assert env['ir.module.module'].search([('name', '=', 'nockworks_part_numbering')], limit=1).latest_version == '19.0.2.0.0'
user = env['res.users'].create({'name': 'Integrity product editor', 'login': 'nw-rpc-probe',
    'group_ids': [(6, 0, [env.ref('base.group_user').id, env.ref('stock.group_stock_user').id, env.ref('product.group_product_manager').id])]})
model = env['product.product'].with_user(user)
model.check_access('create')
assert not user.has_group('stock.group_stock_manager')
product_id = call_kw(model, 'create', [{'name': 'RPC forged legacy assignment'}], {'context': {
    'default_nw_numbering_state': 'legacy', 'default_nw_part_number': '777-01-0099',
    'default_nw_part_number_assigned': True, 'default_default_code': '777-01-0099'}})
product = env['product.product'].browse(product_id)
assert product.nw_part_number_assigned and product.default_code == '777-01-0099'
assert product.product_tmpl_id.nw_numbering_state == 'legacy'
env.cr.commit()
print('3270759 RPC BYPASS CONFIRMED: non-manager product editor forged a legacy assignment via context defaults', flush=True)
