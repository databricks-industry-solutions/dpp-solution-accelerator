"""
Digital Product Passport -- Synthetic Data Generator

Generates realistic test data for "NordicForm", a fictional Scandinavian
furniture manufacturer. Uses Faker with seed=42 for deterministic output.

Output: JSON files per table in src/foundation/data/

Usage:
    python 02_synthetic_data_generator.py
"""

from __future__ import annotations

import json
import os
import random
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from faker import Faker


def _script_dir() -> Path:
    """Directory of this script. Databricks serverless spark_python_task does
    not define __file__, so fall back to argv[0]."""
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path(sys.argv[0]).resolve().parent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEED = 42
NUM_SUPPLIERS = 50
NUM_PRODUCTS = 500
OUTPUT_DIR = _script_dir() / "data"
REFERENCE_DATE = date(2026, 3, 15)  # Fixed date for deterministic output

STYLE_MODIFIERS = [
    "Natural", "Dark Oak", "Walnut", "Classic", "Modern", "Compact", "Wide",
    "Tall", "Slim", "XL", "Mini", "Heritage", "Studio", "Nordic", "Coastal",
    "Urban", "Rustic",
]

SUPPLIER_COUNTRIES = [
    "SWE", "FIN", "NOR", "DNK", "DEU", "POL", "LTU", "LVA", "EST",
    "CZE", "PRT", "ITA", "CHN", "IND", "VNM",
]

PRODUCT_CATALOG: dict[str, list[dict[str, Any]]] = {
    "Furniture": [
        {"prefix": "BJORK", "type": "Dining Table"},
        {"prefix": "FJALL", "type": "Bookshelf"},
        {"prefix": "SKOG", "type": "Desk"},
        {"prefix": "ALVA", "type": "Armchair"},
        {"prefix": "GRAN", "type": "Coffee Table"},
        {"prefix": "VIDE", "type": "Side Table"},
        {"prefix": "STEN", "type": "Bench"},
        {"prefix": "LIND", "type": "Bed Frame"},
        {"prefix": "MOLN", "type": "Wardrobe"},
        {"prefix": "TALL", "type": "Dining Chair"},
        {"prefix": "BLAD", "type": "Stool"},
        {"prefix": "RONN", "type": "Shelving Unit"},
    ],
    "Textiles": [
        {"prefix": "DROM", "type": "Cushion Cover"},
        {"prefix": "VIND", "type": "Curtain"},
        {"prefix": "ROST", "type": "Rug"},
        {"prefix": "SOVA", "type": "Bedding Set"},
        {"prefix": "MJUK", "type": "Throw Blanket"},
        {"prefix": "TRAD", "type": "Table Runner"},
    ],
    "Lighting": [
        {"prefix": "STROM", "type": "Floor Lamp"},
        {"prefix": "LJUS", "type": "Table Lamp"},
        {"prefix": "GLOD", "type": "Pendant Light"},
        {"prefix": "SKYN", "type": "LED Fixture"},
        {"prefix": "SOLS", "type": "Wall Sconce"},
    ],
    "Storage": [
        {"prefix": "KLAR", "type": "Storage Box"},
        {"prefix": "FACK", "type": "Basket"},
        {"prefix": "HYLLA", "type": "Drawer Unit"},
        {"prefix": "PLATS", "type": "Organizer"},
    ],
}

CERTIFICATIONS = [
    "FSC", "PEFC", "GOTS", "OEKO-TEX Standard 100", "ISO 14001",
    "ISO 9001", "EU Ecolabel", "Cradle to Cradle", "REACH",
    "RoHS", "Blue Angel", "Nordic Swan", "GRS",
]

# Materials by category with realistic properties
MATERIAL_DB: dict[str, list[dict[str, Any]]] = {
    "Furniture": [
        {"name": "Solid Oak", "category": "Wood", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Solid Birch", "category": "Wood", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Solid Pine", "category": "Wood", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Particle Board", "category": "Wood Composite", "cas": None, "renewable": True, "hazardous": False},
        {"name": "MDF", "category": "Wood Composite", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Steel", "category": "Metal", "cas": "7439-89-6", "renewable": False, "hazardous": False},
        {"name": "Aluminium", "category": "Metal", "cas": "7429-90-5", "renewable": False, "hazardous": False},
        {"name": "Brass Hardware", "category": "Metal", "cas": None, "renewable": False, "hazardous": False},
        {"name": "Water-based Lacquer", "category": "Coating", "cas": None, "renewable": False, "hazardous": False},
        {"name": "Wood Oil Finish", "category": "Coating", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Polyurethane Foam", "category": "Foam", "cas": "9009-54-5", "renewable": False, "hazardous": False},
        {"name": "Natural Latex Foam", "category": "Foam", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Wool Felt", "category": "Textile", "cas": None, "renewable": True, "hazardous": False},
    ],
    "Textiles": [
        {"name": "Organic Cotton", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Cotton", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Linen", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Wool", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Recycled Polyester", "category": "Synthetic Fiber", "cas": "25038-59-9", "renewable": False, "hazardous": False},
        {"name": "Polyester", "category": "Synthetic Fiber", "cas": "25038-59-9", "renewable": False, "hazardous": False},
        {"name": "Viscose", "category": "Semi-synthetic Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Jute", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Textile Dye", "category": "Chemical", "cas": None, "renewable": False, "hazardous": False},
    ],
    "Lighting": [
        {"name": "Steel", "category": "Metal", "cas": "7439-89-6", "renewable": False, "hazardous": False},
        {"name": "Aluminium", "category": "Metal", "cas": "7429-90-5", "renewable": False, "hazardous": False},
        {"name": "Copper Wiring", "category": "Metal", "cas": "7440-50-8", "renewable": False, "hazardous": False},
        {"name": "Glass", "category": "Glass", "cas": None, "renewable": False, "hazardous": False},
        {"name": "Polycarbonate", "category": "Plastic", "cas": "25037-45-0", "renewable": False, "hazardous": False},
        {"name": "LED Module", "category": "Electronic", "cas": None, "renewable": False, "hazardous": False},
        {"name": "Opal Acrylic", "category": "Plastic", "cas": None, "renewable": False, "hazardous": False},
        {"name": "Linen Shade", "category": "Textile", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Powder Coating", "category": "Coating", "cas": None, "renewable": False, "hazardous": False},
    ],
    "Storage": [
        {"name": "Polypropylene", "category": "Plastic", "cas": "9003-07-0", "renewable": False, "hazardous": False},
        {"name": "Recycled Polypropylene", "category": "Plastic", "cas": "9003-07-0", "renewable": False, "hazardous": False},
        {"name": "HDPE", "category": "Plastic", "cas": "9002-88-4", "renewable": False, "hazardous": False},
        {"name": "Bamboo", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Seagrass", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Cotton Rope", "category": "Natural Fiber", "cas": None, "renewable": True, "hazardous": False},
        {"name": "Steel Wire", "category": "Metal", "cas": "7439-89-6", "renewable": False, "hazardous": False},
    ],
}

# Carbon footprint ranges per category (kg CO2e)
CARBON_RANGES: dict[str, tuple[float, float]] = {
    "Furniture": (20.0, 150.0),
    "Textiles": (5.0, 40.0),
    "Lighting": (10.0, 60.0),
    "Storage": (3.0, 20.0),
}

# Category-specific lifecycle phase splits (mfg, transport, use, eol)
# Each tuple is (min, max) for that phase's share of total carbon.
LIFECYCLE_SPLITS: dict[str, dict[str, tuple[float, float]]] = {
    "Furniture": {  # Heavy processing, low use-phase
        "manufacturing": (0.50, 0.65),
        "transport": (0.12, 0.20),
        "use_phase": (0.03, 0.10),
        "end_of_life": (0.10, 0.20),
    },
    "Textiles": {  # Global supply chain, significant use-phase (washing/drying)
        "manufacturing": (0.25, 0.35),
        "transport": (0.20, 0.30),
        "use_phase": (0.25, 0.40),
        "end_of_life": (0.05, 0.12),
    },
    "Lighting": {  # Electricity over product lifetime dominates
        "manufacturing": (0.15, 0.25),
        "transport": (0.05, 0.12),
        "use_phase": (0.50, 0.70),
        "end_of_life": (0.03, 0.08),
    },
    "Storage": {  # Simple products, mostly manufacturing
        "manufacturing": (0.55, 0.70),
        "transport": (0.15, 0.25),
        "use_phase": (0.02, 0.06),
        "end_of_life": (0.08, 0.15),
    },
}

REGULATIONS = [
    {"name": "ESPR - Ecodesign for Sustainable Products", "version": "2024/1781"},
    {"name": "EU REACH Regulation", "version": "EC 1907/2006"},
    {"name": "EU RoHS Directive", "version": "2011/65/EU"},
    {"name": "EU Timber Regulation", "version": "EU 995/2010"},
    {"name": "EU Packaging and Packaging Waste", "version": "94/62/EC"},
    {"name": "EU Waste Framework Directive", "version": "2008/98/EC"},
]

ISSUING_BODIES = [
    "TUV Rheinland", "Bureau Veritas", "SGS SA", "Intertek",
    "DNV GL", "RISE (Sweden)", "VTT (Finland)", "SP Technical Research",
]

LCA_METHODOLOGIES = [
    "ISO 14040/14044", "PEF (Product Environmental Footprint)",
    "EPD (Environmental Product Declaration)", "GHG Protocol Product Standard",
]

DISPOSAL_METHODS = [
    "Municipal recycling", "Specialized recycling center",
    "Composting (industrial)", "Return to manufacturer",
    "Hazardous waste collection", "Textile collection point",
    "Electronics recycling (WEEE)",
]

RECYCLING_CODES = {
    "Wood": "51 FOR", "Steel": "40 FE", "Aluminium": "41 ALU",
    "Plastic": "5 PP", "Glass": "70 GL", "Textile": "60 TEX",
    "Foam": "7 OTHER", "Paper": "20 PAP",
}

PRODUCTION_FACILITIES = [
    "NordicForm Almhult Factory",
    "NordicForm Jonkoping Plant",
    "NordicForm Gdansk Workshop",
    "NordicForm Kaunas Assembly",
    "NordicForm Tallinn Textiles",
]

SECOND_LIFE_OPTIONS = [
    "furniture reuse program", "textile recycling", "material recovery",
    "upcycling workshops", "charity donation", "component harvesting",
    "refurbishment service", "spare parts marketplace",
]

# Furniture domain knobs that were previously inline in the generator methods.
FURNITURE_COMPONENT_NAMES: dict[str, list[str]] = {
    "Furniture": ["Frame", "Tabletop", "Legs", "Hardware", "Finish", "Upholstery"],
    "Textiles": ["Outer Fabric", "Inner Lining", "Filling", "Thread", "Dye"],
    "Lighting": ["Body", "Shade", "Wiring", "LED Module", "Base"],
    "Storage": ["Shell", "Handle", "Base", "Liner"],
}
FURNITURE_DURABILITY_RANGES: dict[str, tuple[int, int]] = {
    "Furniture": (5, 25), "Textiles": (2, 10), "Lighting": (5, 15), "Storage": (3, 15),
}
FURNITURE_DISPOSAL_COMPONENTS: dict[str, list[tuple]] = {
    "Furniture": [
        ("Wood Frame", "Municipal recycling", "51 FOR", 8.0, 45.0),
        ("Metal Hardware", "Specialized recycling center", "40 FE", 0.5, 3.0),
        ("Foam Padding", "Specialized recycling center", "7 OTHER", 1.0, 5.0),
        ("Finish/Coating", "Hazardous waste collection", None, 0.1, 0.5),
    ],
    "Textiles": [
        ("Fabric", "Textile collection point", "60 TEX", 0.3, 5.0),
        ("Filling", "Municipal recycling", "7 OTHER", 0.2, 2.0),
        ("Packaging", "Municipal recycling", "20 PAP", 0.1, 0.3),
    ],
    "Lighting": [
        ("Metal Body", "Specialized recycling center", "40 FE", 0.5, 3.0),
        ("Glass/Shade", "Municipal recycling", "70 GL", 0.2, 1.5),
        ("Electronics", "Electronics recycling (WEEE)", None, 0.05, 0.3),
        ("Wiring", "Electronics recycling (WEEE)", "41 ALU", 0.02, 0.1),
    ],
    "Storage": [
        ("Plastic Shell", "Municipal recycling", "5 PP", 0.3, 3.0),
        ("Metal Frame", "Specialized recycling center", "40 FE", 0.2, 2.0),
        ("Natural Fiber", "Composting (industrial)", None, 0.1, 1.5),
    ],
}

# ---------------------------------------------------------------------------
# Battery profile (EU Batteries Regulation 2023/1542) -- fictional "VoltCore"
# ---------------------------------------------------------------------------
BATTERY_CATALOG: dict[str, list[dict[str, Any]]] = {
    "EV Battery": [
        {"prefix": "VOLT", "type": "EV Pack"},
        {"prefix": "NMCE", "type": "NMC Module"},
        {"prefix": "LFPX", "type": "LFP Pack"},
        {"prefix": "NCAE", "type": "NCA Module"},
    ],
    "Industrial Battery": [
        {"prefix": "ESSR", "type": "ESS Rack"},
        {"prefix": "GRID", "type": "Grid Module"},
        {"prefix": "UPSX", "type": "UPS Battery"},
    ],
    "LMT Battery": [
        {"prefix": "EBIK", "type": "E-Bike Pack"},
        {"prefix": "ESCO", "type": "E-Scooter Pack"},
    ],
    "Portable Battery": [
        {"prefix": "PWRX", "type": "Power Tool Pack"},
        {"prefix": "CY70", "type": "21700 Cell"},
        {"prefix": "POUC", "type": "Pouch Cell"},
    ],
}
BATTERY_STYLE_MODIFIERS = [
    "48V", "400V", "800V", "LFP", "NMC811", "NCA", "Long-Range",
    "Fast-Charge", "High-Density", "Gen2", "Gen3", "Standard",
]
BATTERY_CERTIFICATIONS = [
    "CE", "UN 38.3", "IEC 62133", "IEC 62619", "UL 2580", "ISO 14001",
    "OECD Due Diligence", "EU Battery Passport",
]
_LIION_MATERIALS = [
    {"name": "Lithium Carbonate", "category": "Active Material", "cas": "554-13-2", "renewable": False, "hazardous": False},
    {"name": "Cobalt Oxide", "category": "Active Material", "cas": "1307-96-6", "renewable": False, "hazardous": True},
    {"name": "Nickel Sulfate", "category": "Active Material", "cas": "7786-81-4", "renewable": False, "hazardous": True},
    {"name": "Manganese Oxide", "category": "Active Material", "cas": "1313-13-9", "renewable": False, "hazardous": False},
    {"name": "Graphite Anode", "category": "Active Material", "cas": "7782-42-5", "renewable": False, "hazardous": False},
    {"name": "Lithium Iron Phosphate", "category": "Active Material", "cas": "15365-14-7", "renewable": False, "hazardous": False},
    {"name": "Electrolyte (LiPF6)", "category": "Electrolyte", "cas": "21324-40-3", "renewable": False, "hazardous": True},
    {"name": "Copper Foil", "category": "Current Collector", "cas": "7440-50-8", "renewable": False, "hazardous": False},
    {"name": "Aluminium Foil", "category": "Current Collector", "cas": "7429-90-5", "renewable": False, "hazardous": False},
    {"name": "Polymer Separator", "category": "Separator", "cas": None, "renewable": False, "hazardous": False},
    {"name": "Steel Casing", "category": "Metal", "cas": "7439-89-6", "renewable": False, "hazardous": False},
]
BATTERY_MATERIAL_DB = {cat: _LIION_MATERIALS for cat in BATTERY_CATALOG}
BATTERY_CARBON_RANGES: dict[str, tuple[float, float]] = {
    "EV Battery": (2000.0, 8000.0),
    "Industrial Battery": (500.0, 3500.0),
    "LMT Battery": (40.0, 300.0),
    "Portable Battery": (3.0, 60.0),
}
BATTERY_LIFECYCLE_SPLITS: dict[str, dict[str, tuple[float, float]]] = {
    "EV Battery": {"manufacturing": (0.55, 0.70), "transport": (0.05, 0.10), "use_phase": (0.18, 0.32), "end_of_life": (0.04, 0.10)},
    "Industrial Battery": {"manufacturing": (0.50, 0.65), "transport": (0.05, 0.10), "use_phase": (0.22, 0.35), "end_of_life": (0.04, 0.10)},
    "LMT Battery": {"manufacturing": (0.55, 0.70), "transport": (0.06, 0.12), "use_phase": (0.12, 0.25), "end_of_life": (0.05, 0.12)},
    "Portable Battery": {"manufacturing": (0.60, 0.75), "transport": (0.06, 0.12), "use_phase": (0.08, 0.18), "end_of_life": (0.05, 0.12)},
}
# In-force at the 18 Feb 2027 battery-passport launch (get a normal weighted
# status). Carbon footprint / recycled content / due diligence are NOT here --
# they are phased in later (see BATTERY_PHASED_REGULATIONS) so they are never
# randomly marked "compliant".
BATTERY_REGULATIONS = [
    {"name": "EU Batteries Regulation", "version": "2023/1542"},
    {"name": "ESPR - Ecodesign for Sustainable Products", "version": "2024/1781"},
    {"name": "UN 38.3 Transport of Dangerous Goods", "version": "Rev.7"},
    {"name": "EU REACH Regulation", "version": "EC 1907/2006"},
    {"name": "EU RoHS Directive", "version": "2011/65/EU"},
]
# Requirements that exist in Reg. 2023/1542 but do NOT apply at the Feb-2027
# launch -- always emitted as `pending` with a note citing the applicability
# date. Confirmed by the DG GROW battery-DPP webinar (27 May 2026): the battery
# passport is mandatory 18 Feb 2027 but carbon footprint (Art.7), recycled
# content (Art.8) and supply-chain due diligence (Art.48) phase in afterwards.
BATTERY_PHASED_REGULATIONS = [
    {"name": "Battery Carbon Footprint Declaration", "version": "2023/1542 Art.7",
     "note": "Not required at the 18 Feb 2027 launch; carbon footprint declaration applies from a later date set by delegated act (Art.7)."},
    {"name": "Recycled Content Share", "version": "2023/1542 Art.8",
     "note": "Not required at launch; minimum recycled-content documentation applies from a later date (Art.8)."},
    {"name": "Supply Chain Due Diligence", "version": "2023/1542 Art.48",
     "note": "Due diligence report required at the latest by 18 Aug 2028 (Art.48)."},
]
# Multi-tier chain, keyed by supplier tier, so origins read mine -> cell ->
# module -> pack as you walk from the deepest tier up to the manufacturer.
BATTERY_TIER_COMPONENTS = {
    3: ["Lithium (raw material)", "Cobalt (raw material)", "Natural graphite (raw material)",
        "Nickel (raw material)", "Manganese ore"],
    2: ["Cathode active material", "Anode active material", "Electrolyte", "Separator", "Battery cell"],
    1: ["Battery module", "Cell-to-pack assembly", "Battery management system (BMS)",
        "Busbar / interconnect", "Pack housing"],
}
# State of health (dynamic data, Reg. Art.10/14) is only meaningful for
# rechargeable batteries with a BMS -- not portable/primary cells.
BATTERY_RECHARGEABLE_CATEGORIES = {"EV Battery", "Industrial Battery", "LMT Battery"}
BATTERY_COMPONENT_NAMES = {
    cat: ["Cathode", "Anode", "Electrolyte", "Separator", "Cell Casing", "BMS", "Module Housing", "Busbar"]
    for cat in BATTERY_CATALOG
}
BATTERY_DURABILITY_RANGES: dict[str, tuple[int, int]] = {
    "EV Battery": (8, 15), "Industrial Battery": (10, 20),
    "LMT Battery": (3, 8), "Portable Battery": (2, 6),
}
BATTERY_DISPOSAL_COMPONENTS: dict[str, list[tuple]] = {
    "EV Battery": [
        ("Battery Cells", "Hazardous waste collection", "16 06 01", 80.0, 400.0),
        ("BMS Electronics", "Electronics recycling (WEEE)", None, 1.0, 5.0),
        ("Pack Housing", "Specialized recycling center", "41 ALU", 10.0, 60.0),
        ("Cooling System", "Specialized recycling center", "40 FE", 5.0, 30.0),
    ],
    "Industrial Battery": [
        ("Battery Modules", "Hazardous waste collection", "16 06 01", 30.0, 200.0),
        ("Rack Frame", "Specialized recycling center", "40 FE", 10.0, 80.0),
        ("Power Electronics", "Electronics recycling (WEEE)", None, 2.0, 10.0),
    ],
    "LMT Battery": [
        ("Cell Pack", "Hazardous waste collection", "16 06 01", 1.0, 8.0),
        ("BMS Board", "Electronics recycling (WEEE)", None, 0.05, 0.3),
        ("Casing", "Municipal recycling", "5 PP", 0.2, 1.0),
    ],
    "Portable Battery": [
        ("Cells", "Hazardous waste collection", "16 06 01", 0.05, 2.0),
        ("Casing", "Municipal recycling", "5 PP", 0.02, 0.3),
    ],
}

# ---------------------------------------------------------------------------
# Industry profiles -- select with --profile / DPP_PROFILE. The schema, pipeline,
# apps and dashboard are domain-agnostic; only this synthetic data differs.
# ---------------------------------------------------------------------------
PROFILES: dict[str, dict[str, Any]] = {
    "furniture": {
        "manufacturer": {
            "name": "NordicForm AB", "country": "SWE",
            "registration_number": "SE556012-3456", "website": "https://www.nordicform.se",
        },
        "sku_prefix": "NF",
        "product_catalog": PRODUCT_CATALOG,
        "style_modifiers": STYLE_MODIFIERS,
        "certifications": CERTIFICATIONS,
        "material_db": MATERIAL_DB,
        "carbon_ranges": CARBON_RANGES,
        "lifecycle_splits": LIFECYCLE_SPLITS,
        "regulations": REGULATIONS,
        "production_facilities": PRODUCTION_FACILITIES,
        "second_life_options": SECOND_LIFE_OPTIONS,
        "component_names": FURNITURE_COMPONENT_NAMES,
        "durability_ranges": FURNITURE_DURABILITY_RANGES,
        "disposal_components": FURNITURE_DISPOSAL_COMPONENTS,
        "origin_countries": ["SWE", "POL", "LTU"],
        "lca_data_source": "NordicForm LCA Database v3.1",
        "qr_base_url": "https://dpp.nordicform.se/passport/",
        "doc_base_url": "https://certs.nordicform.se/",
    },
    "battery": {
        "manufacturer": {
            "name": "VoltCore Energy AB", "country": "SWE",
            "registration_number": "SE556987-6543", "website": "https://www.voltcore.se",
        },
        "sku_prefix": "VC",
        "product_catalog": BATTERY_CATALOG,
        "style_modifiers": BATTERY_STYLE_MODIFIERS,
        "certifications": BATTERY_CERTIFICATIONS,
        "material_db": BATTERY_MATERIAL_DB,
        "carbon_ranges": BATTERY_CARBON_RANGES,
        "lifecycle_splits": BATTERY_LIFECYCLE_SPLITS,
        "regulations": BATTERY_REGULATIONS,
        "production_facilities": [
            "VoltCore Gigafactory Skelleftea", "VoltCore Cell Plant Gdansk",
            "VoltCore Module Assembly Kaunas", "VoltCore Pack Line Hamburg",
            "VoltCore Recycling Norrkoping",
        ],
        "second_life_options": [
            "grid storage repurposing", "second-life ESS", "cell harvesting",
            "material recovery (hydrometallurgy)", "refurbishment service", "cascaded reuse",
        ],
        "component_names": BATTERY_COMPONENT_NAMES,
        "durability_ranges": BATTERY_DURABILITY_RANGES,
        "disposal_components": BATTERY_DISPOSAL_COMPONENTS,
        "origin_countries": ["SWE", "DEU", "POL"],
        "lca_data_source": "VoltCore Battery LCA Database v2.0",
        "qr_base_url": "https://dpp.voltcore.se/passport/",
        "doc_base_url": "https://certs.voltcore.se/",
        # Battery-realism knobs (absent for furniture, so it is unaffected).
        "phased_regulations": BATTERY_PHASED_REGULATIONS,
        "tier_components": BATTERY_TIER_COMPONENTS,
        "has_dynamic_data": True,
        "rechargeable_categories": BATTERY_RECHARGEABLE_CATEGORIES,
    },
}

DEFAULT_PROFILE = os.environ.get("DPP_PROFILE", "battery")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    """Generate a deterministic UUID from the seeded random module."""
    return str(uuid.UUID(int=random.getrandbits(128), version=4))


def _decimal(val: float, places: int = 3) -> float:
    """Round a float for JSON-friendly output."""
    return round(val, places)


def _date_str(d: date) -> str:
    return d.isoformat()


def _ts_str(dt: datetime) -> str:
    return dt.isoformat()


class _JSONEncoder(json.JSONEncoder):
    """Custom encoder for date/datetime/Decimal."""

    def default(self, o: Any) -> Any:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class DPPDataGenerator:
    """Generates a complete set of synthetic DPP data."""

    def __init__(self, seed: int = SEED, profile: str | None = None) -> None:
        profile = profile or DEFAULT_PROFILE
        if profile not in PROFILES:
            raise ValueError(
                f"Unknown profile {profile!r}. Choose from {sorted(PROFILES)}."
            )
        self.profile_name = profile
        self.p = PROFILES[profile]

        random.seed(seed)
        self.fake = Faker(["sv_SE", "en_US"])
        Faker.seed(seed)

        self.manufacturer: dict[str, Any] = {}
        self.suppliers: list[dict[str, Any]] = []
        self.passports: list[dict[str, Any]] = []
        self.origins: list[dict[str, Any]] = []
        self.materials: list[dict[str, Any]] = []
        self.impacts: list[dict[str, Any]] = []
        self.compliance: list[dict[str, Any]] = []
        self.circularity: list[dict[str, Any]] = []
        self.disposal: list[dict[str, Any]] = []
        self.audit_log: list[dict[str, Any]] = []

        self._supplier_map: dict[str, dict[str, Any]] = {}

    # -- Public API ---------------------------------------------------------

    def generate_all(self) -> None:
        """Generate all data tables in dependency order."""
        self._generate_manufacturer()
        self._generate_suppliers()
        self._generate_passports()

    def save(self, output_dir: Path | None = None) -> None:
        """Write each table to a JSON file."""
        out = output_dir or OUTPUT_DIR
        out.mkdir(parents=True, exist_ok=True)

        tables = {
            "manufacturer": [self.manufacturer],
            "supplier": self.suppliers,
            "product_passport": self.passports,
            "product_origin": self.origins,
            "product_materials": self.materials,
            "environmental_impact": self.impacts,
            "compliance_records": self.compliance,
            "circularity_info": self.circularity,
            "disposal_guidelines": self.disposal,
            "passport_audit_log": self.audit_log,
        }

        for name, records in tables.items():
            path = out / f"{name}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, cls=_JSONEncoder, ensure_ascii=False)
            print(f"  Wrote {len(records):>5} records -> {path.name}")

    # -- Private generators -------------------------------------------------

    def _generate_manufacturer(self) -> None:
        m = self.p["manufacturer"]
        self.manufacturer = {
            "manufacturer_id": _uuid(),
            "name": m["name"],
            "country": m["country"],
            "registration_number": m["registration_number"],
            "website": m["website"],
            "created_at": _ts_str(datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc)),
            "updated_at": _ts_str(datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc)),
        }

    def _generate_suppliers(self) -> None:
        """Generate a multi-tier supplier graph.

        Suppliers are created tier by tier so that parent links can be
        assigned: a tier-2 supplier's parent is a random tier-1 supplier, a
        tier-3 supplier's parent is a random tier-2 supplier. Tier-1 (direct)
        suppliers have no parent. This models real supply-chain depth and
        powers tier-1 -> tier-N traceability downstream.
        """
        today = REFERENCE_DATE

        # Decide each supplier's tier up front (~40/35/25 split), then build
        # tier 1, then 2, then 3 so parents always exist when children are made.
        tiers = random.choices(
            [1, 2, 3], weights=[0.4, 0.35, 0.25], k=NUM_SUPPLIERS
        )
        # Guarantee at least one supplier in every tier (deterministic for seed=42,
        # but keeps the hierarchy well-formed for any seed/count).
        for t in (1, 2, 3):
            if t not in tiers:
                tiers[t - 1] = t

        by_tier: dict[int, list[str]] = {1: [], 2: [], 3: []}

        certifications = self.p["certifications"]
        for tier in sorted(tiers):  # build tier 1 first, then 2, then 3
            num_certs = random.randint(1, 4)
            certs = random.sample(certifications, min(num_certs, len(certifications)))

            # ~15% of suppliers have audit dates expiring within 30 days
            if random.random() < 0.15:
                audit_date = today + timedelta(days=random.randint(1, 30))
            else:
                audit_date = today - timedelta(days=random.randint(30, 365))

            # Parent is a supplier one tier closer to the manufacturer.
            parent_id = None
            if tier > 1 and by_tier[tier - 1]:
                parent_id = random.choice(by_tier[tier - 1])

            supplier = {
                "supplier_id": _uuid(),
                "name": self.fake.company(),
                "country": random.choice(SUPPLIER_COUNTRIES),
                "tier": tier,
                "parent_supplier_id": parent_id,
                "risk_score": _decimal(random.uniform(1.0, 9.5), 1),
                "certifications": certs,
                "last_audit_date": _date_str(audit_date),
                "active": random.random() > 0.05,
                "created_at": _ts_str(datetime(2024, 1, 15, tzinfo=timezone.utc)),
                "updated_at": _ts_str(datetime(2024, 6, 1, tzinfo=timezone.utc)),
            }
            self.suppliers.append(supplier)
            self._supplier_map[supplier["supplier_id"]] = supplier
            by_tier[tier].append(supplier["supplier_id"])

    def _generate_passports(self) -> None:
        """Generate ~500 product passports with all child records."""
        today = REFERENCE_DATE
        category_items = []
        for cat, items in self.p["product_catalog"].items():
            for item in items:
                category_items.append((cat, item))

        # Pre-generate all unique product names to avoid duplicates
        used_names: set[str] = set()
        # Per-prefix sequence so product_id is GUARANTEED unique. A random
        # variant collides (birthday paradox) and violates the uq_product_id
        # constraint at seed time, so the SKU number must be monotonic.
        prefix_seq: dict[str, int] = {}

        for i in range(NUM_PRODUCTS):
            cat, item = random.choice(category_items)
            variant = random.randint(1, 99)
            style = random.choice(self.p["style_modifiers"])
            base_name = f"{item['prefix']} {item['type']} {style}".upper()

            # If name already used, append variant number to make it unique
            product_name = base_name
            if product_name in used_names:
                product_name = f"{base_name} {variant:02d}"
            # Still a collision (very unlikely)? Add counter
            counter = 2
            while product_name in used_names:
                product_name = f"{base_name} {variant:02d}-{counter}"
                counter += 1
            used_names.add(product_name)

            passport_id = _uuid()
            seq = prefix_seq.get(item["prefix"], 0) + 1
            prefix_seq[item["prefix"]] = seq
            product_id = f"{self.p['sku_prefix']}-{item['prefix']}-{seq:03d}"
            gtin = f"{random.randint(10000000000000, 99999999999999)}"[:14]
            serial = f"SN{self.fake.bothify('########')}"
            batch = f"LOT-{random.randint(2024, 2026)}-{random.randint(1, 52):02d}"

            # 90% complete passports, 10% incomplete (missing some optional fields)
            is_complete = random.random() < 0.90

            production_date = today - timedelta(days=random.randint(1, 730))
            created_at = datetime.combine(
                production_date - timedelta(days=random.randint(1, 30)),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )

            passport = {
                "passport_id": passport_id,
                "product_id": product_id,
                "gtin": gtin,
                "serial_number": serial if is_complete else None,
                "batch_lot_number": batch,
                "product_name": product_name,
                "product_category": cat,
                "manufacturer_id": self.manufacturer["manufacturer_id"],
                "production_date": _date_str(production_date),
                "production_facility": random.choice(self.p["production_facilities"])
                    if is_complete else None,
                "country_of_origin": random.choice(self.p["origin_countries"])
                    if is_complete else None,
                "passport_status": random.choices(
                    ["active", "draft", "expired", "revoked"],
                    weights=[0.78, 0.13, 0.05, 0.02],
                )[0],
                "qr_code_url": f"{self.p['qr_base_url']}{passport_id}"
                    if is_complete else None,
                "created_at": _ts_str(created_at),
                "updated_at": _ts_str(created_at + timedelta(days=random.randint(0, 60))),
            }
            self.passports.append(passport)

            # Generate child records
            self._generate_origins(passport_id, cat, is_complete)
            self._generate_materials(passport_id, cat)
            self._generate_impact(passport_id, cat, is_complete)
            self._generate_compliance(passport_id, is_complete)
            self._generate_circularity(passport_id, cat, is_complete)
            self._generate_disposal(passport_id, cat)

    def _generate_origins(
        self, passport_id: str, category: str, is_complete: bool
    ) -> None:
        num_origins = random.randint(1, 5)
        used_suppliers: set[str] = set()

        for _ in range(num_origins):
            supplier = random.choice(self.suppliers)
            if supplier["supplier_id"] in used_suppliers:
                continue
            used_suppliers.add(supplier["supplier_id"])

            # Some certifications expiring within 30 days for alert testing
            cert = random.choice(self.p["certifications"])
            if random.random() < 0.12:
                cert_expiry = REFERENCE_DATE + timedelta(days=random.randint(1, 30))
            else:
                cert_expiry = REFERENCE_DATE + timedelta(days=random.randint(90, 730))

            # Tier-correlated components (battery) tell a mine -> cell -> module
            # -> pack story; otherwise fall back to the flat per-category list.
            tier_components = self.p.get("tier_components")
            if tier_components:
                choices = tier_components.get(supplier["tier"]) \
                    or self.p["component_names"].get(category, ["Component"])
            else:
                choices = self.p["component_names"].get(category, ["Component"])

            origin = {
                "origin_id": _uuid(),
                "passport_id": passport_id,
                "supplier_id": supplier["supplier_id"],
                "supply_chain_tier": supplier["tier"],
                "component_name": random.choice(choices),
                "source_country": supplier["country"],
                "source_region": self.fake.city() if is_complete else None,
                "certification": cert,
                "certification_expiry": _date_str(cert_expiry),
                "traceability_proof": f"TRACE-{self.fake.bothify('????-####')}"
                    if is_complete else None,
            }
            self.origins.append(origin)

    def _generate_materials(self, passport_id: str, category: str) -> None:
        """Generate 2-8 materials whose percentages sum to ~100%."""
        material_db = self.p["material_db"]
        available = material_db.get(category) or next(iter(material_db.values()))
        num_materials = random.randint(2, min(8, len(available)))
        chosen = random.sample(available, num_materials)

        # Generate weights that sum to 100
        raw_weights = [random.uniform(1, 10) for _ in range(num_materials)]
        total = sum(raw_weights)
        percentages = [round(w / total * 100, 2) for w in raw_weights]
        # Fix rounding to exactly 100
        diff = round(100.0 - sum(percentages), 2)
        percentages[0] = round(percentages[0] + diff, 2)

        for mat, pct in zip(chosen, percentages):
            recycled_pct = (
                round(random.uniform(0, 80), 2)
                if random.random() < 0.3
                else 0.0
            )
            material = {
                "material_id": _uuid(),
                "passport_id": passport_id,
                "material_name": mat["name"],
                "material_category": mat["category"],
                "percentage_by_weight": pct,
                "recycled_content_pct": recycled_pct,
                "renewable_flag": mat["renewable"],
                "hazardous_flag": mat["hazardous"],
                "cas_number": mat["cas"],
                "reach_compliant": True,
                "svhc_flag": False,
            }
            self.materials.append(material)

    def _generate_impact(
        self, passport_id: str, category: str, is_complete: bool
    ) -> None:
        lo, hi = self.p["carbon_ranges"][category]
        total_carbon = round(random.uniform(lo, hi), 3)

        # Category-specific lifecycle phase splits
        splits = self.p["lifecycle_splits"][category]
        mfg_pct = random.uniform(*splits["manufacturing"])
        transport_pct = random.uniform(*splits["transport"])
        use_pct = random.uniform(*splits["use_phase"])
        eol_pct = random.uniform(*splits["end_of_life"])
        # Normalize to sum to 1.0
        total_pct = mfg_pct + transport_pct + use_pct + eol_pct
        mfg_pct /= total_pct
        transport_pct /= total_pct
        use_pct /= total_pct
        eol_pct /= total_pct

        impact = {
            "impact_id": _uuid(),
            "passport_id": passport_id,
            "carbon_footprint_kg": total_carbon,
            "carbon_manufacturing": _decimal(total_carbon * mfg_pct),
            "carbon_transport": _decimal(total_carbon * transport_pct),
            "carbon_use_phase": _decimal(total_carbon * use_pct),
            "carbon_end_of_life": _decimal(total_carbon * eol_pct),
            "energy_consumption_kwh": _decimal(random.uniform(5, 500)),
            "water_usage_liters": _decimal(random.uniform(10, 2000)),
            "lca_methodology": random.choice(LCA_METHODOLOGIES) if is_complete else None,
            "lca_data_source": self.p["lca_data_source"] if is_complete else None,
            "assessment_date": _date_str(
                REFERENCE_DATE - timedelta(days=random.randint(30, 365))
            ),
            "verified_by": random.choice(ISSUING_BODIES) if is_complete else None,
        }
        self.impacts.append(impact)

    def _generate_compliance(self, passport_id: str, is_complete: bool) -> None:
        """Generate 1-3 compliance records per product.

        Distribution: ~85% compliant, ~10% pending, ~5% non_compliant.
        """
        regulations = self.p["regulations"]
        num_records = random.randint(1, 3)
        chosen_regs = random.sample(regulations, min(num_records, len(regulations)))

        for reg in chosen_regs:
            # Weighted compliance status
            roll = random.random()
            if roll < 0.85:
                status = "compliant"
            elif roll < 0.95:
                status = "pending"
            else:
                status = "non_compliant"

            issue_date = REFERENCE_DATE - timedelta(days=random.randint(30, 730))
            expiry_date = issue_date + timedelta(days=random.randint(365, 1095))

            record = {
                "compliance_id": _uuid(),
                "passport_id": passport_id,
                "regulation_name": reg["name"],
                "regulation_version": reg["version"],
                "compliance_status": status,
                "certificate_ref": f"CERT-{self.fake.bothify('????-####')}"
                    if status == "compliant" else None,
                "issuing_body": random.choice(ISSUING_BODIES)
                    if is_complete else None,
                "issue_date": _date_str(issue_date),
                "expiry_date": _date_str(expiry_date),
                "document_url": f"{self.p['doc_base_url']}{self.fake.bothify('########')}.pdf"
                    if status == "compliant" else None,
                "notes": "Pending lab results" if status == "pending" else None,
            }
            self.compliance.append(record)

        # Phased-in requirements (e.g. battery carbon footprint / recycled
        # content / due diligence) are always present but not yet applicable at
        # launch -- emitted as `pending` with a note citing the applicability
        # date. Empty for profiles that don't define them (furniture).
        for reg in self.p.get("phased_regulations", []):
            self.compliance.append({
                "compliance_id": _uuid(),
                "passport_id": passport_id,
                "regulation_name": reg["name"],
                "regulation_version": reg["version"],
                "compliance_status": "pending",
                "certificate_ref": None,
                "issuing_body": None,
                "issue_date": None,
                "expiry_date": None,
                "document_url": None,
                "notes": reg["note"],
            })

    def _generate_circularity(
        self, passport_id: str, category: str, is_complete: bool
    ) -> None:
        lo, hi = self.p["durability_ranges"][category]

        second_life = self.p["second_life_options"]
        num_options = random.randint(1, min(4, len(second_life)))
        options = random.sample(second_life, num_options)

        # State of health = dynamic data (Reg. Art.10/14). Only meaningful for
        # rechargeable batteries with a BMS; NULL for everything else, so the
        # viewer shows a "Battery Health" panel only where it applies.
        has_dynamic = self.p.get("has_dynamic_data") and category in self.p.get(
            "rechargeable_categories", set()
        )
        if has_dynamic:
            soh = _decimal(random.uniform(72.0, 100.0), 1)
            cycles = random.randint(50, 3000)
            soh_updated = _ts_str(datetime.combine(
                REFERENCE_DATE - timedelta(days=random.randint(0, 7)),
                datetime.min.time(), tzinfo=timezone.utc,
            ))
        else:
            soh = cycles = soh_updated = None

        circularity = {
            "circularity_id": _uuid(),
            "passport_id": passport_id,
            "durability_years": random.randint(lo, hi),
            "repairability_score": _decimal(random.uniform(2.0, 9.5), 1),
            "spare_parts_available": random.random() > 0.3,
            "spare_parts_years": random.randint(5, 15) if is_complete else None,
            "refurbishable": random.random() > 0.4,
            "recycled_content_pct": _decimal(random.uniform(0, 60), 2),
            "recyclability_pct": _decimal(random.uniform(40, 98), 2),
            "take_back_program": random.random() > 0.5,
            "second_life_options": options,
            "state_of_health_pct": soh,
            "cycle_count": cycles,
            "dynamic_data_updated_at": soh_updated,
        }
        self.circularity.append(circularity)

    def _generate_disposal(self, passport_id: str, category: str) -> None:
        """Generate disposal guidelines for 1-4 components."""
        component_map = self.p["disposal_components"]
        components = component_map.get(category) or next(iter(component_map.values()))
        num = random.randint(1, min(4, len(components)))
        chosen = random.sample(components, num)

        for comp_name, method, code, wt_lo, wt_hi in chosen:
            disposal = {
                "disposal_id": _uuid(),
                "passport_id": passport_id,
                "component_name": comp_name,
                "disposal_method": method,
                "disassembly_steps": f"1. Remove {comp_name.lower()} using standard tools. "
                    f"2. Separate from other components. "
                    f"3. Clean if necessary before disposal.",
                "recycling_code": code,
                "local_collection_info": "Check local municipality recycling guidelines.",
                "special_handling": "Wear protective gloves during disassembly."
                    if "Hazardous" in method or "Electronics" in method else None,
                "weight_kg": _decimal(random.uniform(wt_lo, wt_hi)),
            }
            self.disposal.append(disposal)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Generate all synthetic data and save to JSON files."""
    import argparse

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--profile", default=DEFAULT_PROFILE, choices=sorted(PROFILES))
    args, _ = ap.parse_known_args()

    print("=" * 60)
    print("DPP Synthetic Data Generator")
    print(f"Profile: {args.profile} | Seed: {SEED} | "
          f"Products: {NUM_PRODUCTS} | Suppliers: {NUM_SUPPLIERS}")
    print("=" * 60)

    gen = DPPDataGenerator(seed=SEED, profile=args.profile)
    gen.generate_all()
    gen.save()

    print()
    print("Summary:")
    print(f"  Manufacturer:       1")
    print(f"  Suppliers:          {len(gen.suppliers)}")
    print(f"  Product Passports:  {len(gen.passports)}")
    print(f"  Origin Records:     {len(gen.origins)}")
    print(f"  Material Records:   {len(gen.materials)}")
    print(f"  Impact Records:     {len(gen.impacts)}")
    print(f"  Compliance Records: {len(gen.compliance)}")
    print(f"  Circularity:        {len(gen.circularity)}")
    print(f"  Disposal:           {len(gen.disposal)}")
    print()
    print("Done. Files saved to src/foundation/data/")


if __name__ == "__main__":
    main()
