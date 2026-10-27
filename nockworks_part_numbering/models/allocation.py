from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ReferenceAllocation(models.Model):
    _name = 'nockworks.reference.allocation'
    _description = 'Permanent NockWorks reference allocation'
    _order = 'id'

    reference = fields.Char(required=True, readonly=True, index=True)
    family_id = fields.Many2one('product.template', ondelete='set null', readonly=True)
    family_key = fields.Integer(readonly=True, index=True)
    suffix = fields.Integer(readonly=True)
    product_id = fields.Many2one('product.product', ondelete='set null', readonly=True)
    original_product_id = fields.Integer(readonly=True)
    reason = fields.Text(readonly=True)
    retired = fields.Boolean(readonly=True)

    _reference_unique = models.Constraint('unique(reference)', 'This reference has already been issued and cannot be reused.')
    _suffix_unique = models.Constraint('unique(family_key, suffix)', 'This family suffix has already been allocated.')
    _suffix_range = models.Constraint('check(suffix IS NULL OR suffix BETWEEN 0 AND 99)', 'Variant suffix must be between 01 and 99.')

    @api.model_create_multi
    def create(self, vals_list):
        raise ValidationError(_('Reference allocations are managed automatically.'))

    def write(self, vals):
        raise ValidationError(_('Reference allocations are permanent.'))

    def unlink(self):
        raise ValidationError(_('Issued reference allocations cannot be deleted.'))

    @api.model
    def _reserve(self, template, reference, product=None, suffix=0, reason=None):
        """Private service, also used to adopt an existing reference without changing it."""
        ledger = self.sudo()
        existing = ledger.search([('reference', '=', reference)], limit=1)
        if existing:
            if existing.retired or (existing.product_id and existing.product_id != product) or (
                existing.family_key and existing.family_key != template.id
            ) or (not existing.product_id and existing.original_product_id):
                raise ValidationError(_('Reference %s is permanently reserved.', reference))
            super(ReferenceAllocation, existing).write({
                'family_id': template.id, 'family_key': template.id, 'suffix': suffix,
                'product_id': product.id if product else False,
                'original_product_id': product.id if product else False,
                'reason': reason or 'Family allocation',
            })
            return existing
        return super(ReferenceAllocation, ledger).create({
            'reference': reference, 'family_id': template.id, 'family_key': template.id,
            'suffix': suffix, 'product_id': product.id if product else False,
            'original_product_id': product.id if product else False,
            'reason': reason or 'Automatic allocation',
        })

    def _retire(self, reason):
        super(ReferenceAllocation, self.sudo()).write({'retired': True, 'reason': reason})
