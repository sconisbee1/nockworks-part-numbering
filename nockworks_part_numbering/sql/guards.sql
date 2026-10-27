-- Run by initialize() under upgrade table locks. All identifiers are module-owned.
CREATE OR REPLACE FUNCTION nw_reference_actor() RETURNS integer LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('nockworks.actor_uid', true), '')::integer
$$;

CREATE OR REPLACE FUNCTION nw_guard_allocation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Issued NockWorks reservations cannot be deleted'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_permanent';
    END IF;
    IF NEW.reference IS DISTINCT FROM OLD.reference OR NEW.family_key IS DISTINCT FROM OLD.family_key
       OR NEW.original_product_id IS DISTINCT FROM OLD.original_product_id
       OR NEW.suffix IS DISTINCT FROM OLD.suffix OR NEW.kind IS DISTINCT FROM OLD.kind THEN
        RAISE EXCEPTION 'Issued reference identity and ownership snapshots are immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_identity';
    END IF;
    IF OLD.retired AND NOT NEW.retired THEN
        RAISE EXCEPTION 'Retired references cannot be reactivated'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_permanent';
    END IF;
    IF NEW.family_id IS DISTINCT FROM OLD.family_id AND NOT (
        NEW.family_id IS NULL AND NOT EXISTS (SELECT 1 FROM product_template WHERE id = OLD.family_id)
    ) THEN
        RAISE EXCEPTION 'Reference family ownership cannot be reassigned'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    IF NEW.product_id IS DISTINCT FROM OLD.product_id AND NEW.product_id IS NOT NULL THEN
        RAISE EXCEPTION 'An issued reference cannot be reassigned to a SKU'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    -- Foreign-key SET NULL on deletion must leave a retired tombstone, never a free slot.
    IF (OLD.product_id IS NOT NULL AND NEW.product_id IS NULL)
       OR (OLD.family_id IS NOT NULL AND NEW.family_id IS NULL) THEN
        NEW.retired := true;
        NEW.release_reason := COALESCE(NEW.release_reason,
            CASE WHEN NEW.family_id IS NULL THEN 'Family deleted' ELSE 'SKU ownership released' END);
    END IF;
    IF NEW.retired THEN
        NEW.product_id := NULL;
        NEW.released_at := COALESCE(NEW.released_at, transaction_timestamp());
        NEW.released_by := COALESCE(NEW.released_by, nw_reference_actor());
    END IF;
    RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION nw_reserve_product_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allocation nockworks_reference_allocation%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        UPDATE nockworks_reference_allocation SET retired = true, product_id = NULL,
            release_reason = COALESCE(release_reason, 'SKU deleted'), write_date = NOW(), write_uid = nw_reference_actor()
            WHERE original_product_id = OLD.id AND NOT retired;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.default_code IS DISTINCT FROM NEW.default_code THEN
        UPDATE nockworks_reference_allocation SET retired = true, product_id = NULL,
            release_reason = COALESCE(release_reason,
                CASE WHEN NEW.default_code IS NULL OR NEW.default_code = '' THEN 'Internal Reference cleared' ELSE 'Internal Reference changed' END),
            write_date = NOW(), write_uid = nw_reference_actor()
            WHERE reference = OLD.default_code AND product_id = OLD.id AND NOT retired;
    END IF;
    IF NEW.default_code IS NULL OR NEW.default_code !~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}(-[0-9]{2})?$' THEN RETURN NEW; END IF;
    INSERT INTO nockworks_reference_allocation
        (reference, kind, family_id, family_key, suffix, product_id, original_product_id, reason, retired,
         create_uid, write_uid, create_date, write_date)
        VALUES (NEW.default_code, 'manual', NEW.product_tmpl_id, NEW.product_tmpl_id, NULL, NEW.id, NEW.id,
                'Internal Reference reservation', false, nw_reference_actor(), nw_reference_actor(), NOW(), NOW())
        ON CONFLICT (reference) DO NOTHING;
    SELECT * INTO allocation FROM nockworks_reference_allocation WHERE reference = NEW.default_code FOR UPDATE;
    IF allocation.retired OR allocation.product_id IS DISTINCT FROM NEW.id THEN
        RAISE EXCEPTION 'NockWorks reference % is permanently reserved', NEW.default_code
            USING ERRCODE = '23505', CONSTRAINT = 'nw_reference_reserved';
    END IF;
    IF allocation.original_product_id IS DISTINCT FROM NEW.id
       OR allocation.family_id IS DISTINCT FROM NEW.product_tmpl_id
       OR allocation.family_key IS DISTINCT FROM NEW.product_tmpl_id THEN
        RAISE EXCEPTION 'Reference, SKU and family ownership do not agree'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION nw_assert_product(product_key integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p product_product%ROWTYPE; t product_template%ROWTYPE; a nockworks_reference_allocation%ROWTYPE;
BEGIN
    SELECT * INTO p FROM product_product WHERE id = product_key;
    IF NOT FOUND THEN RETURN; END IF;
    SELECT * INTO t FROM product_template WHERE id = p.product_tmpl_id;
    IF p.default_code ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}(-[0-9]{2})?$' THEN
        SELECT * INTO a FROM nockworks_reference_allocation WHERE reference = p.default_code;
        IF NOT FOUND OR a.retired OR a.product_id IS DISTINCT FROM p.id OR a.original_product_id IS DISTINCT FROM p.id
           OR a.family_id IS DISTINCT FROM p.product_tmpl_id OR a.family_key IS DISTINCT FROM p.product_tmpl_id THEN
            RAISE EXCEPTION 'SKU % does not own its reference allocation', p.id
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
    ELSIF p.nw_part_number_assigned THEN
        RAISE EXCEPTION 'Assigned SKU % has an invalid NockWorks reference', p.id
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_format';
    END IF;
    IF p.nw_part_number_assigned AND (p.nw_part_category_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM nockworks_part_type part_type WHERE part_type.id = p.nw_part_type_id
            AND part_type.category_id = p.nw_part_category_id)) THEN
        RAISE EXCEPTION 'Assigned SKU lacks a consistent classification'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    IF p.nw_part_number_assigned THEN
        IF p.default_code IS DISTINCT FROM p.nw_part_number THEN
            RAISE EXCEPTION 'Assigned reference differs from Internal Reference'
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
        IF t.nw_numbering_state = 'single' THEN
            IF a.kind != 'base' OR a.suffix != 0 OR COALESCE(p.nw_variant_number, 0) != 0 OR p.default_code IS DISTINCT FROM t.nw_base_part_number THEN
                RAISE EXCEPTION 'Single SKU does not own its family base' USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
            END IF;
        ELSIF t.nw_numbering_state = 'variants' THEN
            IF a.kind != 'variant' OR a.suffix IS DISTINCT FROM p.nw_variant_number
               OR p.default_code IS DISTINCT FROM (t.nw_base_part_number || '-' || lpad(p.nw_variant_number::text, 2, '0')) THEN
                RAISE EXCEPTION 'Variant suffix, full reference and family base do not agree'
                    USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
            END IF;
        ELSIF t.nw_numbering_state != 'legacy' OR a.kind != 'manual' OR COALESCE(p.nw_variant_number, 0) != 0 THEN
            RAISE EXCEPTION 'Assigned SKU has no valid numbered family'
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
        IF t.nw_numbering_state != 'legacy' AND p.nw_base_part_number IS DISTINCT FROM t.nw_base_part_number THEN
            RAISE EXCEPTION 'Stored SKU base differs from its family' USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
        IF t.nw_numbering_state != 'legacy' AND
           (p.nw_part_category_id IS DISTINCT FROM t.nw_part_category_id OR p.nw_part_type_id IS DISTINCT FROM t.nw_part_type_id) THEN
            RAISE EXCEPTION 'SKU classification differs from its family'
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
    ELSIF t.nw_numbering_state IN ('single', 'variants') OR (a.id IS NOT NULL AND a.kind != 'manual') THEN
        RAISE EXCEPTION 'Numbered family has an unassigned or incorrectly assigned SKU'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
END; $$;

CREATE OR REPLACE FUNCTION nw_assert_allocation(allocation_key integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE a nockworks_reference_allocation%ROWTYPE; t product_template%ROWTYPE; p product_product%ROWTYPE;
BEGIN
    SELECT * INTO a FROM nockworks_reference_allocation WHERE id = allocation_key;
    IF NOT FOUND THEN RETURN; END IF;
    IF a.family_id IS DISTINCT FROM a.family_key THEN
        IF a.family_id IS NOT NULL OR EXISTS (SELECT 1 FROM product_template WHERE id = a.family_key) THEN
            RAISE EXCEPTION 'Allocation family link and immutable snapshot differ'
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
    END IF;
    SELECT * INTO t FROM product_template WHERE id = a.family_key;
    IF a.kind IN ('base', 'variant') AND t.id IS NOT NULL THEN
        IF (a.kind = 'base' AND a.reference IS DISTINCT FROM t.nw_base_part_number)
           OR (a.kind = 'variant' AND a.reference IS DISTINCT FROM (t.nw_base_part_number || '-' || lpad(a.suffix::text, 2, '0'))) THEN
            RAISE EXCEPTION 'Allocation reference differs from its permanent family base/suffix'
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
    END IF;
    IF a.retired THEN
        IF a.product_id IS NOT NULL THEN
            RAISE EXCEPTION 'Retired allocation still has a current SKU owner'
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
        RETURN;
    END IF;
    IF t.id IS NULL THEN
        RAISE EXCEPTION 'Active allocation has no live family' USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    IF a.kind = 'base' AND a.product_id IS NULL AND COALESCE(a.original_product_id, 0) = 0 THEN RETURN; END IF;
    SELECT * INTO p FROM product_product WHERE id = a.product_id;
    IF NOT FOUND OR p.default_code IS DISTINCT FROM a.reference OR p.id IS DISTINCT FROM a.original_product_id
       OR p.product_tmpl_id IS DISTINCT FROM a.family_key THEN
        RAISE EXCEPTION 'Active allocation no longer belongs to its recorded SKU/family'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    PERFORM nw_assert_product(p.id);
END; $$;

CREATE OR REPLACE FUNCTION nw_assert_family(family_key integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE t product_template%ROWTYPE; item record; base_record nockworks_reference_allocation%ROWTYPE;
BEGIN
    SELECT * INTO t FROM product_template WHERE id = family_key;
    IF NOT FOUND THEN RETURN; END IF;
    IF t.nw_base_part_number IS NOT NULL THEN
        SELECT * INTO base_record FROM nockworks_reference_allocation WHERE reference = t.nw_base_part_number;
        IF NOT FOUND OR base_record.kind != 'base' OR base_record.family_id IS DISTINCT FROM t.id
           OR base_record.family_key IS DISTINCT FROM t.id OR t.nw_numbering_state NOT IN ('single', 'variants')
           OR t.nw_base_part_number !~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$'
           OR t.nw_part_category_id IS NULL OR t.nw_part_type_id IS NULL THEN
            RAISE EXCEPTION 'Family does not own a valid reserved base'
                USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
        END IF;
    ELSIF t.nw_numbering_state IN ('single', 'variants') THEN
        RAISE EXCEPTION 'Numbered family has no base' USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    IF t.nw_next_variant IS NULL OR t.nw_next_variant NOT BETWEEN 1 AND 100 OR t.nw_next_variant <= COALESCE((SELECT max(suffix) FROM nockworks_reference_allocation WHERE family_id = t.id AND kind = 'variant'), 0) THEN
        RAISE EXCEPTION 'Variant counter cannot move behind issued allocations'
            USING ERRCODE = '23514', CONSTRAINT = 'nw_reference_owner';
    END IF;
    FOR item IN SELECT id FROM nockworks_reference_allocation WHERE family_id = t.id LOOP
        PERFORM nw_assert_allocation(item.id);
    END LOOP;
    FOR item IN SELECT id FROM product_product WHERE product_tmpl_id = t.id LOOP
        PERFORM nw_assert_product(item.id);
    END LOOP;
END; $$;

CREATE OR REPLACE FUNCTION nw_check_numbering_integrity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'product_template' THEN
        PERFORM nw_assert_family(NEW.id);
    ELSIF TG_TABLE_NAME = 'product_product' THEN
        IF TG_OP != 'DELETE' THEN PERFORM nw_assert_family(NEW.product_tmpl_id); END IF;
        IF TG_OP != 'INSERT' THEN PERFORM nw_assert_family(OLD.product_tmpl_id); END IF;
    ELSE
        PERFORM nw_assert_allocation(NEW.id);
        PERFORM nw_assert_family(NEW.family_key);
    END IF;
    RETURN NULL;
END; $$;

ALTER TABLE nockworks_reference_allocation ALTER COLUMN retired SET DEFAULT FALSE;
ALTER TABLE nockworks_reference_allocation ALTER COLUMN retired SET NOT NULL;
ALTER TABLE nockworks_reference_allocation DROP CONSTRAINT IF EXISTS nw_allocation_shape;
ALTER TABLE nockworks_reference_allocation ADD CONSTRAINT nw_allocation_shape CHECK (
    CASE kind
        WHEN 'manual' THEN suffix IS NULL
        WHEN 'base' THEN suffix IS NOT NULL AND suffix = 0 AND family_key IS NOT NULL
        WHEN 'variant' THEN suffix IS NOT NULL AND suffix BETWEEN 1 AND 99 AND family_key IS NOT NULL
                            AND original_product_id IS NOT NULL AND original_product_id > 0
        ELSE false
    END
);
CREATE TRIGGER nw_allocation_permanence BEFORE UPDATE OR DELETE ON nockworks_reference_allocation
    FOR EACH ROW EXECUTE FUNCTION nw_guard_allocation();
CREATE TRIGGER nw_reference_reservation AFTER INSERT OR UPDATE OF default_code, product_tmpl_id OR DELETE ON product_product
    FOR EACH ROW EXECUTE FUNCTION nw_reserve_product_reference();
CREATE CONSTRAINT TRIGGER nw_product_integrity AFTER INSERT OR UPDATE OR DELETE ON product_product
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nw_check_numbering_integrity();
CREATE CONSTRAINT TRIGGER nw_family_integrity AFTER INSERT OR UPDATE ON product_template
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nw_check_numbering_integrity();
CREATE CONSTRAINT TRIGGER nw_allocation_integrity AFTER INSERT OR UPDATE ON nockworks_reference_allocation
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nw_check_numbering_integrity();
