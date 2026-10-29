/** @odoo-module **/
import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

registry.category("web_tour.tours").add("nw_rfq_create_edit_product", {
    steps: () => [
        { trigger: '.o_field_x2many_list_row_add > a', run: 'click' },
        { trigger: '.o_field_widget[name="product_id"] input', run: 'edit NW RFQ browser regression' },
        { trigger: '.o_m2o_dropdown_option_create_edit', run: 'click' },
        { trigger: '.modal .o_field_widget[name="name"] textarea, .modal .o_field_widget[name="name"] input', run: 'edit NW RFQ browser regression' },
        { trigger: '.modal .o_field_widget[name="lst_price"] input', run: 'edit 25' },
        { trigger: '.modal .o_field_widget[name="standard_price"] input', run: 'edit 12' },
        { trigger: '.modal .modal-footer .o_form_button_save', run: 'click' },
        { trigger: '.o_data_cell[name="product_id"]:contains(NW RFQ browser regression), .o_field_widget[name="product_id"] input:value("NW RFQ browser regression")' },
        { trigger: '.o_field_widget[name="order_line"] th', run: 'click' },
        ...stepUtils.saveForm(),
        { trigger: '.o_data_cell[name="product_id"]:contains(NW RFQ browser regression), .o_field_widget[name="product_id"] input:value("NW RFQ browser regression")' },
    ],
});