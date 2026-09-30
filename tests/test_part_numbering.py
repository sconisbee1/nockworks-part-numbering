from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestNockWorksPartNumbering(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Category = cls.env["nockworks.part.category"]
        cls.Type = cls.env["nockworks.part.type"]
        cls.Product = cls.env["product.product"]
        cls.category = cls.Category.create({"name": "NockWorks Product", "code": "100"})
        cls.part_type = cls.Type.create({"name": "Stabiliser", "code": "03", "category_id": cls.category.id})

    def _product(self, **values):
        vals = {"name": "Test SKU"}
        vals.update(values)
        return self.Product.create(vals)

    def test_category_validation_and_leading_zero(self):
        category = self.Category.create({"name": "Leading zero", "code": "005"})
        self.assertEqual(category.code, "005")
        for code in ("5", "50", "1000", "ABC", "10A"):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.Category.create({"name": code, "code": code})

    def test_type_validation_and_leading_zero(self):
        part_type = self.Type.create({"name": "Leading zero", "code": "04", "category_id": self.category.id})
        self.assertEqual(part_type.code, "04")
        for code in ("4", "004", "A4"):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.Type.create({"name": code, "code": code, "category_id": self.category.id})

    def test_next_number_range_and_no_decrease(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.Type.create({"name": "Invalid", "code": "09", "category_id": self.category.id, "next_number": 0})
        self.part_type.write({"next_number": 2})
        with self.assertRaises(ValidationError):
            self.part_type.write({"next_number": 1})

    def test_uniqueness(self):
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.Category.create({"name": "Duplicate", "code": "100"})
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.Type.create({"name": "Duplicate", "code": "03", "category_id": self.category.id})

    def test_generation_and_formatting(self):
        product = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        product.action_generate_nw_part_number()
        self.assertEqual(product.nw_part_number, "100-03-0001")
        self.assertEqual(product.default_code, "100-03-0001")
        self.assertTrue(product.nw_part_number_assigned)
        self.assertEqual(self.part_type.next_number, 2)

    def test_separate_sequences(self):
        other_type = self.Type.create({"name": "Other", "code": "04", "category_id": self.category.id})
        first = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        second = self._product(nw_part_category_id=self.category.id, nw_part_type_id=other_type.id)
        first.action_generate_nw_part_number()
        second.action_generate_nw_part_number()
        self.assertEqual(first.nw_part_number, "100-03-0001")
        self.assertEqual(second.nw_part_number, "100-04-0001")

    def test_duplicate_prevention(self):
        first = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        first.action_generate_nw_part_number()
        duplicate = self._product()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            duplicate.with_context(nw_numbering_internal=True).write(
                {"nw_part_number": first.nw_part_number, "nw_part_number_assigned": True}
            )

    def test_copy_clears_number_and_generated_default_code(self):
        product = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        product.action_generate_nw_part_number()
        duplicate = product.copy()
        self.assertFalse(duplicate.nw_part_number)
        self.assertFalse(duplicate.nw_part_number_assigned)
        self.assertNotEqual(duplicate.default_code, product.nw_part_number)

    def test_existing_default_code_untouched(self):
        product = self._product(default_code="LEGACY-42")
        self.category.write({"description": "Unrelated configuration edit"})
        self.assertEqual(product.default_code, "LEGACY-42")

    def test_sequence_exhaustion(self):
        self.part_type.write({"next_number": 9999})
        product = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        product.action_generate_nw_part_number()
        self.assertEqual(product.nw_part_number, "100-03-9999")
        another = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        with self.assertRaises(UserError):
            another.action_generate_nw_part_number()

    def test_invalid_classification_combination(self):
        other_category = self.Category.create({"name": "Other", "code": "200"})
        with self.assertRaises(ValidationError):
            self._product(nw_part_category_id=other_category.id, nw_part_type_id=self.part_type.id)

    def test_assigned_values_are_immutable(self):
        product = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        product.action_generate_nw_part_number()
        with self.assertRaises(ValidationError):
            product.default_code = "CHANGED"
        with self.assertRaises(ValidationError):
            product.nw_part_category_id = False

    def test_archive_and_delete_do_not_release_numbers(self):
        product = self._product(nw_part_category_id=self.category.id, nw_part_type_id=self.part_type.id)
        product.action_generate_nw_part_number()
        product.active = False
        self.assertEqual(self.part_type.next_number, 2)
        product.unlink()
        self.assertEqual(self.part_type.next_number, 2)

    def test_ordinary_products_keep_editable_default_code(self):
        product = self._product(default_code="OLD")
        product.default_code = "NEW"
        self.assertEqual(product.default_code, "NEW")

    def test_variant_specific_numbers(self):
        attribute = self.env["product.attribute"].create({"name": "Length"})
        values = self.env["product.attribute.value"].create([
            {"name": "600 mm", "attribute_id": attribute.id},
            {"name": "650 mm", "attribute_id": attribute.id},
        ])
        template = self.env["product.template"].create({
            "name": "AttenuArc Aero",
            "attribute_line_ids": [(0, 0, {"attribute_id": attribute.id, "value_ids": [(6, 0, values.ids)]})],
        })
        self.assertEqual(template.product_variant_count, 2)
        for variant in template.product_variant_ids:
            variant.write({"nw_part_category_id": self.category.id, "nw_part_type_id": self.part_type.id})
            variant.action_generate_nw_part_number()
        self.assertEqual(len(set(template.product_variant_ids.mapped("nw_part_number"))), 2)
