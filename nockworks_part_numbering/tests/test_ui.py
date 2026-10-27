from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'nw_browser')
class TestNativeVariantUI(HttpCase):
    def test_variants_smart_button_and_easy_form(self):
        category = self.env['nockworks.part.category'].create({'name': 'Browser fixture', 'code': '982'})
        part_type = self.env['nockworks.part.type'].create({'name': 'Body', 'code': '01', 'category_id': category.id})
        attribute = self.env['product.attribute'].create({'name': 'Material'})
        values = self.env['product.attribute.value'].create([{'name': name, 'attribute_id': attribute.id} for name in ('ABS', 'ABS-FR')])
        template = self.env['product.template'].create({'name': 'Native UI fixture', 'nw_part_category_id': category.id,
            'nw_part_type_id': part_type.id, 'attribute_line_ids': [(0, 0, {'attribute_id': attribute.id, 'value_ids': [(6, 0, values.ids)]})]})
        self.env.ref('base.user_admin').write({'group_ids': [(4, self.env.ref('product.group_product_variant').id)]})
        self.start_tour('/odoo/action-product.product_template_action/%s' % template.id,
                        'nw_native_variant_numbers', login='admin', timeout=90)
