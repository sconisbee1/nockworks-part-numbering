{
    "name": "NockWorks Part Numbering",
    "summary": "Concurrency-safe engineering part numbers for product SKUs",
    "version": "19.0.2.1.2",
    "category": "Inventory/Inventory",
    "license": "LGPL-3",
    "author": "NockWorks Innovations",
    "depends": ["stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/part_category_views.xml",
        "views/part_type_views.xml",
        "views/product_views.xml",
        "wizard/conversion_views.xml",
        "views/menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "assets": {
        "web.assets_backend": [
            "nockworks_part_numbering/static/src/js/variant_suffix.js",
            "nockworks_part_numbering/static/src/scss/part_numbering_ui.scss",
        ],
        "web.assets_tests": [
            "nockworks_part_numbering/static/tests/tours/variant_numbering.js",
            "nockworks_part_numbering/static/tests/tours/rfq_creation.js",
        ],
    },
    "installable": True,
    "application": True,
}
