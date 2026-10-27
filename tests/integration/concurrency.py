"""Run using odoo shell against a disposable DB; commits are intentional.
Separate workers use separate PostgreSQL connections and retry whole transactions.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from psycopg2.errors import SerializationFailure, DeadlockDetected
from odoo import api, SUPERUSER_ID

category = env['nockworks.part.category'].create({'name': 'Concurrency fixture', 'code': '981'})
part_type = env['nockworks.part.type'].create({'name': 'Concurrent', 'code': '01', 'category_id': category.id})
attribute = env['product.attribute'].create({'name': 'Concurrent combinations', 'create_variant': 'dynamic'})
values = env['product.attribute.value'].create([{'name': str(i), 'attribute_id': attribute.id} for i in range(6)])
template = env['product.template'].create({'name': 'Concurrent family', 'nw_part_category_id': category.id,
    'nw_part_type_id': part_type.id, 'attribute_line_ids': [(0, 0, {'attribute_id': attribute.id, 'value_ids': [(6, 0, values.ids)]})]})
template_id = template.id
ptav_ids = template.attribute_line_ids.product_template_value_ids.ids
env.cr.commit()
barrier = Barrier(2)


def allocate(ptav_id):
    barrier.wait(timeout=30)
    for attempt in range(10):
        try:
            with env.registry.cursor() as cr:
                worker = api.Environment(cr, SUPERUSER_ID, {})
                family = worker['product.template'].browse(template_id)
                product = family._create_product_variant(worker['product.template.attribute.value'].browse(ptav_id))
                result = product.id, product.default_code, product.nw_variant_number
                cr.commit()
                return result
        except (SerializationFailure, DeadlockDetected):
            if attempt == 9:
                raise


results = []
with ThreadPoolExecutor(max_workers=2) as executor:
    for offset in range(0, 6, 2):
        results.extend(executor.map(allocate, ptav_ids[offset:offset + 2]))
assert len({item[0] for item in results}) == 6, results
assert len({item[1] for item in results}) == 6, results
assert sorted(item[2] for item in results) == list(range(1, 7)), results
env.invalidate_all()
assert env['product.template'].browse(template_id).nw_next_variant == 7
print('CONCURRENCY PASS: 6 native dynamic variants, 2 simultaneous connections, permanent suffixes 01..06', flush=True)
