import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NockWorksPartCategory(models.Model):
    _name = "nockworks.part.category"
    _description = "NockWorks Part Category"
    _order = "code, name, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    description = fields.Text()
    type_ids = fields.One2many("nockworks.part.type", "category_id", string="Part Types")

    _sql_constraints = [
        ("code_unique", "unique(code)", "The part category code must be unique."),
    ]

    @api.constrains("code")
    def _check_code(self):
        for category in self:
            if not re.fullmatch(r"[0-9]{3}", category.code or ""):
                raise ValidationError(_("Part Category code must contain exactly three digits."))

