"""
Tests for the DPP Synthetic Data Generator

Validates that the generated data meets structural and business requirements:
- Correct record counts
- Material percentages sum to ~100%
- Compliance status distribution matches targets
- All foreign key relationships are valid
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

# The generator file has a numeric prefix (02_synthetic_data_generator.py)
# which is not a valid Python module name, so we use importlib to load it.
_GENERATOR_PATH = Path(__file__).parent.parent / "src" / "foundation" / "02_synthetic_data_generator.py"
_spec = importlib.util.spec_from_file_location("synthetic_data_generator", _GENERATOR_PATH)
_module = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_module)  # type: ignore[union-attr]
DPPDataGenerator = _module.DPPDataGenerator


@pytest.fixture(scope="module")
def generator() -> DPPDataGenerator:
    """Create and run the generator once for the furniture-profile tests.

    Pinned to furniture explicitly: the default profile is now `battery`, but
    the structural tests below assert furniture-specific values (manufacturer,
    categories, carbon ranges). Battery/default behaviour is covered separately
    in TestProfiles.
    """
    gen = DPPDataGenerator(seed=42, profile="furniture")
    gen.generate_all()
    return gen


# ---------------------------------------------------------------------------
# Industry-profile flexibility
# ---------------------------------------------------------------------------

class TestProfiles:
    """The data generator must support multiple industry profiles."""

    def test_battery_profile_generates_valid_data(self) -> None:
        gen = DPPDataGenerator(seed=42, profile="battery")
        gen.generate_all()

        # Battery manufacturer + categories, not furniture.
        assert gen.manufacturer["name"] == "VoltCore Energy AB"
        cats = {p["product_category"] for p in gen.passports}
        assert cats == {"EV Battery", "Industrial Battery", "LMT Battery", "Portable Battery"}

        # Same structural guarantees as furniture.
        ids = [p["product_id"] for p in gen.passports]
        assert len(ids) == len(set(ids)), "product_id must be unique"
        assert all(pid.startswith("VC-") for pid in ids)

        sums: dict[str, float] = {}
        for m in gen.materials:
            sums[m["passport_id"]] = sums.get(m["passport_id"], 0.0) + m["percentage_by_weight"]
        assert all(99.5 <= v <= 100.5 for v in sums.values())

        supplier_ids = {s["supplier_id"] for s in gen.suppliers}
        assert all(o["supplier_id"] in supplier_ids for o in gen.origins)

        # Battery carbon footprints are far higher than furniture (EV packs).
        assert max(i["carbon_footprint_kg"] for i in gen.impacts) > 1000
        # Battery chemistry includes hazardous materials.
        assert any(m["hazardous_flag"] for m in gen.materials)

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(ValueError):
            DPPDataGenerator(seed=42, profile="nonexistent")

    def test_default_profile_is_battery(self) -> None:
        """The default profile is now battery (the first mandatory EU DPP)."""
        gen = DPPDataGenerator(seed=42)
        gen.generate_all()
        assert gen.profile_name == "battery"
        assert gen.manufacturer["name"] == "VoltCore Energy AB"


class TestBatteryRealism:
    """Battery-profile realism grounded in Reg. 2023/1542 (Annex XIII)."""

    @pytest.fixture(scope="class")
    def battery(self) -> DPPDataGenerator:
        gen = DPPDataGenerator(seed=42, profile="battery")
        gen.generate_all()
        return gen

    def test_phased_regulations_always_pending(self, battery: DPPDataGenerator) -> None:
        """CF (Art.7), recycled content (Art.8), due diligence (Art.48) are
        emitted for every passport and are always `pending` (not yet applicable
        at the Feb-2027 launch)."""
        phased_names = {
            "Battery Carbon Footprint Declaration",
            "Recycled Content Share",
            "Supply Chain Due Diligence",
        }
        phased = [r for r in battery.compliance if r["regulation_name"] in phased_names]
        assert len(phased) == len(battery.passports) * 3
        assert all(r["compliance_status"] == "pending" for r in phased)
        assert all(r["notes"] for r in phased)

    def test_state_of_health_only_for_rechargeable(self, battery: DPPDataGenerator) -> None:
        rechargeable = {"EV Battery", "Industrial Battery", "LMT Battery"}
        cat = {p["passport_id"]: p["product_category"] for p in battery.passports}
        for c in battery.circularity:
            if cat[c["passport_id"]] in rechargeable:
                assert c["state_of_health_pct"] is not None
                assert 0 <= c["state_of_health_pct"] <= 100
                assert c["cycle_count"] is not None
            else:  # Portable Battery = no BMS/SoH
                assert c["state_of_health_pct"] is None

    def test_multitier_components_span_mine_to_pack(self, battery: DPPDataGenerator) -> None:
        names = {o["component_name"] for o in battery.origins}
        assert any("raw material" in n for n in names), "deepest tier (mining) missing"
        assert "Battery cell" in names
        assert any("module" in n.lower() or "pack" in n.lower() for n in names)

    def test_furniture_has_no_dynamic_data(self) -> None:
        gen = DPPDataGenerator(seed=42, profile="furniture")
        gen.generate_all()
        assert all(c["state_of_health_pct"] is None for c in gen.circularity)


# ---------------------------------------------------------------------------
# Record count tests
# ---------------------------------------------------------------------------

class TestRecordCounts:
    """Verify expected record counts."""

    def test_manufacturer_count(self, generator: DPPDataGenerator) -> None:
        assert generator.manufacturer is not None
        assert generator.manufacturer["name"] == "NordicForm AB"

    def test_supplier_count(self, generator: DPPDataGenerator) -> None:
        assert len(generator.suppliers) == 50

    def test_product_count(self, generator: DPPDataGenerator) -> None:
        count = len(generator.passports)
        assert 490 <= count <= 510, f"Expected ~500 products, got {count}"

    def test_product_id_unique(self, generator: DPPDataGenerator) -> None:
        """product_id must be globally unique (uq_product_id constraint)."""
        ids = [pp["product_id"] for pp in generator.passports]
        dupes = [pid for pid, n in Counter(ids).items() if n > 1]
        assert not dupes, f"Duplicate product_id values would fail seed: {dupes[:5]}"

    def test_has_origin_records(self, generator: DPPDataGenerator) -> None:
        assert len(generator.origins) > 0
        # At least 1 origin per product, could be up to 5
        assert len(generator.origins) >= len(generator.passports)

    def test_has_material_records(self, generator: DPPDataGenerator) -> None:
        assert len(generator.materials) > 0
        # At least 2 materials per product
        assert len(generator.materials) >= len(generator.passports) * 2

    def test_has_impact_records(self, generator: DPPDataGenerator) -> None:
        # 1 impact record per passport
        assert len(generator.impacts) == len(generator.passports)

    def test_has_compliance_records(self, generator: DPPDataGenerator) -> None:
        assert len(generator.compliance) > 0
        # At least 1 compliance record per product
        assert len(generator.compliance) >= len(generator.passports)

    def test_has_circularity_records(self, generator: DPPDataGenerator) -> None:
        # 1 circularity record per passport
        assert len(generator.circularity) == len(generator.passports)

    def test_has_disposal_records(self, generator: DPPDataGenerator) -> None:
        assert len(generator.disposal) > 0
        assert len(generator.disposal) >= len(generator.passports)


# ---------------------------------------------------------------------------
# Material composition tests
# ---------------------------------------------------------------------------

class TestMaterialComposition:
    """Verify material percentages are realistic."""

    def test_percentages_sum_to_100(self, generator: DPPDataGenerator) -> None:
        """Material percentages per product should sum to ~100%."""
        passport_materials: dict[str, float] = {}
        for mat in generator.materials:
            pid = mat["passport_id"]
            passport_materials.setdefault(pid, 0.0)
            passport_materials[pid] += mat["percentage_by_weight"]

        failures = []
        for pid, total in passport_materials.items():
            if not (99.5 <= total <= 100.5):
                failures.append((pid, total))

        assert len(failures) == 0, (
            f"{len(failures)} products have material percentages not summing to ~100%. "
            f"First 5: {failures[:5]}"
        )

    def test_material_count_per_product(self, generator: DPPDataGenerator) -> None:
        """Each product should have 2-8 materials."""
        counts: Counter[str] = Counter()
        for mat in generator.materials:
            counts[mat["passport_id"]] += 1

        for pid, count in counts.items():
            assert 2 <= count <= 8, (
                f"Product {pid} has {count} materials (expected 2-8)"
            )

    def test_individual_percentages_valid(self, generator: DPPDataGenerator) -> None:
        """Each material percentage should be between 0 and 100."""
        for mat in generator.materials:
            pct = mat["percentage_by_weight"]
            assert 0 <= pct <= 100, (
                f"Material {mat['material_id']} has invalid percentage: {pct}"
            )


# ---------------------------------------------------------------------------
# Compliance distribution tests
# ---------------------------------------------------------------------------

class TestComplianceDistribution:
    """Verify compliance status distribution matches ~85/10/5 target."""

    def test_compliance_distribution(self, generator: DPPDataGenerator) -> None:
        """Distribution should be roughly 85% compliant, 10% pending, 5% non-compliant."""
        counts = Counter(rec["compliance_status"] for rec in generator.compliance)
        total = sum(counts.values())

        compliant_pct = counts.get("compliant", 0) / total * 100
        pending_pct = counts.get("pending", 0) / total * 100
        non_compliant_pct = counts.get("non_compliant", 0) / total * 100

        # Allow +/- 8% tolerance for randomness (seeded, but sample size effects)
        assert 75 <= compliant_pct <= 95, (
            f"Compliant: {compliant_pct:.1f}% (expected ~85%)"
        )
        assert 2 <= pending_pct <= 20, (
            f"Pending: {pending_pct:.1f}% (expected ~10%)"
        )
        assert 0 <= non_compliant_pct <= 15, (
            f"Non-compliant: {non_compliant_pct:.1f}% (expected ~5%)"
        )

    def test_all_statuses_present(self, generator: DPPDataGenerator) -> None:
        """All three compliance statuses should appear in the data."""
        statuses = {rec["compliance_status"] for rec in generator.compliance}
        assert "compliant" in statuses
        assert "pending" in statuses
        assert "non_compliant" in statuses


# ---------------------------------------------------------------------------
# Foreign key integrity tests
# ---------------------------------------------------------------------------

class TestForeignKeyIntegrity:
    """Verify all FK relationships are valid."""

    def test_passport_manufacturer_fk(self, generator: DPPDataGenerator) -> None:
        """All passports reference the valid manufacturer."""
        mfg_id = generator.manufacturer["manufacturer_id"]
        for pp in generator.passports:
            assert pp["manufacturer_id"] == mfg_id, (
                f"Passport {pp['passport_id']} references unknown manufacturer "
                f"{pp['manufacturer_id']}"
            )

    def test_origin_passport_fk(self, generator: DPPDataGenerator) -> None:
        """All origin records reference a valid passport."""
        passport_ids = {pp["passport_id"] for pp in generator.passports}
        for origin in generator.origins:
            assert origin["passport_id"] in passport_ids, (
                f"Origin {origin['origin_id']} references unknown passport "
                f"{origin['passport_id']}"
            )

    def test_origin_supplier_fk(self, generator: DPPDataGenerator) -> None:
        """All origin records reference a valid supplier."""
        supplier_ids = {s["supplier_id"] for s in generator.suppliers}
        for origin in generator.origins:
            assert origin["supplier_id"] in supplier_ids, (
                f"Origin {origin['origin_id']} references unknown supplier "
                f"{origin['supplier_id']}"
            )

    def test_supplier_parent_fk(self, generator: DPPDataGenerator) -> None:
        """Every parent_supplier_id references a valid supplier (or is None)."""
        supplier_ids = {s["supplier_id"] for s in generator.suppliers}
        for s in generator.suppliers:
            parent = s["parent_supplier_id"]
            if parent is not None:
                assert parent in supplier_ids, (
                    f"Supplier {s['supplier_id']} has unknown parent {parent}"
                )


# ---------------------------------------------------------------------------
# Multi-tier supplier hierarchy tests
# ---------------------------------------------------------------------------

class TestSupplierHierarchy:
    """Verify the multi-tier supplier graph (parent_supplier_id)."""

    def test_all_suppliers_have_parent_field(self, generator: DPPDataGenerator) -> None:
        for s in generator.suppliers:
            assert "parent_supplier_id" in s

    def test_tier1_has_no_parent(self, generator: DPPDataGenerator) -> None:
        """Tier-1 (direct) suppliers are the roots — no parent."""
        for s in generator.suppliers:
            if s["tier"] == 1:
                assert s["parent_supplier_id"] is None, (
                    f"Tier-1 supplier {s['supplier_id']} should have no parent"
                )

    def test_deeper_tiers_have_parent(self, generator: DPPDataGenerator) -> None:
        """Every tier-2/3 supplier links to a parent one tier closer to the OEM."""
        by_id = {s["supplier_id"]: s for s in generator.suppliers}
        for s in generator.suppliers:
            if s["tier"] > 1:
                parent = by_id.get(s["parent_supplier_id"])
                assert parent is not None, (
                    f"Tier-{s['tier']} supplier {s['supplier_id']} has no parent"
                )
                assert parent["tier"] == s["tier"] - 1, (
                    f"Supplier {s['supplier_id']} (tier {s['tier']}) parent is "
                    f"tier {parent['tier']}, expected {s['tier'] - 1}"
                )

    def test_no_cycles(self, generator: DPPDataGenerator) -> None:
        """Walking parents from any supplier terminates at a tier-1 root."""
        by_id = {s["supplier_id"]: s for s in generator.suppliers}
        for s in generator.suppliers:
            seen: set[str] = set()
            node = s
            while node["parent_supplier_id"] is not None:
                assert node["supplier_id"] not in seen, (
                    f"Cycle detected starting at {s['supplier_id']}"
                )
                seen.add(node["supplier_id"])
                node = by_id[node["parent_supplier_id"]]
            assert node["tier"] == 1, "Chain should terminate at a tier-1 supplier"

    def test_materials_passport_fk(self, generator: DPPDataGenerator) -> None:
        """All material records reference a valid passport."""
        passport_ids = {pp["passport_id"] for pp in generator.passports}
        for mat in generator.materials:
            assert mat["passport_id"] in passport_ids

    def test_impact_passport_fk(self, generator: DPPDataGenerator) -> None:
        """All impact records reference a valid passport."""
        passport_ids = {pp["passport_id"] for pp in generator.passports}
        for impact in generator.impacts:
            assert impact["passport_id"] in passport_ids

    def test_compliance_passport_fk(self, generator: DPPDataGenerator) -> None:
        """All compliance records reference a valid passport."""
        passport_ids = {pp["passport_id"] for pp in generator.passports}
        for rec in generator.compliance:
            assert rec["passport_id"] in passport_ids

    def test_circularity_passport_fk(self, generator: DPPDataGenerator) -> None:
        """All circularity records reference a valid passport."""
        passport_ids = {pp["passport_id"] for pp in generator.passports}
        for rec in generator.circularity:
            assert rec["passport_id"] in passport_ids

    def test_disposal_passport_fk(self, generator: DPPDataGenerator) -> None:
        """All disposal records reference a valid passport."""
        passport_ids = {pp["passport_id"] for pp in generator.passports}
        for rec in generator.disposal:
            assert rec["passport_id"] in passport_ids


# ---------------------------------------------------------------------------
# Data quality tests
# ---------------------------------------------------------------------------

class TestDataQuality:
    """Additional data quality checks."""

    def test_product_categories(self, generator: DPPDataGenerator) -> None:
        """All four product categories should be represented."""
        categories = {pp["product_category"] for pp in generator.passports}
        assert "Furniture" in categories
        assert "Textiles" in categories
        assert "Lighting" in categories
        assert "Storage" in categories

    def test_supplier_countries(self, generator: DPPDataGenerator) -> None:
        """Suppliers should span multiple countries."""
        countries = {s["country"] for s in generator.suppliers}
        assert len(countries) >= 8, f"Only {len(countries)} unique supplier countries"

    def test_supplier_tiers(self, generator: DPPDataGenerator) -> None:
        """All three supplier tiers should be represented."""
        tiers = {s["tier"] for s in generator.suppliers}
        assert tiers == {1, 2, 3}

    def test_passport_status_distribution(self, generator: DPPDataGenerator) -> None:
        """Most passports should be active."""
        statuses = Counter(pp["passport_status"] for pp in generator.passports)
        total = sum(statuses.values())
        active_pct = statuses.get("active", 0) / total * 100
        assert active_pct >= 60, f"Only {active_pct:.1f}% active passports"

    def test_incomplete_passports_exist(self, generator: DPPDataGenerator) -> None:
        """~10% of passports should have missing fields."""
        incomplete = sum(
            1 for pp in generator.passports if pp["serial_number"] is None
        )
        pct = incomplete / len(generator.passports) * 100
        assert 3 <= pct <= 20, f"Incomplete passports: {pct:.1f}% (expected ~10%)"

    def test_carbon_ranges(self, generator: DPPDataGenerator) -> None:
        """Carbon footprints should be in realistic ranges per category."""
        passport_cats = {
            pp["passport_id"]: pp["product_category"]
            for pp in generator.passports
        }
        ranges = {
            "Furniture": (20.0, 150.0),
            "Textiles": (5.0, 40.0),
            "Lighting": (10.0, 60.0),
            "Storage": (3.0, 20.0),
        }
        for impact in generator.impacts:
            cat = passport_cats[impact["passport_id"]]
            lo, hi = ranges[cat]
            carbon = impact["carbon_footprint_kg"]
            assert lo <= carbon <= hi, (
                f"Carbon {carbon} out of range [{lo}, {hi}] for {cat}"
            )

    def test_deterministic_output(self) -> None:
        """Running the generator twice with the same seed produces identical data."""
        gen1 = DPPDataGenerator(seed=42)
        gen1.generate_all()

        gen2 = DPPDataGenerator(seed=42)
        gen2.generate_all()

        assert len(gen1.passports) == len(gen2.passports)
        assert gen1.passports[0]["passport_id"] == gen2.passports[0]["passport_id"]
        assert gen1.passports[-1]["product_name"] == gen2.passports[-1]["product_name"]
