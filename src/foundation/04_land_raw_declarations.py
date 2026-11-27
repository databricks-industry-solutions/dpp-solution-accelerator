"""
Digital Product Passport -- land RAW supplier material declarations

Suppliers do not type everything into a portal. Most passport evidence arrives
as files: material declarations exported from the supplier's own systems. This
module writes those files, as raw JSON lines, into a Unity Catalog volume. The
ingestion pipeline picks them up with Auto Loader (see
src/pipelines/bronze/ingest_raw_supplier_declarations.py).

The files are deliberately imperfect (about 4% of the lines): a missing
supplier id, a recycled share above 100, an unreadable date. The Silver layer
has to reject those, which is the point of the raw step.

All data is synthetic and derived from the same seeded generator as the rest
of the accelerator, so the supplier ids match the suppliers seeded in Lakebase.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta

VOLUME_NAME = "raw_landing"
SUBFOLDER = "supplier_declarations"
DIRTY_SHARE = 0.04


def build_declarations(suppliers: list[dict], materials: list[dict], reference_date: date, seed: int) -> list[dict]:
    """One declaration per (supplier, material) the supplier delivers.

    Uses its own Random instance so the main generator's sequence is untouched.
    """
    rng = random.Random(seed + 1)
    material_names = sorted({m["material_name"] for m in materials})
    declarations: list[dict] = []
    for sup in suppliers:
        for material in rng.sample(material_names, k=min(len(material_names), rng.randint(2, 5))):
            declared = reference_date - timedelta(days=rng.randint(5, 400))
            valid_until = declared + timedelta(days=rng.choice([365, 730]))
            slug = "".join(ch for ch in sup["name"].lower() if ch.isalnum())[:18] or "supplier"
            rec = {
                "declaration_id": f"DECL-{rng.getrandbits(40):010x}",
                "supplier_id": sup["supplier_id"],
                "supplier_name": sup["name"],
                "material_name": material,
                "recycled_content_pct": round(rng.uniform(0, 65), 1),
                "carbon_kg_co2e_per_kg": round(rng.uniform(0.8, 28.0), 2),
                "country_of_origin": sup["country"],
                "certificate_number": f"CERT-{rng.randint(100000, 999999)}",
                "certificate_valid_until": valid_until.isoformat(),
                "declared_at": declared.isoformat(),
                "submitted_by": f"compliance@{slug}.example",
            }
            roll = rng.random()
            if roll < DIRTY_SHARE / 3:
                rec["supplier_id"] = None
            elif roll < 2 * DIRTY_SHARE / 3:
                rec["recycled_content_pct"] = round(rng.uniform(101, 180), 1)
            elif roll < DIRTY_SHARE:
                rec["declared_at"] = "not-a-date"
            declarations.append(rec)
    return declarations


def land(spark, catalog: str, schema: str, declarations: list[dict], files: int = 5) -> str:
    """Create the volume if needed and write the declarations as JSON-lines files.

    Returns the landing folder. Existing files with the same names are replaced,
    so a re-run of the setup job does not duplicate deliveries.
    """
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")
    spark.sql(
        f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`{VOLUME_NAME}` "
        "COMMENT 'RAW landing zone: supplier material declarations as delivered (synthetic)'"
    )
    folder = f"/Volumes/{catalog}/{schema}/{VOLUME_NAME}/{SUBFOLDER}"
    import os

    os.makedirs(folder, exist_ok=True)
    chunk = max(1, -(-len(declarations) // files))
    for i in range(files):
        part = declarations[i * chunk:(i + 1) * chunk]
        if not part:
            continue
        path = f"{folder}/declarations_batch_{i + 1:02d}.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for rec in part:
                fh.write(json.dumps(rec) + "\n")
        print(f"  Wrote {len(part):>4} raw declarations to {path}")
    return folder
