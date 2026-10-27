from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from .capability import require_internal


class ReferenceAllocation(models.Model):
    _name = 'nockworks.reference.allocation'
    _description = 'Permanent NockWorks reference allocation'
    _order = 'id'

    reference = fields.Char(required=True, readonly=True, index=True)
    kind = fields.Selection([('manual', 'Existing/manual namespace reference'), ('base', 'Family base'),
                             ('variant', 'Variant reference')], required=True, default='manual', readonly=True)
    family_id = fields.Many2one('product.template', ondelete='set null', readonly=True)
    family_key = fields.Integer(readonly=True, index=True)
    suffix = fields.Integer(readonly=True)
    product_id = fields.Many2one('product.product', ondelete='set null', readonly=True)
    original_product_id = fields.Integer(readonly=True, index=True)
    reason = fields.Text(readonly=True)
    retired = fields.Boolean(readonly=True, default=False, required=True)
    released_at = fields.Datetime(readonly=True)
    released_by = fields.Many2one('res.users', readonly=True, ondelete='set null')
    release_reason = fields.Text(readonly=True)

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
        require_internal(self.env)
        template = self.env['product.template'].browse(template.id)
        template.check_access('write')
        if product:
            product = self.env['product.product'].browse(product.id)
            product.check_access('write')
            if product.product_tmpl_id != template:
                raise ValidationError(_('The SKU does not belong to the allocation family.'))
        template._nw_lock()
        expected = '%s-%02d' % (template.nw_base_part_number, suffix) if suffix else reference
        kind = 'variant' if suffix else 'base'
        if suffix and (not 1 <= suffix <= 99 or reference != expected or template.nw_numbering_state != 'variants'):
            raise ValidationError(_('A suffix requires a numbered variant family and matching full reference.'))
        if not suffix:
            import re
            if not re.fullmatch(r'[0-9]{3}-[0-9]{2}-[0-9]{4}', reference or ''):
                raise ValidationError(_('Invalid NockWorks family base format.'))
        # Do not propagate client default_* metadata into the privileged ledger create.
        clean_context = {key: value for key, value in self.env.context.items() if not key.startswith('default_')}
        ledger = self.sudo().with_context(clean_context)
        existing = ledger.search([('reference', '=', reference)], limit=1)
        if existing:
            # Idempotence cannot adopt or rewrite any historical ownership.
            if (existing.retired or existing.kind != kind or existing.family_key != template.id
                    or existing.family_id != template or existing.product_id.id != (product.id if product else False)
                    or existing.suffix != suffix):
                raise ValidationError(_('Reference %s is permanently reserved.', reference))
            return existing
        return super(ReferenceAllocation, ledger).create({
            'reference': reference, 'kind': kind, 'family_id': template.id, 'family_key': template.id,
            'suffix': suffix, 'product_id': product.id if product else False,
            'original_product_id': product.id if product else False,
            'reason': reason or 'Automatic allocation', 'retired': False,
        })

    def _retire(self, reason):
        require_internal(self.env)
        if not reason:
            raise ValidationError(_('A reference retirement requires a reason.'))
        self.family_id.check_access('write')
        super(ReferenceAllocation, self.sudo()).write({
            'retired': True, 'product_id': False, 'release_reason': reason,
            'released_at': fields.Datetime.now(), 'released_by': self.env.uid,
        })
