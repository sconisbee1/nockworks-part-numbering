from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProductProduct(models.Model):
    _inherit = "product.product"

    nw_part_category_id = fields.Many2one(
        "nockworks.part.category", string="Part Category", ondelete="restrict", index=True
    )
    nw_part_type_id = fields.Many2one(
        "nockworks.part.type", string="Part Type", ondelete="restrict", index=True
    )
    nw_part_number = fields.Char(
        string="Part Number", readonly=True, copy=False, index=True
    )
    nw_part_number_assigned = fields.Boolean(
        string="Part Number Assigned", readonly=True, copy=False, default=False, index=True
    )

    _sql_constraints = [
        (
            "nw_part_number_unique",
            "unique(nw_part_number)",
            "The NockWorks part number must be unique.",
        ),
        (
            "nw_assignment_consistent",
            "check((nw_part_number_assigned AND nw_part_number IS NOT NULL) OR "
            "(NOT nw_part_number_assigned AND nw_part_number IS NULL))",
            "The NockWorks assignment flag and part number must be consistent.",
        ),
    ]

    @api.constrains("nw_part_category_id", "nw_part_type_id")
    def _check_part_classification(self):
        for product in self:
            if (
                product.nw_part_type_id
                and product.nw_part_type_id.category_id != product.nw_part_category_id
            ):
                raise ValidationError(_("The selected Part Type does not belong to the selected Part Category."))

    @api.onchange("nw_part_category_id")
    def _onchange_nw_part_category_id(self):
        for product in self:
            if (
                not product.nw_part_number_assigned
                and product.nw_part_type_id
                and product.nw_part_type_id.category_id != product.nw_part_category_id
            ):
                product.nw_part_type_id = False

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("nw_numbering_internal"):
            for vals in vals_list:
                if vals.get("nw_part_number") or vals.get("nw_part_number_assigned"):
                    raise ValidationError(_("NockWorks part numbers can only be assigned with the Generate Part Number button."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("nw_numbering_internal"):
            for product in self:
                if product.nw_part_number_assigned:
                    if "default_code" in vals and vals["default_code"] != product.nw_part_number:
                        raise ValidationError(_("Internal Reference cannot differ from the assigned NockWorks part number."))
                    if "nw_part_number" in vals and vals["nw_part_number"] != product.nw_part_number:
                        raise ValidationError(_("An assigned NockWorks part number is immutable."))
                    if "nw_part_number_assigned" in vals and not vals["nw_part_number_assigned"]:
                        raise ValidationError(_("An assigned NockWorks part number cannot be removed."))
                    if "nw_part_category_id" in vals and vals["nw_part_category_id"] != product.nw_part_category_id.id:
                        raise ValidationError(_("Part Category cannot be changed after a part number is assigned."))
                    if "nw_part_type_id" in vals and vals["nw_part_type_id"] != product.nw_part_type_id.id:
                        raise ValidationError(_("Part Type cannot be changed after a part number is assigned."))
        return super().write(vals)

    def action_generate_nw_part_number(self):
        self.ensure_one()
        if self.nw_part_number_assigned or self.nw_part_number:
            raise UserError(_("This SKU already has a NockWorks part number."))
        if not self.nw_part_category_id or not self.nw_part_type_id:
            raise UserError(_("Select both a Part Category and a Part Type before generating a number."))
        if self.nw_part_type_id.category_id != self.nw_part_category_id:
            raise UserError(_("The selected Part Type does not belong to the selected Part Category."))

        sequence_number = self.nw_part_type_id._allocate_next_number()
        part_number = "%s-%s-%04d" % (
            self.nw_part_category_id.code,
            self.nw_part_type_id.code,
            sequence_number,
        )
        self.with_context(nw_numbering_internal=True).write(
            {
                "nw_part_number": part_number,
                "nw_part_number_assigned": True,
                "default_code": part_number,
            }
        )
        return True

    def copy(self, default=None):
        new_product = super().copy(default=default)
        source = self.ensure_one()
        values = {
            "nw_part_number": False,
            "nw_part_number_assigned": False,
        }
        if source.nw_part_number and new_product.default_code == source.nw_part_number:
            values["default_code"] = False
        new_product.with_context(nw_numbering_internal=True).write(values)
        return new_product


class ProductTemplate(models.Model):
    _inherit = "product.template"

    nw_part_category_id = fields.Many2one(
        "nockworks.part.category",
        string="Part Category",
        compute="_compute_nw_variant_fields",
        inverse="_inverse_nw_part_category_id",
    )
    nw_part_type_id = fields.Many2one(
        "nockworks.part.type",
        string="Part Type",
        compute="_compute_nw_variant_fields",
        inverse="_inverse_nw_part_type_id",
    )
    nw_part_number = fields.Char(
        string="Part Number", compute="_compute_nw_variant_fields", readonly=True
    )
    nw_part_number_assigned = fields.Boolean(
        string="Part Number Assigned", compute="_compute_nw_variant_fields", readonly=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Carry classifications entered on a new template to its first SKU.

        The template fields are non-stored proxies.  Their normal inverse runs
        before product.template.create has finished creating the first variant,
        so an explicit post-create transfer is required for the New Product form.
        """
        staged_classifications = [
            {
                field_name: vals[field_name]
                for field_name in ("nw_part_category_id", "nw_part_type_id")
                if field_name in vals
            }
            for vals in vals_list
        ]
        templates = super().create(vals_list)
        for template, classification in zip(templates, staged_classifications):
            if classification and len(template.product_variant_ids) == 1:
                template.product_variant_ids.write(classification)
        return templates

    @api.depends(
        "product_variant_ids.nw_part_category_id",
        "product_variant_ids.nw_part_type_id",
        "product_variant_ids.nw_part_number",
        "product_variant_ids.nw_part_number_assigned",
    )
    def _compute_nw_variant_fields(self):
        for template in self:
            variant = template.product_variant_ids if len(template.product_variant_ids) == 1 else False
            template.nw_part_category_id = variant.nw_part_category_id if variant else False
            template.nw_part_type_id = variant.nw_part_type_id if variant else False
            template.nw_part_number = variant.nw_part_number if variant else False
            template.nw_part_number_assigned = variant.nw_part_number_assigned if variant else False

    def _inverse_nw_part_category_id(self):
        for template in self:
            if len(template.product_variant_ids) == 1:
                template.product_variant_ids.nw_part_category_id = template.nw_part_category_id

    def _inverse_nw_part_type_id(self):
        for template in self:
            if len(template.product_variant_ids) == 1:
                template.product_variant_ids.nw_part_type_id = template.nw_part_type_id

    @api.onchange("nw_part_category_id")
    def _onchange_nw_part_category_id(self):
        for template in self:
            if (
                not template.nw_part_number_assigned
                and template.nw_part_type_id
                and template.nw_part_type_id.category_id != template.nw_part_category_id
            ):
                template.nw_part_type_id = False

    def action_generate_nw_part_number(self):
        self.ensure_one()
        if self.product_variant_count != 1:
            raise UserError(_("Part numbers must be generated on each individual product variant."))
        return self.product_variant_id.action_generate_nw_part_number()

    def copy(self, default=None):
        new_template = super().copy(default=default)
        source_numbers = set(self.product_variant_ids.mapped("nw_part_number")) - {False}
        for variant in new_template.product_variant_ids:
            values = {"nw_part_number": False, "nw_part_number_assigned": False}
            if variant.default_code in source_numbers:
                values["default_code"] = False
            variant.with_context(nw_numbering_internal=True).write(values)
        return new_template
