from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestProductCreationOnchange(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['nockworks.part.category'].create({'name': 'RFQ regression', 'code': '984'})
        cls.part_type = cls.env['nockworks.part.type'].create({
            'name': 'Body', 'code': '01', 'category_id': cls.category.id})

    def _classification(self):
        return {'nw_part_category_id': self.category.id, 'nw_part_type_id': self.part_type.id}

    def test_empty_and_new_templates_never_lock_or_allocate(self):
        templates = self.env['product.template']
        draft = templates.new({'name': 'Unsaved', **self._classification()})
        # A truthy recordset with no database IDs caused the original IN () error.
        self.assertTrue(draft)
        self.assertFalse(draft.ids)
        with patch.object(type(self.env.cr), 'execute', side_effect=AssertionError('Unexpected SQL')):
            templates._nw_lock()
            draft._nw_lock()
        draft._nw_ensure_numbered()
        draft.write({'name': 'Changed unsaved template', **self._classification()})
        self.assertFalse(draft.nw_base_part_number)
        self.assertEqual(self.part_type.next_number, 1)
        self.assertTrue(templates.write({}))

    def test_variant_onchange_write_is_cache_only(self):
        draft = self.env['product.product'].new({'name': 'Unsaved RFQ product'})
        draft.write(self._classification())
        draft.write({'standard_price': 12, 'list_price': 25})
        self.assertEqual(draft.nw_part_type_id, self.part_type)
        self.assertFalse(draft.nw_part_number)
        self.assertFalse(draft.product_tmpl_id.nw_base_part_number)
        self.assertEqual(self.part_type.next_number, 1)
        with self.assertRaises(ValidationError):
            draft.write({'nw_variant_number': 1})

    def test_origin_pseudorecord_does_not_modify_saved_product(self):
        product = self.env['product.product'].create({'name': 'Original', **self._classification()})
        reference = product.default_code
        draft = product.new({'name': 'Preview'}, origin=product)
        draft.write({'name': 'Only in browser', 'list_price': 42})
        draft.product_tmpl_id._nw_lock()
        draft.product_tmpl_id._nw_ensure_numbered()
        product.invalidate_recordset()
        self.assertEqual(product.name, 'Original')
        self.assertEqual(product.default_code, reference)
        self.assertEqual(self.part_type.next_number, 2)

    def test_inventory_form_allocates_only_when_saved(self):
        with Form(self.env['product.template'], view='product.product_template_only_form_view') as form:
            form.name = 'Inventory product regression'
            form.nw_part_category_id = self.category
            form.nw_part_type_id = self.part_type
            self.assertEqual(self.part_type.next_number, 1)
            self.assertFalse(form.nw_base_part_number)
        product = form.record.product_variant_id
        self.assertEqual(product.default_code, '984-01-0001')
        product.write({'name': 'Edited inventory product', 'list_price': 45})
        self.assertEqual(product.default_code, '984-01-0001')
        self.assertEqual(self.part_type.next_number, 2)

    def test_rfq_product_form_onchange_and_save(self):
        # The product.product form used by a purchase line's Create and Edit.
        with Form(self.env['product.product'].with_context(default_purchase_ok=True,
                  default_nw_part_category_id=self.category.id, default_nw_part_type_id=self.part_type.id),
                  view='product.product_normal_form_view') as form:
            form.name = 'RFQ Create and Edit regression'
            form.lst_price = 25
            form.standard_price = 12
            self.assertEqual(self.part_type.next_number, 1)
        product = form.record
        self.assertEqual(product.default_code, '984-01-0001')
        if 'purchase.order' not in self.env:
            self.skipTest('Purchase integration requires purchase')
        vendor = self.env['res.partner'].create({'name': 'RFQ regression vendor'})
        with Form(self.env['purchase.order']) as order_form:
            order_form.partner_id = vendor
            with order_form.order_line.new() as line:
                line.product_id = product
        self.assertEqual(order_form.record.order_line.product_id, product)
        self.assertEqual(product.default_code, '984-01-0001')

    def test_category_onchange_clears_incompatible_type_without_allocating(self):
        other = self.env['nockworks.part.category'].create({'name': 'Other', 'code': '985'})
        draft = self.env['product.product'].new({'name': 'Classification preview', **self._classification()})
        draft.nw_part_category_id = other
        draft._onchange_nw_part_category_id()
        self.assertFalse(draft.nw_part_type_id)
        self.assertEqual(self.part_type.next_number, 1)