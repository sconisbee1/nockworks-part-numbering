from odoo import _, api, fields, models
from odoo.exceptions import UserError
from ..models.capability import context


class VariantConversion(models.TransientModel):
    _name = 'nockworks.variant.conversion'
    _description = 'Review existing SKU conversion'

    template_id = fields.Many2one('product.template', required=True, ondelete='cascade')
    first_value_id = fields.Many2one('product.attribute.value', string='Original SKU represents', required=True)
    reason = fields.Text(required=True, string='History review and reason')
    confirmed = fields.Boolean(string='I reviewed stock, lots, manufacturing, BoMs and order history; the selected value accurately represents the original SKU.')
    preview = fields.Text(compute='_compute_preview')
    original_sku_ids = fields.Char(string='Original SKU ID', compute='_compute_preview')
    existing_reference = fields.Char(string='Existing Internal Reference', compute='_compute_preview')
    history_usage = fields.Text(string='Historical usage', compute='_compute_preview')

    @api.depends('template_id')
    def _compute_preview(self):
        for wizard in self:
            products = wizard.template_id.with_context(active_test=False).product_variant_ids
            wizard.original_sku_ids = ', '.join(str(product_id) for product_id in products.ids)
            wizard.existing_reference = ', '.join(products.mapped('default_code') or ['None'])
            history_lines = []
            lines = ['Original SKU IDs: %s' % products.ids,
                     'Issued references: %s' % ', '.join(products.mapped('default_code') or ['None'])]
            for model, field, label in [
                ('stock.quant', 'product_id', 'Stock quant records (review quantities and locations)'),
                ('stock.lot', 'product_id', 'Lots / serials'),
                ('stock.move', 'product_id', 'Stock movements'),
                ('mrp.production', 'product_id', 'Manufacturing orders'),
                ('mrp.bom', 'product_id', 'Variant-specific BoMs'),
                ('mrp.bom.line', 'product_id', 'BoM component usages'),
                ('sale.order.line', 'product_id', 'Sales order lines'),
                ('purchase.order.line', 'product_id', 'Purchase order lines'),
            ]:
                if model in self.env:
                    count = self.env[model].sudo().with_context(active_test=False).search_count([(field, 'in', products.ids)])
                    usage_line = '%s: %s' % (label, count)
                    lines.append(usage_line)
                    history_lines.append(usage_line)
            lines.append('This review does not determine historical material identity. Review source records before confirming. No quantities or historical foreign keys will be changed.')
            wizard.preview = '\n'.join(lines)
            wizard.history_usage = '\n'.join(history_lines)

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_manager') or not self.confirmed:
            raise UserError(_('An Inventory manager must explicitly confirm the history review.'))
        with self.env.cr.savepoint():
            old, new, product_id = self.template_id.with_context(**context())._nw_convert(self.first_value_id, self.reason)
            self.template_id.message_post(body=_(
                'Approved variant conversion: SKU %(sku)s, %(old)s to %(new)s. Original value: %(value)s. Review: %(reason)s',
                sku=product_id, old=old, new=new, value=self.first_value_id.display_name, reason=self.reason))
        return {'type': 'ir.actions.act_window_close'}
