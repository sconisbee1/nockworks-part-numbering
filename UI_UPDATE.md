# Part numbering UI update — 19.0.2.1.1

Based on 0f57ebf; branch feature/part-numbering-ui-improvements.

* Template numbering fields use three responsive columns with labels above values.
* Review Conversion to Variants moves to the native form Actions menu, restricted
  to Inventory managers. It calls the unchanged action_nw_convert method, including
  its eligibility checks and current-template handling. The entry may remain visible
  for ineligible products; the existing server-side error prevents conversion.
* The wizard has Original product, Historical usage review and Conversion approval
  sections, a visible attribute selector, full-width reason, and adjacent checkbox
  and label. Existing warnings and footer actions are retained.
* New wizard presentation fields are computed and non-stored. They reuse the exact
  existing query loop; preview remains available unchanged. No database columns,
  allocation logic, security rules, conversion logic or migrations were changed.

Per the owner's instruction, no local test environment, layout tests or screenshots
were used. Browser rendering and Odoo installation/upgrade validation are unverified
for this patch; existing historical test reports apply to the base revision only.

For manual deployment, back up the live database and matching filestore, replace
only the addon with this branch's code, restart Odoo and upgrade
nockworks_part_numbering using the established configuration. Expected installed
version: 19.0.2.1.1. No new migration script is included, and issued numbers must not
change. Use the existing deployment/rollback procedure in DEPLOYMENT.md.
