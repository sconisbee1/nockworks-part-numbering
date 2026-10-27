from psycopg2 import IntegrityError
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.addons.nockworks_part_numbering.hooks import initialize
from odoo.addons.nockworks_part_numbering.models.capability import context


@tagged('post_install', '-at_install')
class TestNockWorksPartNumbering(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['nockworks.part.category'].create({'name': 'Manufactured', 'code': '150'})
        cls.part_type = cls.env['nockworks.part.type'].create({'name': 'Body', 'code': '01', 'category_id': cls.category.id})
        cls.attribute = cls.env['product.attribute'].create({'name': 'Material', 'create_variant': 'always'})
        cls.values = cls.env['product.attribute.value'].create([
            {'name': name, 'attribute_id': cls.attribute.id} for name in ('ABS', 'ABS-FR', 'PETG')])

    def _template(self, variants=False, **extra):
        vals = {'name': 'V200', 'nw_part_category_id': self.category.id, 'nw_part_type_id': self.part_type.id}
        if variants:
            vals['attribute_line_ids'] = [(0, 0, {'attribute_id': self.attribute.id, 'value_ids': [(6, 0, self.values[:2].ids)]})]
        vals.update(extra)
        return self.env['product.template'].create(vals)

    def _convert(self, template):
        wizard = self.env['nockworks.variant.conversion'].create({
            'template_id': template.id, 'first_value_id': self.values[0].id,
            'reason': 'Verified original stock and historical orders are ABS.', 'confirmed': True})
        wizard.action_confirm()

    def test_single_and_idempotent_generation(self):
        template = self._template()
        self.assertEqual(template.nw_base_part_number, '150-01-0001')
        self.assertEqual(template.product_variant_id.default_code, template.nw_base_part_number)
        self.assertFalse(template.product_variant_id.nw_variant_number)
        template.action_generate_nw_part_number()
        self.assertEqual(self.part_type.next_number, 2)

    def test_unmanaged_products(self):
        product = self.env['product.product'].create({'name': 'Legacy', 'default_code': 'OLD'})
        product.default_code = 'NEW'
        self.assertEqual(product.default_code, 'NEW')
        self.assertFalse(product.nw_part_number)

    def test_two_variants_then_third(self):
        template = self._template(True)
        products = template.product_variant_ids.sorted('id')
        previous = {p.id: p.default_code for p in products}
        self.assertEqual(products.mapped('nw_variant_number'), [1, 2])
        self.assertEqual(products.mapped('default_code'), ['150-01-0001-01', '150-01-0001-02'])
        template.attribute_line_ids.value_ids = self.values
        self.assertEqual(template.product_variant_count, 3)
        self.assertEqual({p.id: p.default_code for p in products}, previous)
        self.assertEqual(template.nw_next_variant, 4)

    def test_multiple_attributes_reorder(self):
        template = self._template(True)
        colour = self.env['product.attribute'].create({'name': 'Colour'})
        colours = self.env['product.attribute.value'].create([{'name': name, 'attribute_id': colour.id} for name in ('Black', 'White')])
        template.write({'attribute_line_ids': [(0, 0, {'attribute_id': colour.id, 'value_ids': [(6, 0, colours.ids)]})]})
        self.assertEqual(template.product_variant_count, 4)
        previous = {p.id: p.default_code for p in template.product_variant_ids}
        template.attribute_line_ids[0].sequence = 99
        template._create_variant_ids()
        self.assertEqual(previous, {p.id: p.default_code for p in template.product_variant_ids})

    def test_archive_reactivate(self):
        template = self._template(True)
        product = template.product_variant_ids[0]
        reference = product.default_code
        product.active = False
        product.active = True
        self.assertEqual(reference, product.default_code)
        self.assertEqual(template.nw_next_variant, 3)

    def test_delete_recreate_tombstone(self):
        template = self._template(True)
        product = template.product_variant_ids[0]
        reference = product.default_code
        product.unlink()
        template._create_variant_ids()
        self.assertNotIn(reference, template.product_variant_ids.mapped('default_code'))
        allocation = self.env['nockworks.reference.allocation'].search([('reference', '=', reference)])
        self.assertTrue(allocation)
        self.assertFalse(allocation.product_id)
        self.assertEqual(template.nw_next_variant, 4)

    def test_duplicate_template_and_product(self):
        template = self._template(True)
        duplicate = template.copy()
        self.assertNotEqual(template.nw_base_part_number, duplicate.nw_base_part_number)
        self.assertEqual(duplicate.product_variant_ids.sorted('id').mapped('nw_variant_number'), [1, 2])
        copied_product = template.product_variant_ids[0].copy()
        self.assertNotIn(copied_product.default_code, template.product_variant_ids.mapped('default_code'))

    def test_reference_collision_manual_and_tombstone(self):
        template = self._template(True)
        product = template.product_variant_ids[0]
        reference = product.default_code
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['product.product'].create({'name': 'Collision', 'default_code': reference})
        product.unlink()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['product.product'].create({'name': 'Tombstone collision', 'default_code': reference})

    def test_context_flags_do_not_authorize_writes(self):
        product = self._template(True).product_variant_ids[0]
        for flags in ({'nw_numbering_internal': True}, {'_nw_capability': True}, {'nw_sequence_allocation': True}):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                product.with_context(**flags).write({'nw_part_number': '150-01-9999-99', 'default_code': '150-01-9999-99'})
        with self.assertRaises(ValidationError):
            self.env['product.product'].with_context(nw_numbering_internal=True).create({'name': 'Forged', 'nw_variant_number': 3})
        with self.assertRaises(ValidationError):
            product.product_tmpl_id.write({'nw_next_variant': 1})

    def test_no_public_ledger_mutation(self):
        allocation = self.env['nockworks.reference.allocation'].search([('reference', '=', self._template().nw_base_part_number)])
        for method, vals in [('write', {'suffix': 98}), ('create', {'reference': 'x'})]:
            with self.assertRaises(ValidationError):
                getattr(allocation, method)(vals)
        with self.assertRaises(ValidationError):
            allocation.unlink()

    def test_exhaustion_is_atomic(self):
        template = self._template(True)
        template.with_context(**context()).write({'nw_next_variant': 99})
        template.attribute_line_ids.value_ids = self.values
        self.assertIn(99, template.product_variant_ids.mapped('nw_variant_number'))
        extra = self.env['product.attribute.value'].create({'name': 'Nylon', 'attribute_id': self.attribute.id})
        references = template.product_variant_ids.mapped('default_code')
        with self.assertRaises(UserError), self.env.cr.savepoint():
            template.attribute_line_ids.value_ids |= extra
        self.assertEqual(template.product_variant_ids.mapped('default_code'), references)

    def test_issued_single_blocks_native_and_direct_changes(self):
        template = self._template()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            template.attribute_line_ids = [(0, 0, {'attribute_id': self.attribute.id, 'value_ids': [(6, 0, self.values[:2].ids)]})]
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env['product.product'].create({'product_tmpl_id': template.id})
        self.assertEqual(template.product_variant_id.default_code, template.nw_base_part_number)

    def test_controlled_conversion_retains_id_and_adds_second(self):
        template = self._template()
        product = template.product_variant_id
        original_id = product.id
        old_reference = product.default_code
        self._convert(template)
        self.assertEqual(template.product_variant_id.id, original_id)
        self.assertEqual(product.default_code, old_reference + '-01')
        template.attribute_line_ids.value_ids = self.values[:2]
        self.assertEqual(template.product_variant_count, 2)
        self.assertEqual(product.id, original_id)
        self.assertEqual(product.default_code, old_reference + '-01')
        self.assertTrue(self.env['nockworks.reference.allocation'].search([('reference', '=', old_reference)]).retired)
        self.assertTrue(template.message_ids.filtered(lambda m: 'Approved variant conversion' in str(m.body)))

    def test_conversion_requires_review(self):
        template = self._template()
        wizard = self.env['nockworks.variant.conversion'].create({'template_id': template.id, 'first_value_id': self.values[0].id, 'reason': 'Unreviewed'})
        with self.assertRaises(UserError):
            wizard.action_confirm()
        user = self.env['res.users'].create({'name': 'Stock User', 'login': 'nw-test-user', 'group_ids': [(6, 0, [self.env.ref('stock.group_stock_user').id])]})
        with self.assertRaises(UserError):
            template.with_user(user).action_nw_convert()

    def test_no_variant_attributes_stay_unsuffixed(self):
        attribute = self.env['product.attribute'].create({'name': 'Engraving', 'create_variant': 'no_variant'})
        values = self.env['product.attribute.value'].create([{'name': name, 'attribute_id': attribute.id} for name in ('A', 'B')])
        template = self._template(attribute_line_ids=[(0, 0, {'attribute_id': attribute.id, 'value_ids': [(6, 0, values.ids)]})])
        self.assertEqual(template.nw_numbering_state, 'single')
        self.assertFalse(template.product_variant_id.nw_variant_number)

    def test_dynamic_variants(self):
        attribute = self.env['product.attribute'].create({'name': 'On demand', 'create_variant': 'dynamic'})
        values = self.env['product.attribute.value'].create([{'name': name, 'attribute_id': attribute.id} for name in ('A', 'B')])
        template = self._template(attribute_line_ids=[(0, 0, {'attribute_id': attribute.id, 'value_ids': [(6, 0, values.ids)]})])
        self.assertEqual(template.nw_numbering_state, 'variants')
        ptavs = template.attribute_line_ids.product_template_value_ids
        first = template._create_product_variant(ptavs[:1])
        second = template._create_product_variant(ptavs[1:])
        self.assertNotEqual(first.nw_variant_number, second.nw_variant_number)
        reference = first.default_code
        first.active = False
        self.assertEqual(template._create_product_variant(ptavs[:1]).default_code, reference)

    def test_upgrade_metadata_adoption_is_idempotent(self):
        template = self.env['product.template'].create({'name': 'Old issued single'})
        product = template.product_variant_id
        # Reproduce old-version stored data, without calling the new numbering service.
        self.env.cr.execute('''UPDATE product_product SET nw_part_number = '150-01-0042',
            nw_part_number_assigned = TRUE, default_code = '150-01-0042', nw_part_category_id = %s,
            nw_part_type_id = %s WHERE id = %s''', [self.category.id, self.part_type.id, product.id])
        self.env.invalidate_all()
        initialize(self.env)
        initialize(self.env)
        self.assertEqual(product.default_code, '150-01-0042')
        self.assertEqual(template.nw_base_part_number, product.default_code)
        self.assertEqual(template.nw_numbering_state, 'single')
        self.assertFalse(product.nw_variant_number)

    def test_native_view_architectures(self):
        for xmlid, model, view_type in [
            ('product.product_template_only_form_view', 'product.template', 'form'),
            ('product.product_product_tree_view', 'product.product', 'list'),
            ('product.product_variant_easy_edit_view', 'product.product', 'form'),
            ('product.product_normal_form_view', 'product.product', 'form'),
            ('product.product_search_form_view', 'product.product', 'search'),
        ]:
            arch = self.env[model].get_view(self.env.ref(xmlid).id, view_type)['arch']
            self.assertIn('nw_base_part_number', arch)
        action = self.env.ref('product.product_variant_action')
        self.assertEqual(action.res_model, 'product.product')
        self.assertIn('active_id', action.context)
        self.assertIn(self.env.ref('product.product_variant_easy_edit_view'), action.view_ids.view_id)

    def test_classification_and_base_limits(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.category.code = '15'
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.part_type.code = 'A'
        self.part_type.next_number = 9999
        self.assertEqual(self._template().nw_base_part_number, '150-01-9999')
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._template()

    def test_manufacturing_and_stock_identity(self):
        if 'mrp.bom' not in self.env:
            self.skipTest('Install mrp for the manufacturing integration suite')
        template = self._template(is_storable=True, tracking='lot')
        product = template.product_variant_id
        component = self.env['product.product'].create({'name': 'Component', 'is_storable': True})
        bom = self.env['mrp.bom'].create({'product_tmpl_id': template.id, 'product_id': product.id,
            'bom_line_ids': [(0, 0, {'product_id': component.id, 'product_qty': 1})],
            'operation_ids': [(0, 0, {'name': 'Machine', 'workcenter_id': self.env['mrp.workcenter'].create({'name': 'Test mill'}).id})]})
        mo = self.env['mrp.production'].create({'product_id': product.id, 'product_qty': 1, 'bom_id': bom.id})
        mo.action_confirm()
        lot = self.env['stock.lot'].create({'name': 'ABS-EXISTING', 'product_id': product.id})
        location = self.env.ref('stock.stock_location_stock')
        self.env['stock.quant']._update_available_quantity(product, location, 5, lot_id=lot)
        moves = mo.move_finished_ids
        workorders = mo.workorder_ids
        self._convert(template)
        self.assertEqual(mo.product_id, product)
        self.assertEqual(lot.product_id, product)
        self.assertEqual(bom.product_id, product)
        self.assertEqual(mo.move_finished_ids, moves)
        self.assertEqual(mo.workorder_ids, workorders)
        self.assertEqual(self.env['stock.quant']._get_available_quantity(product, location, lot_id=lot), 5)
        template.attribute_line_ids.value_ids = self.values[:2]
        other = template.product_variant_ids - product
        other_bom = self.env['mrp.bom'].create({'product_tmpl_id': template.id, 'product_id': other.id})
        found = self.env['mrp.bom']._bom_find(template.product_variant_ids)
        self.assertEqual(found[product], bom)
        self.assertEqual(found[other], other_bom)



    def test_copy_keeps_normal_security_context(self):
        copy = self._template(True).copy()
        with self.assertRaises(ValidationError):
            copy.write({'nw_next_variant': 1})
        with self.assertRaises(ValidationError):
            copy.product_variant_ids[0].write({'nw_variant_number': 98})

    def test_archived_single_can_reactivate_without_conversion(self):
        template = self._template()
        product = template.product_variant_id
        reference = product.default_code
        template.action_archive()
        template.action_unarchive()
        self.assertTrue(product.active)
        self.assertEqual(product.default_code, reference)
        self.assertFalse(product.nw_variant_number)

    def test_import_rejects_suffix_injection(self):
        result = self.env['product.product'].load(['name', 'nw_variant_number'], [['Import forgery', '44']])
        self.assertFalse(result.get('ids'))
        self.assertTrue(result['messages'])
        self.assertFalse(self.env['product.product'].search([('name', '=', 'Import forgery')]))

    def test_direct_attribute_line_edit_cannot_convert_single(self):
        template = self._template()
        original_id = template.product_variant_id.id
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env['product.template.attribute.line'].create({'product_tmpl_id': template.id,
                'attribute_id': self.attribute.id, 'value_ids': [(6, 0, self.values[:2].ids)]})
        self.assertEqual(template.product_variant_id.id, original_id)
        self.assertEqual(template.product_variant_id.default_code, template.nw_base_part_number)

    def test_issued_configuration_is_immutable(self):
        self._template()
        with self.assertRaises(ValidationError):
            self.category.code = '151'
        with self.assertRaises(ValidationError):
            self.part_type.code = '02'
        with self.assertRaises(ValidationError):
            self.part_type.with_context(nw_sequence_allocation=True).sequence_exhausted = False
        with self.assertRaises(ValidationError):
            self.part_type.next_number = 1

    def test_database_suffix_and_reference_constraints(self):
        template = self._template(True)
        products = template.product_variant_ids.sorted('id')
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('UPDATE product_product SET nw_variant_number = %s WHERE id = %s',
                [products[0].nw_variant_number, products[1].id])
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute("UPDATE product_product SET default_code = 'FORGED' WHERE id = %s", [products[0].id])

    def test_new_manual_namespace_reference_is_reserved(self):
        product = self.env['product.product'].create({'name': 'Manual managed format', 'default_code': '777-01-0001'})
        self.assertFalse(product.nw_part_number_assigned)
        allocation = self.env['nockworks.reference.allocation'].sudo().search([('reference', '=', product.default_code)])
        self.assertEqual(allocation.product_id, product)
        product.unlink()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['product.product'].create({'name': 'Reused manual reference', 'default_code': '777-01-0001'})

    def test_upgrade_preserves_unissued_classification_without_numbering(self):
        template = self.env['product.template'].create({'name': 'Unissued old classification'})
        product = template.product_variant_id
        self.env.cr.execute('UPDATE product_product SET nw_part_category_id = %s, nw_part_type_id = %s WHERE id = %s',
            [self.category.id, self.part_type.id, product.id])
        self.env.invalidate_all()
        initialize(self.env)
        self.assertEqual(template.nw_part_category_id, self.category)
        self.assertEqual(template.nw_part_type_id, self.part_type)
        self.assertFalse(template.nw_base_part_number)
        self.assertFalse(product.default_code)
        self.assertEqual(template.nw_numbering_state, 'none')

    def test_non_variant_attribute_edit_keeps_issued_single_reference(self):
        template = self._template()
        product = template.product_variant_id
        reference = product.default_code
        attribute = self.env['product.attribute'].create({'name': 'Customer text', 'create_variant': 'no_variant'})
        values = self.env['product.attribute.value'].create([{'name': name, 'attribute_id': attribute.id} for name in ('A', 'B')])
        template.write({'attribute_line_ids': [(0, 0, {'attribute_id': attribute.id, 'value_ids': [(6, 0, values.ids)]})]})
        self.assertEqual(template.product_variant_id, product)
        self.assertEqual(product.default_code, reference)
        self.assertFalse(product.nw_variant_number)
