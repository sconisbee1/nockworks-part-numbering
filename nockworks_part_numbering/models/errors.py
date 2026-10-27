"""Map expected database collisions to useful errors without swallowing transaction retries."""
from functools import wraps
from psycopg2 import IntegrityError
from odoo import _
from odoo.exceptions import ValidationError


def reference_errors(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            with self.env.cr.savepoint():
                return method(self, *args, **kwargs)
        except IntegrityError as error:
            constraint = error.diag.constraint_name or ''
            if constraint.startswith(('nw_reference_', 'nw_default_code_', 'nockworks_reference_allocation_')):
                raise ValidationError(_('This NockWorks reference or suffix has already been issued and is permanently reserved. Review existing and archived products.')) from error
            raise
    return guarded
