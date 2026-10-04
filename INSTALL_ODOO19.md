# Odoo 19 deployment

The repository contains the addon in `nockworks_part_numbering/`. The repository
root is an addons directory, not an addon. Odoo scans only the immediate children
of each configured addons directory; it does not search repositories recursively.

For the existing NockWorks Docker deployment, keep the checkout outside the
mounted addons directory and link the actual addon into it:

```sh
mkdir -p ~/odoo19/repos
git clone https://github.com/sconisbee1/nockworks-part-numbering.git ~/odoo19/repos/nockworks_part_numbering
```

If `~/odoo19/addons/nockworks_part_numbering` already exists, preserve it outside
the mounted addons directory before adding the link. Only run the move when the
destination backup does not already exist:

```sh
mv -T ~/odoo19/addons/nockworks_part_numbering ~/odoo19/repos/nockworks_part_numbering_previous
ln -s ../repos/nockworks_part_numbering/nockworks_part_numbering ~/odoo19/addons/nockworks_part_numbering
```

For Docker, a host symlink to an unmounted directory will not resolve inside the
container. Instead use a direct bind mount for the addon in the existing Odoo
service's Compose `volumes` list (keep all existing volumes):

```yaml
- ./repos/nockworks_part_numbering/nockworks_part_numbering:/mnt/extra-addons/nockworks_part_numbering:ro
```

For this Docker approach do not create the host symlink. Preserve the old checkout
with the move above, add the mount, and recreate the Odoo service:

```sh
cd ~/odoo19
docker compose up -d
docker compose exec odoo ls /mnt/extra-addons/nockworks_part_numbering/__manifest__.py
docker compose logs --tail=100 odoo
```

Replace `odoo` if your Compose service uses another name. The configured
`addons_path` must include `/mnt/extra-addons` alongside its existing standard
addon paths. Enable developer mode, open Apps, Update Apps List, and search for
NockWorks Part Numbering. It is now an application and appears under the Apps
filter. Install it, or Upgrade it if already installed.

For a native server, either use the host symlink above or add the repository root
to `addons_path`, then restart the service and update the Apps list.

Update the checkout with `git -C ~/odoo19/repos/nockworks_part_numbering pull
--ff-only`, restart/recreate Odoo as appropriate, then Upgrade the addon.

This addon targets Odoo 19; upgrading the addon does not migrate an Odoo 18
database. Existing numbering fields and sequences are retained on module upgrade.
