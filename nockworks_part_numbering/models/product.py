from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from .capability import context, internal
from .errors import reference_errors

CLASSIFICATION = ('nw_part_category_id', 'nw_part_type_id')
SKU_PROTECTED = ('nw_part_number', 'nw_part_number_assigned', 'nw_variant_number')
FAMILY_PROTECTED = ('nw_base_part_number', 'nw_numbering_state', 'nw_next_variant')


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # Keep the existing stored SKU columns for legacy independently numbered variants.
    nw_part_category_id = fields.Many2one('nockworks.part.category', string='Part Category', ondelete='restrict', index=True)
    nw_part_type_id = fields.Many2one('nockworks.part.type', string='Part Type', ondelete='restrict', index=True)
    nw_part_number = fields.Char(string='Full NockWorks Part Number', readonly=True, copy=False, index=True)
    nw_part_number_assigned = fields.Boolean(readonly=True, copy=False, default=False, index=True)
    nw_base_part_number = fields.Char(related='product_tmpl_id.nw_base_part_number', store=True, index=True)
    nw_variant_number = fields.Integer(string='Variant Sequence Number', readonly=True, copy=False, index=True)
    nw_variant_suffix = fields.Char(string='Variant Suffix', compute='_compute_nw_suffix')

    _nw_part_number_unique = models.Constraint('unique(nw_part_number)', 'The NockWorks part number must be unique.')
    _nw_assignment_consistent = models.Constraint(
        'check((nw_part_number_assigned AND nw_part_number IS NOT NULL) OR '
        '(NOT nw_part_number_assigned AND nw_part_number IS NULL))',
        'The NockWorks assignment flag and part number must be consistent.')
    _nw_reference_consistent = models.Constraint(
        'check(NOT nw_part_number_assigned OR default_code IS NOT DISTINCT FROM nw_part_number)',
        'Internal Reference must match the assigned NockWorks number.')
    _nw_suffix_range = models.Constraint('check(nw_variant_number BETWEEN 0 AND 99)', 'Variant suffix must be between 01 and 99.')
    _nw_suffix_unique = models.UniqueIndex('(product_tmpl_id, nw_variant_number) WHERE nw_variant_number > 0')

    @api.depends('nw_variant_number')
    def _compute_nw_suffix(self):
        for product in self:
            product.nw_variant_suffix = '%02d' % product.nw_variant_number if product.nw_variant_number else False

    @api.constrains(*CLASSIFICATION)
    def _check_part_classification(self):
        for product in self:
            if product.nw_part_type_id and product.nw_part_type_id.category_id != product.nw_part_category_id:
                raise ValidationError(_('The selected Part Type does not belong to the selected Part Category.'))

    @api.onchange('nw_part_category_id')
    def _onchange_nw_part_category_id(self):
        for product in self:
            if not product.nw_part_number_assigned and product.nw_part_type_id.category_id != product.nw_part_category_id:
                product.nw_part_type_id = False

    @api.model_create_multi
    @reference_errors
    def create(self, vals_list):
        trusted = internal(self.env)
        if not trusted:
            for vals in vals_list:
                if any(vals.get(key) for key in SKU_PROTECTED + FAMILY_PROTECTED):
                    raise ValidationError(_('NockWorks identifiers are allocated automatically.'))
                if vals.get('product_tmpl_id'):
                    template = self.env['product.template'].browse(vals['product_tmpl_id'])
                    template._nw_lock()
                    if template.nw_numbering_state in ('single', 'legacy'):
                        raise UserError(_('Use controlled conversion before creating variants for an issued single SKU or legacy family.'))
                    for key in CLASSIFICATION:
                        if key in vals and vals[key] != template[key].id and template.nw_base_part_number:
                            raise ValidationError(_('Variant classification must match its family.'))
        products = super(ProductProduct, self.with_context(**context())).create(vals_list)
        if not trusted:
            for product in products:
                template = product.product_tmpl_id
                if not template.nw_base_part_number and product.nw_part_category_id and product.nw_part_type_id:
                    template.with_context(**context()).write({key: product[key].id for key in CLASSIFICATION})
                template._nw_ensure_numbered()
        return products.with_env(self.env)

    @reference_errors
    def write(self, vals):
        if internal(self.env):
            return super().write(vals)
        if any(key in vals for key in SKU_PROTECTED):
            raise ValidationError(_('Assigned numbers and suffixes cannot be edited.'))
        self.product_tmpl_id._nw_lock()
        for product in self:
            if product.nw_part_number_assigned:
                if 'default_code' in vals and vals['default_code'] != product.nw_part_number:
                    raise ValidationError(_('Internal Reference cannot differ from the assigned NockWorks number.'))
                if 'product_tmpl_id' in vals and vals['product_tmpl_id'] != product.product_tmpl_id.id:
                    raise ValidationError(_('An issued SKU cannot be moved to another family.'))
                if any(key in vals and vals[key] != product[key].id for key in CLASSIFICATION):
                    raise ValidationError(_('Issued classifications are immutable.'))
            if product.product_tmpl_id.nw_numbering_state == 'legacy' and 'product_template_attribute_value_ids' in vals:
                raise UserError(_('Resolve this legacy family before changing variant identities.'))
            if product.product_tmpl_id.nw_numbering_state == 'single' and 'product_template_attribute_value_ids' in vals:
                raise UserError(_('Use controlled conversion before changing an issued SKU combination.'))
        result = super().write(vals)
        if any(key in vals for key in CLASSIFICATION):
            for product in self:
                if not product.product_tmpl_id.nw_base_part_number:
                    product.product_tmpl_id.write({key: product[key].id for key in CLASSIFICATION})
        return result

    def unlink(self):
        self.product_tmpl_id._nw_lock()
        return super().unlink()

    @reference_errors
    def action_generate_nw_part_number(self):
        self.ensure_one()
        return self.product_tmpl_id.action_generate_nw_part_number()

    def _nw_assign(self, reference, suffix=0):
        self.ensure_one()
        template = self.product_tmpl_id
        self.with_context(**context()).write({
            'nw_part_category_id': template.nw_part_category_id.id,
            'nw_part_type_id': template.nw_part_type_id.id,
            'nw_part_number': reference, 'nw_part_number_assigned': True,
            'default_code': reference, 'nw_variant_number': suffix,
        })

    def _nw_allocate_suffix(self):
        self.ensure_one()
        template = self.product_tmpl_id
        template._nw_lock()
        self.invalidate_recordset(list(SKU_PROTECTED) + ['default_code'])
        if self.nw_part_number_assigned:
            return
        if self.default_code:
            raise UserError(_('Existing reference %s requires reviewed conversion.', self.default_code))
        self.env.cr.execute('''UPDATE product_template SET nw_next_variant = nw_next_variant + 1
            WHERE id = %s AND nw_next_variant BETWEEN 1 AND 99 RETURNING nw_next_variant - 1''', [template.id])
        row = self.env.cr.fetchone()
        template.invalidate_recordset(['nw_next_variant'])
        if not row:
            raise UserError(_('Variant suffix range exhausted for %s (maximum 99; issued suffixes are never reused).', template.nw_base_part_number))
        suffix = row[0]
        reference = '%s-%02d' % (template.nw_base_part_number, suffix)
        self.env['nockworks.reference.allocation']._reserve(template, reference, self, suffix)
        self._nw_assign(reference, suffix)

    def copy_data(self, default=None):
        defaults = dict(default or {})
        defaults.update({key: False for key in SKU_PROTECTED})
        defaults['default_code'] = False
        return super().copy_data(default=defaults)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nw_part_category_id = fields.Many2one('nockworks.part.category', string='Part Category', ondelete='restrict', index=True)
    nw_part_type_id = fields.Many2one('nockworks.part.type', string='Part Type', ondelete='restrict', index=True)
    nw_base_part_number = fields.Char(string='Base NockWorks Part Number', readonly=True, copy=False, index=True)
    nw_numbering_state = fields.Selection([
        ('none', 'Unnumbered'), ('single', 'Issued single SKU'),
        ('variants', 'Variant family'), ('legacy', 'Legacy review required')], default='none', required=True, readonly=True, copy=False)
    nw_next_variant = fields.Integer(default=1, readonly=True, copy=False)
    # Preserve field names consumed by existing views/integrations, without proxying default_code.
    nw_part_number = fields.Char(related='nw_base_part_number', string='Part Number (compatibility)')
    nw_part_number_assigned = fields.Boolean(compute='_compute_nw_assigned')
    _nw_base_unique = models.Constraint('unique(nw_base_part_number)', 'Family base numbers must be unique.')
    _nw_counter_range = models.Constraint('check(nw_next_variant BETWEEN 1 AND 100)', 'Invalid variant counter.')

    @api.depends('nw_base_part_number')
    def _compute_nw_assigned(self):
        for template in self:
            template.nw_part_number_assigned = bool(template.nw_base_part_number)

    @api.constrains(*CLASSIFICATION)
    def _check_nw_classification(self):
        for template in self:
            if template.nw_part_type_id and template.nw_part_type_id.category_id != template.nw_part_category_id:
                raise ValidationError(_('The selected Part Type does not belong to the selected Part Category.'))

    def _nw_lock(self):
        """Serialize family operations; Odoo retries serialization failures at RPC boundary."""
        if self:
            self.flush_recordset(list(FAMILY_PROTECTED))
            self.env.cr.execute('SELECT id FROM product_template WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.invalidate_recordset(list(FAMILY_PROTECTED) + list(CLASSIFICATION))

    @api.model_create_multi
    @reference_errors
    def create(self, vals_list):
        trusted = internal(self.env)
        if not trusted and any(any(vals.get(key) for key in FAMILY_PROTECTED + ('nw_part_number', 'nw_part_number_assigned')) for vals in vals_list):
            raise ValidationError(_('Family identifiers are allocated automatically.'))
        templates = super(ProductTemplate, self.with_context(**context())).create(vals_list)
        if not trusted:
            templates._nw_ensure_numbered()
        return templates.with_env(self.env)

    @reference_errors
    def write(self, vals):
        if internal(self.env):
            return super().write(vals)
        if any(key in vals for key in FAMILY_PROTECTED + ('nw_part_number', 'nw_part_number_assigned')):
            raise ValidationError(_('Family identifiers and counters cannot be edited.'))
        self._nw_lock()
        for template in self:
            if template.nw_numbering_state != 'none' and any(key in vals and vals[key] != template[key].id for key in CLASSIFICATION):
                raise ValidationError(_('Issued family classifications are immutable.'))
            if template.nw_numbering_state in ('single', 'legacy') and 'attribute_line_ids' in vals:
                raise UserError(_('Use controlled conversion before changing attributes of an issued single SKU. Legacy multi-SKU families require separate review.'))
        result = super().write(vals)
        # Explicit classification changes opt an unnumbered family into numbering.
        if any(key in vals for key in CLASSIFICATION):
            self._nw_ensure_numbered()
        return result

    def _create_variant_ids(self):
        if not internal(self.env):
            self._nw_lock()
            unsafe = self.filtered(lambda t: t.nw_numbering_state == 'legacy' or (t.nw_numbering_state == 'single' and (t._nw_has_variants() or len(t.with_context(active_test=False).product_variant_ids) != 1)))
            if unsafe:
                raise UserError(_('Use controlled conversion before regenerating issued single-SKU or legacy variants.'))
        result = super()._create_variant_ids()
        if not internal(self.env):
            self._nw_ensure_numbered()
        return result

    def _nw_has_variants(self):
        self.ensure_one()
        return any(line.attribute_id.create_variant != 'no_variant' and len(line.value_ids) > 1 for line in self.attribute_line_ids)

    def _nw_ensure_numbered(self):
        for template in self.sorted('id'):
            template._nw_lock()
            if template.nw_numbering_state == 'legacy':
                continue
            products = template.with_context(active_test=False).product_variant_ids.sorted('id')
            if not template.nw_base_part_number:
                if not template.nw_part_category_id or not template.nw_part_type_id:
                    continue
                if products.filtered(lambda p: p.nw_part_number or p.default_code):
                    raise UserError(_('Existing SKU references require reviewed adoption; they will not be overwritten.'))
                part_type = template.nw_part_type_id
                number = part_type._allocate_next_number()
                base = '%s-%s-%04d' % (template.nw_part_category_id.code, part_type.code, number)
                variant_family = template._nw_has_variants() or len(products) > 1
                state = 'variants' if variant_family else 'single'
                self.env['nockworks.reference.allocation']._reserve(template, base, products[:1] if not variant_family else None)
                template.with_context(**context()).write({'nw_base_part_number': base, 'nw_numbering_state': state})
                if not variant_family and products:
                    products._nw_assign(base)
            if template.nw_numbering_state == 'variants':
                for product in products:
                    product._nw_allocate_suffix()

    @reference_errors
    def action_generate_nw_part_number(self):
        self.ensure_one()
        self.check_access('write')
        if not self.nw_part_category_id or not self.nw_part_type_id:
            raise UserError(_('Select Part Category and Part Type first.'))
        self._nw_ensure_numbered()
        return True

    def action_nw_convert(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_('Only Inventory managers can approve a conversion.'))
        if self.nw_numbering_state != 'single':
            raise UserError(_('Only an issued single SKU can use this conversion.'))
        return {'type': 'ir.actions.act_window', 'name': _('Review variant conversion'),
                'res_model': 'nockworks.variant.conversion', 'view_mode': 'form', 'target': 'new',
                'context': {'default_template_id': self.id}}

    def _nw_convert(self, first_value, reason):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_('Only Inventory managers can approve a conversion.'))
        self._nw_lock()
        products = self.with_context(active_test=False).product_variant_ids
        if self.nw_numbering_state != 'single' or len(products) != 1 or not products.active:
            raise UserError(_('Conversion requires exactly one active issued SKU, including archived variants in the check.'))
        if not reason or not first_value or first_value.attribute_id.create_variant == 'no_variant':
            raise UserError(_('Select a stock variant attribute value and document why it represents the original SKU history.'))
        product = products
        original_id, old_reference = product.id, product.default_code
        lines = self.attribute_line_ids.filtered(lambda line: line.attribute_id == first_value.attribute_id)
        if lines and lines.value_ids != first_value:
            raise UserError(_('The chosen original value conflicts with existing attributes.'))
        if any(len(line.value_ids) != 1 for line in self.attribute_line_ids if line.attribute_id.create_variant != 'no_variant'):
            raise UserError(_('Resolve existing multi-value attributes before conversion.'))
        if not lines:
            self.with_context(**context()).write({'attribute_line_ids': [(0, 0, {
                'attribute_id': first_value.attribute_id.id, 'value_ids': [(6, 0, first_value.ids)]})]})
        self.invalidate_recordset(['product_variant_ids'])
        if self.with_context(active_test=False).product_variant_ids.ids != [original_id] or first_value not in product.product_template_attribute_value_ids.product_attribute_value_id:
            raise UserError(_('Conversion aborted: Odoo did not retain the original SKU and chosen combination.'))
        ledger = self.env['nockworks.reference.allocation'].sudo().search([('reference', '=', old_reference)])
        ledger._retire(reason)
        self.with_context(**context()).write({'nw_numbering_state': 'variants'})
        product.with_context(**context()).write({'nw_part_number': False, 'nw_part_number_assigned': False, 'default_code': False})
        product._nw_allocate_suffix()
        return old_reference, product.default_code, original_id

    def copy_data(self, default=None):
        defaults = dict(default or {})
        defaults.update({'nw_base_part_number': False, 'nw_numbering_state': 'none', 'nw_next_variant': 1, 'default_code': False})
        # Defaults for protected fields are only admitted by this private capability.
        return super().copy_data(default=defaults)

    def copy(self, default=None):
        self.ensure_one()
        copied = super(ProductTemplate, self.with_context(**context())).copy(default=default)
        copied._nw_ensure_numbered()
        return copied.with_env(self.env)
