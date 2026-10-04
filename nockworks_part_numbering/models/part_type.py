import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class NockWorksPartType(models.Model):
    _name = "nockworks.part.type"
    _description = "NockWorks Part Type"
    _order = "category_code, code, name, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    category_id = fields.Many2one(
        "nockworks.part.category", required=True, ondelete="restrict", index=True
    )
    category_code = fields.Char(related="category_id.code", store=True, index=True)
    active = fields.Boolean(default=True)
    description = fields.Text()
    next_number = fields.Integer(default=1, required=True)
    sequence_exhausted = fields.Boolean(default=False, readonly=True, copy=False)

    _category_code_unique = models.Constraint(
        "unique(category_id, code)",
        "The Part Type code must be unique within its Part Category.",
    )
    _next_number_range = models.Constraint(
        "check(next_number >= 1 AND next_number <= 9999)",
        "The next number must be between 1 and 9999.",
    )

    @api.constrains("code")
    def _check_code(self):
        for part_type in self:
            if not re.fullmatch(r"[0-9]{2}", part_type.code or ""):
                raise ValidationError(_("Part Type code must contain exactly two digits."))

    def write(self, vals):
        if "sequence_exhausted" in vals and not self.env.context.get("nw_sequence_allocation"):
            raise ValidationError(_("Sequence exhaustion is managed automatically."))
        if "next_number" in vals:
            new_number = vals["next_number"]
            for part_type in self:
                if new_number < part_type.next_number:
                    raise ValidationError(_("The next number cannot be decreased because issued numbers must never be reused."))
                if part_type.sequence_exhausted and new_number != part_type.next_number:
                    raise ValidationError(_("An exhausted sequence cannot be restarted."))
        return super().write(vals)

    def _allocate_next_number(self):
        """Atomically reserve and return one number from this classification."""
        self.ensure_one()
        self.env.cr.execute(
            """
                UPDATE nockworks_part_type
                   SET next_number = CASE
                           WHEN next_number < 9999 THEN next_number + 1
                           ELSE next_number
                       END,
                       sequence_exhausted = (next_number = 9999),
                       write_date = NOW(),
                       write_uid = %s
                 WHERE id = %s
                   AND sequence_exhausted = FALSE
                   AND next_number BETWEEN 1 AND 9999
             RETURNING CASE
                           WHEN sequence_exhausted THEN 9999
                           ELSE next_number - 1
                       END
            """,
            (self.env.uid, self.id),
        )
        row = self.env.cr.fetchone()
        self.invalidate_recordset(["next_number", "sequence_exhausted", "write_date", "write_uid"])
        if not row:
            raise UserError(
                _(
                    "The sequence for Part Category %(category)s and Part Type %(type)s is exhausted (maximum 9999).",
                    category=self.category_id.code,
                    type=self.code,
                )
            )
        return row[0]
