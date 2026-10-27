/** @odoo-module **/
import { registry } from "@web/core/registry";
import { IntegerField, integerField } from "@web/views/fields/integer/integer_field";

class VariantSuffixField extends IntegerField {
    get formattedValue() {
        const value = this.props.record.data[this.props.name];
        return value ? String(value).padStart(2, "0") : "";
    }
}
registry.category("fields").add("nw_variant_suffix", { ...integerField, component: VariantSuffixField });
