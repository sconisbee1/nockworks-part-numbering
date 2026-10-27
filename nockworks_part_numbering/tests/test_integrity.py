from psycopg2 import IntegrityError
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'nw_integrity')
class TestReferenceIntegrity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['nockworks.part.category'].create({'name': 'Integrity manufactured', 'code': '150'})
        cls.part_type = cls.env['nockworks.part.type'].create({'name': 'Integrity body', 'code': '01', 'category_id': cls.category.id})
        cls.attribute = cls.env['product.attribute'].create({'name': 'Integrity material'})
        cls.values = cls.env['product.attribute.value'].create([{'name': name, 'attribute_id': cls.attribute.id} for name in ('ABS', 'ABS-FR')])

    def _family(self, variants=True):
        vals = {'name': 'Integrity family', 'nw_part_category_id': self.category.id, 'nw_part_type_id': self.part_type.id}
        if variants:
            vals['attribute_line_ids'] = [(0, 0, {'attribute_id': self.attribute.id, 'value_ids': [(6, 0, self.values.ids)]})]
        return self.env['product.template'].create(vals)

    def _manual(self, reference='777-01-0042'):
        return self.env['product.product'].create({'name': 'Manual reference', 'default_code': reference})

    def _allocation(self, reference):
        return self.env['nockworks.reference.allocation'].sudo().search([('reference', '=', reference)])

    def _check_database(self):
        self.env.flush_all()
        self.env.cr.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.env.cr.execute('SET CONSTRAINTS ALL DEFERRED')

    def test_manual_clear_retires_and_detaches_current_owner(self):
        product = self._manual()
        original_id = product.id
        product.default_code = False
        allocation = self._allocation('777-01-0042')
        allocation.invalidate_recordset()
        self.assertTrue(allocation.retired)
        self.assertFalse(allocation.product_id)
        self.assertEqual(allocation.original_product_id, original_id)

    def test_same_sku_cannot_reclaim_changed_manual_reference(self):
        product = self._manual()
        product.default_code = '777-01-0043'
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            product.default_code = '777-01-0042'

    def test_manual_owner_cannot_move_to_another_family(self):
        product = self._manual()
        other = self.env['product.template'].with_context(create_product_product=False).create({'name': 'Other family'})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            product.product_tmpl_id = other

    def test_deleted_variant_is_retired_but_permanently_reserved(self):
        family = self._family()
        product = family.product_variant_ids[0]
        reference, original_id = product.default_code, product.id
        product.unlink()
        allocation = self._allocation(reference)
        allocation.invalidate_recordset()
        self.assertTrue(allocation.retired)
        self.assertFalse(allocation.product_id)
        self.assertEqual(allocation.original_product_id, original_id)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._manual(reference)

    def test_conversion_retires_base_without_stale_active_owner(self):
        self.part_type.next_number = 4
        family = self._family(False)
        product = family.product_variant_id
        original_id = product.id
        self.env['nockworks.variant.conversion'].create({'template_id': family.id,
            'first_value_id': self.values[0].id, 'confirmed': True,
            'reason': 'Reviewed original SKU ID and all history: ABS.'}).action_confirm()
        self.assertEqual(product.id, original_id)
        self.assertEqual(product.default_code, '150-01-0004-01')
        allocation = self._allocation('150-01-0004')
        allocation.invalidate_recordset()
        self.assertTrue(allocation.retired)
        self.assertFalse(allocation.product_id)
        self.assertEqual(allocation.original_product_id, original_id)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._manual('150-01-0004')
        self._check_database()

    def test_database_rejects_ledger_family_mismatch(self):
        family = self._family()
        product = family.product_variant_ids[0]
        allocation = self._allocation(product.default_code)
        other = self.env['product.template'].create({'name': 'Wrong ledger family'})
        self.env.flush_all()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('UPDATE nockworks_reference_allocation SET family_id = %s WHERE id = %s', [other.id, allocation.id])
            self._check_database()

    def test_database_rejects_suffix_reference_mismatch(self):
        family = self._family()
        product = family.product_variant_ids[0]
        self.env.flush_all()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('UPDATE product_product SET nw_variant_number = 88 WHERE id = %s', [product.id])
            self._check_database()

    def test_private_reserve_denies_public_orm_caller(self):
        family = self.env['product.template'].create({'name': 'Unnumbered'})
        public = self.env.ref('base.public_user')
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.env['nockworks.reference.allocation'].with_user(public)._reserve(family.with_user(public), '150-01-9999')

    def test_private_retire_denies_public_orm_caller(self):
        family = self._family()
        allocation = self._allocation(family.product_variant_ids[0].default_code)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            allocation.with_user(self.env.ref('base.public_user'))._retire('Unauthorised')

    def test_private_base_counter_denies_public_orm_caller(self):
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.part_type.with_user(self.env.ref('base.public_user'))._allocate_next_number()

    def test_private_assign_cannot_mint_its_own_authority(self):
        product = self.env['product.product'].create({'name': 'Unnumbered'})
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            product._nw_assign('777-01-0099')

    def test_private_suffix_allocation_requires_numbered_family(self):
        product = self.env['product.product'].create({'name': 'Unnumbered'})
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            product._nw_allocate_suffix()

    def test_archive_and_reactivate_preserve_active_manual_owner(self):
        product = self._manual()
        allocation = self._allocation(product.default_code)
        product.active = False
        self._check_database()
        allocation.invalidate_recordset()
        self.assertFalse(allocation.retired)
        self.assertEqual(allocation.product_id, product)
        product.active = True
        self._check_database()
        self.assertEqual(product.default_code, '777-01-0042')

    def test_clear_and_failed_reclaim_are_atomic(self):
        product = self._manual()
        original_family = product.product_tmpl_id.id
        product.default_code = False
        old = self._allocation('777-01-0042')
        old.invalidate_recordset()
        self.assertEqual(old.family_key, original_family)
        self.assertEqual(old.released_by, self.env.user)
        self.assertTrue(old.released_at)
        self.assertIn('cleared', old.release_reason)
        product.default_code = '777-01-0043'
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            product.default_code = '777-01-0042'
        self.env.invalidate_all()
        self.assertEqual(product.default_code, '777-01-0043')
        self.assertFalse(self._allocation('777-01-0043').retired)
        self.assertTrue(old.retired)
        self._check_database()

    def test_manual_namespace_to_plain_reference_preserves_tombstone(self):
        product = self._manual()
        product.default_code = 'LEGACY-EDITABLE'
        self.env.flush_all()
        allocation = self._allocation('777-01-0042')
        self.assertTrue(allocation.retired)
        self.assertFalse(allocation.product_id)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._manual('777-01-0042')
        product.default_code = 'ANOTHER-ORDINARY-REFERENCE'
        self._check_database()

    def test_delete_manual_reference_keeps_identity_snapshot(self):
        product = self._manual()
        product_id, family_id = product.id, product.product_tmpl_id.id
        product.unlink()
        allocation = self._allocation('777-01-0042')
        self.assertTrue(allocation.retired)
        self.assertFalse(allocation.product_id)
        self.assertEqual(allocation.original_product_id, product_id)
        self.assertEqual(allocation.family_key, family_id)
        self.assertEqual(allocation.released_by, self.env.user)
        self._check_database()

    def test_family_deletion_preserves_base_and_variant_reservations(self):
        family = self._family()
        base = family.nw_base_part_number
        refs = [base] + family.product_variant_ids.mapped('default_code')
        family_id = family.id
        family.unlink()
        self.env.invalidate_all()
        for reference in refs:
            allocation = self._allocation(reference)
            self.assertTrue(allocation.retired)
            self.assertFalse(allocation.family_id)
            self.assertFalse(allocation.product_id)
            self.assertEqual(allocation.family_key, family_id)
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self._manual(reference)
        self._check_database()

    def test_variant_family_base_cannot_be_used_as_a_sku_reference(self):
        family = self._family()
        allocation = self._allocation(family.nw_base_part_number)
        self.assertFalse(allocation.product_id)
        self.assertFalse(allocation.retired)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._manual(family.nw_base_part_number)
        self._check_database()

    def test_issued_reference_cannot_be_cleared_or_changed(self):
        family = self._family()
        product = family.product_variant_ids[0]
        reference = product.default_code
        for value in (False, 'ORDINARY', '150-01-9999-99'):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                product.default_code = value
        self.assertEqual(product.default_code, reference)
        self.assertFalse(self._allocation(reference).retired)

    def test_database_cannot_delete_or_rewrite_allocation_identity(self):
        family = self._family()
        allocation = self._allocation(family.product_variant_ids[0].default_code)
        self._check_database()
        statements = [
            ('DELETE FROM nockworks_reference_allocation WHERE id = %s', [allocation.id]),
            ("UPDATE nockworks_reference_allocation SET reference = '150-01-9999-99' WHERE id = %s", [allocation.id]),
            ('UPDATE nockworks_reference_allocation SET original_product_id = original_product_id + 1 WHERE id = %s', [allocation.id]),
            ('UPDATE nockworks_reference_allocation SET family_key = family_key + 1 WHERE id = %s', [allocation.id]),
        ]
        for statement, params in statements:
            with self.assertRaises(IntegrityError), self.env.cr.savepoint():
                self.env.cr.execute(statement, params)

    def test_database_cannot_unretire_or_reassign_reference(self):
        product = self._manual()
        product.default_code = False
        allocation = self._allocation('777-01-0042')
        self._check_database()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('UPDATE nockworks_reference_allocation SET retired = FALSE WHERE id = %s', [allocation.id])
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('UPDATE nockworks_reference_allocation SET product_id = %s WHERE id = %s', [product.id, allocation.id])

    def test_database_cannot_move_issued_sku_to_other_family(self):
        family = self._family()
        other = self._family()
        product = family.product_variant_ids[0]
        self._check_database()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('UPDATE product_product SET product_tmpl_id = %s WHERE id = %s', [other.id, product.id])
            self._check_database()

    def test_database_cannot_replace_family_base_without_reservation(self):
        family = self._family()
        self._check_database()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute("UPDATE product_template SET nw_base_part_number = '150-01-9999' WHERE id = %s", [family.id])
            self._check_database()

    def test_capability_does_not_replace_user_access_checks(self):
        from odoo.addons.nockworks_part_numbering.models.capability import context
        family = self.env['product.template'].create({'name': 'Unnumbered'})
        public = self.env.ref('base.public_user')
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.env['nockworks.reference.allocation'].with_user(public).with_context(**context())._reserve(family, '150-01-9999')
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            family.with_user(public)._nw_ensure_numbered()

    def test_internal_assignment_requires_exact_existing_allocation(self):
        from odoo.addons.nockworks_part_numbering.models.capability import context
        product = self.env['product.product'].create({'name': 'Unnumbered'})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            product.with_context(**context())._nw_assign('150-01-9999')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            product.with_context(**context())._nw_allocate_suffix()

    def test_odoo_rpc_dispatch_rejects_all_private_services(self):
        from odoo.service.model import call_kw
        for model, method in [
            ('nockworks.reference.allocation', '_reserve'), ('nockworks.reference.allocation', '_retire'),
            ('product.product', '_nw_assign'), ('product.product', '_nw_allocate_suffix'),
            ('product.template', '_nw_convert'), ('product.template', '_nw_ensure_numbered'),
            ('nockworks.part.type', '_allocate_next_number'),
        ]:
            with self.assertRaises(AccessError):
                call_kw(self.env[model], method, [], {'context': {'nw_numbering_internal': True, '_nw_capability': True}})

    def test_repeated_initialization_preserves_allocations_and_guard_definitions(self):
        from odoo.addons.nockworks_part_numbering.hooks import initialize
        family = self._family()
        product = self._manual()
        product.default_code = False
        self._check_database()
        fields = ['reference', 'kind', 'family_key', 'original_product_id', 'suffix', 'retired', 'released_at', 'release_reason']
        before = self.env['nockworks.reference.allocation'].sudo().search([]).read(fields)
        refs = family.product_variant_ids.mapped('default_code')
        counter = family.nw_next_variant
        self.env.cr.execute("SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname LIKE 'nw_%' ORDER BY tgname")
        triggers = self.env.cr.fetchall()
        initialize(self.env)
        initialize(self.env)
        self.assertEqual(before, self.env['nockworks.reference.allocation'].sudo().search([]).read(fields))
        self.assertEqual(refs, family.product_variant_ids.mapped('default_code'))
        self.assertEqual(counter, family.nw_next_variant)
        self.env.cr.execute("SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname LIKE 'nw_%' ORDER BY tgname")
        self.assertEqual(triggers, self.env.cr.fetchall())
        self._check_database()

    def test_active_allocations_never_use_sql_null_retirement_flag(self):
        family = self._family()
        self.env.flush_all()
        self.env.cr.execute('SELECT count(*) FROM nockworks_reference_allocation WHERE family_key = %s AND retired IS NULL', [family.id])
        self.assertEqual(self.env.cr.fetchone()[0], 0)
        allocation = self._allocation(family.product_variant_ids[0].default_code)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('UPDATE nockworks_reference_allocation SET retired = NULL WHERE id = %s', [allocation.id])

    def test_variant_counter_cannot_be_null_or_rewind_behind_tombstones(self):
        family = self._family()
        family.product_variant_ids[0].unlink()
        self._check_database()
        for counter in (None, 1):
            with self.assertRaises(IntegrityError), self.env.cr.savepoint():
                self.env.cr.execute('UPDATE product_template SET nw_next_variant = %s WHERE id = %s', [counter, family.id])
                self._check_database()

    def test_allocation_shape_rejects_null_suffix_immediately(self):
        family = self._family()
        self._check_database()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute('''INSERT INTO nockworks_reference_allocation
                (reference, kind, family_id, family_key, suffix, retired, original_product_id)
                VALUES ('150-01-9999', 'base', %s, %s, NULL, TRUE, 0)''', [family.id, family.id])

    def test_rpc_context_defaults_cannot_forge_legacy_assignment(self):
        from odoo.service.model import call_kw
        editor = self.env['res.users'].create({'name': 'Product editor', 'login': 'nw-context-editor',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('stock.group_stock_user').id, self.env.ref('product.group_product_manager').id])]})
        self.assertFalse(editor.has_group('stock.group_stock_manager'))
        self.env['product.product'].with_user(editor).check_access('create')
        forged = {
            'default_nw_numbering_state': 'legacy',
            'default_nw_part_number': '777-01-0099',
            'default_nw_part_number_assigned': True,
            'default_default_code': '777-01-0099',
        }
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            call_kw(self.env['product.product'].with_user(editor), 'create', [{'name': 'Context forged legacy'}], {'context': forged})
            self._check_database()

    def test_template_create_and_copy_reject_protected_context_defaults(self):
        from odoo.service.model import call_kw
        family = self._family()
        for model, method, args in [
            ('product.template', 'create', [{'name': 'Forged family'}]),
            ('product.template', 'copy', [[family.id]]),
            ('product.product', 'copy', [[family.product_variant_ids[0].id]]),
        ]:
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                call_kw(self.env[model], method, args, {'context': {'default_nw_numbering_state': 'legacy'}})

    def test_context_default_template_cannot_bypass_single_sku_conversion(self):
        from odoo.exceptions import UserError
        family = self._family(False)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env['product.product'].with_context(default_product_tmpl_id=family.id, default_active=False).create({'name': 'Injected extra SKU'})

    def test_context_defaults_cannot_spoof_ledger_audit_metadata(self):
        family = self.env['product.template'].with_context(default_released_by=self.env.ref('base.public_user').id,
            default_release_reason='Forged audit note').create({'name': 'Safe family',
                'nw_part_category_id': self.category.id, 'nw_part_type_id': self.part_type.id})
        allocation = self._allocation(family.nw_base_part_number)
        self.assertFalse(allocation.released_by)
        self.assertFalse(allocation.release_reason)
        self._check_database()

    def test_variant_cannot_override_stored_base_or_display_suffix(self):
        product = self._family().product_variant_ids[0]
        for values in ({'nw_base_part_number': '150-01-9999'}, {'nw_variant_suffix': '99'}):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                product.write(values)

    def test_database_rejects_unclassified_legacy_assignment(self):
        product = self._manual()
        self._check_database()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env.cr.execute("UPDATE product_template SET nw_numbering_state = 'legacy' WHERE id = %s", [product.product_tmpl_id.id])
            self.env.cr.execute('UPDATE product_product SET nw_part_number = default_code, nw_part_number_assigned = TRUE WHERE id = %s', [product.id])
            self._check_database()

    def test_upgrade_stops_on_unclassified_issued_reference_without_renumbering(self):
        from odoo.addons.nockworks_part_numbering.hooks import TRIGGERS, initialize
        product = self._manual()
        reference = product.default_code
        self._check_database()
        with self.assertRaises(RuntimeError), self.env.cr.savepoint():
            for table, trigger in TRIGGERS:
                self.env.cr.execute('DROP TRIGGER IF EXISTS %s ON %s' % (trigger, table))
            self.env.cr.execute("UPDATE product_template SET nw_numbering_state = 'legacy' WHERE id = %s", [product.product_tmpl_id.id])
            self.env.cr.execute('UPDATE product_product SET nw_part_number = default_code, nw_part_number_assigned = TRUE WHERE id = %s', [product.id])
            initialize(self.env)
        self.env.invalidate_all()
        self.assertEqual(product.default_code, reference)
        self.assertFalse(product.nw_part_number_assigned)
