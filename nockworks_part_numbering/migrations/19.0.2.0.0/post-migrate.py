from odoo import SUPERUSER_ID, api
from odoo.addons.nockworks_part_numbering.hooks import initialize


def migrate(cr, version):
    initialize(api.Environment(cr, SUPERUSER_ID, {}))
