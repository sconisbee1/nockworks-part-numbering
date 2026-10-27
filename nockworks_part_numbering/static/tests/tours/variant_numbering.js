/** @odoo-module **/
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("nw_native_variant_numbers", {
    steps: () => [
        { trigger: '.o_form_view .o_field_widget[name="nw_base_part_number"]:contains(982-01-0001)' },
        { trigger: '.oe_stat_button:has(.o_stat_text:contains(Variants))', run: 'click' },
        { trigger: '.o_list_view .o_data_cell[name="default_code"]:contains(982-01-0001-01)' },
        { trigger: '.o_list_view .o_data_cell[name="nw_base_part_number"]:contains(982-01-0001)' },
        { trigger: '.o_list_view .o_data_cell[name="nw_variant_number"]:contains(01)' },
        { trigger: '.o_list_view .o_data_cell[name="product_template_variant_value_ids"]:contains(ABS)' },
        { trigger: '.o_list_view .o_data_cell[name="default_code"]:contains(982-01-0001-01)', run: 'click' },
        { trigger: '.o_form_view .o_field_widget[name="nw_variant_suffix"]:contains(01)' },
        { trigger: '.o_form_view .o_field_widget[name="default_code"]:contains(982-01-0001-01)' },
        { trigger: '.o_form_view .o_field_widget[name="nw_part_number"]:contains(982-01-0001-01)' },
    ],
});
