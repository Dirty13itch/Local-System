#!/usr/bin/env python3
"""Build the master performers database by merging multiple source files.

Runs on DESK (Windows) where all xlsx/csv source files live at
C:\\Users\\Shaun\\Desktop\\Triage\\

Merge order:
  1. Performer Data.xlsx (backbone — 803 performers)
  2. Master TOSI.xlsx (body measurements, favorites)
  3. Empire/Ultimate_Bimbo_Performer_Database_Complete.xlsx (bimbo scoring)
  4. Empire/Master_Sheet_FINAL_POLISHED.xlsx (36-column enrichment)
  5. SOVEREIGN_DUMP CSVs (style match scoring)
  6. Compute gen_suitability (0-100 composite)
  7. Mark tiers (S/A/B)
  8. Output performers.json → VAULT NFS

Usage:
    python scripts/build_performers_db.py
    python scripts/build_performers_db.py --dry-run
    python scripts/build_performers_db.py --output ./performers.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl required. Install: pip install openpyxl")
    sys.exit(1)


# ─── Config ──────────────────────────────────────────────────────────────

TRIAGE_DIR = Path(os.environ.get(
    "TRIAGE_DIR",
    r"C:\Users\Shaun\Desktop\Triage"
))

# Output paths
DEFAULT_OUTPUT = Path(r"\\192.168.1.203\data\performers.json")  # VAULT UNC
FALLBACK_OUTPUT = Path("performers.json")  # local fallback

# S-Tier performers (user-specified priority)
S_TIER = {
    "peta jensen", "nicolette shea", "alanah rae",
    "trina michaels", "madison ivy",
}


# ─── Helpers ─────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize a performer name for matching."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip().lower())


def slugify(name: str) -> str:
    """Create a URL-safe slug from a name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return default


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return default


def safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def read_xlsx_rows(path: Path, sheet_name: str | None = None) -> list[dict]:
    """Read an xlsx file into a list of dicts (header row → keys)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    headers = [safe_str(h).strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        d = {}
        for i, h in enumerate(headers):
            if h and i < len(row):
                d[h] = row[i]
        if any(v for v in d.values()):
            result.append(d)
    return result


def read_xlsx_from_zip(zip_path: Path, inner_path: str,
                       sheet_name: str | None = None) -> list[dict]:
    """Read an xlsx file from inside a ZIP archive."""
    import tempfile
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(inner_path) as f:
            tmp = Path(tempfile.mktemp(suffix=".xlsx"))
            tmp.write_bytes(f.read())
    try:
        return read_xlsx_rows(tmp, sheet_name)
    finally:
        tmp.unlink(missing_ok=True)


def read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV into list of dicts."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def body_type_matches_slim(body_type: str) -> bool:
    """Check if body type description matches slim/skinny aesthetic."""
    if not body_type:
        return False
    lower = body_type.lower()
    slim_terms = [
        "slim", "petite", "skinny", "lean", "tight", "tits on a stick",
        "implant doll", "implant model", "bust forward", "bust-dominant",
        "top-heavy", "petite glam", "glam bimbo", "classic porn star",
        "thin", "slender",
    ]
    return any(t in lower for t in slim_terms)


def body_type_matches_athletic(body_type: str) -> bool:
    """Check if body type is athletic/toned."""
    if not body_type:
        return False
    lower = body_type.lower()
    return any(t in lower for t in ["athletic", "toned", "fit", "muscular"])


# ─── Step 1: Backbone from Performer Data.xlsx ───────────────────────────

def load_backbone(triage: Path) -> dict[str, dict]:
    """Load Performer Data.xlsx as the backbone."""
    path = triage / "Performer Data.xlsx"
    if not path.exists():
        print(f"  WARNING: {path} not found, skipping backbone")
        return {}

    rows = read_xlsx_rows(path, "Performers Master")
    print(f"  Step 1: Loaded {len(rows)} performers from Performer Data.xlsx")

    performers: dict[str, dict] = {}
    for r in rows:
        name = safe_str(r.get("Name") or r.get("name", ""))
        if not name:
            continue

        key = normalize_name(name)
        performers[key] = {
            "name": name,
            "aliases": safe_str(r.get("Aliases", "")),
            "rating": safe_float(r.get("Rating", 0)),
            "height": safe_str(r.get("Height", "")),
            "weight": safe_str(r.get("Weight", "")),
            "bust": safe_str(r.get("Bra Size") or r.get("Bust", "")),
            "body_type": safe_str(r.get("Body Type", "")),
            "implants": safe_str(r.get("Implants", "")).lower() in ("yes", "true", "1", "enhanced"),
            "ethnicity": safe_str(r.get("Ethnicity", "")),
            "nationality": safe_str(r.get("Nationality", "")),
            "career_start": safe_str(r.get("Career Start", "")),
            "career_end": safe_str(r.get("Career End", "")),
            "career_peak": safe_str(r.get("Career Peak", "")),
            "total_scenes": safe_int(r.get("Total Scenes", 0)),
            "studios": safe_str(r.get("Studios") or r.get("Studio List", "")),
            "tag_list": safe_str(r.get("Tag List", "")),
            "rare_media": safe_str(r.get("Rare Media", "")),
            "scene_search_hint": safe_str(r.get("Scene Search Hint", "")),
            # Will be filled by later steps
            "waist": "",
            "hip": "",
            "bust_waist_hip": "",
            "bust_to_frame": "",
            "implant_status": "",
            "years_active": None,
            "gen_suitability": 0,
            "tier": "",
            "bimbo_score": 0,
            "bimbo_match_pct": 0,
            "bimbo_subtype": "",
            "viewing_priority": "",
            "style_match": 0,
            "content_areas": "",
            "signature_attributes": "",
            "content_specialization": "",
            "is_favorite": False,
            "is_subject": False,
            "reference_count": 0,
        }

    return performers


# ─── Step 2: Body measurements from Master TOSI ─────────────────────────

def merge_tosi(performers: dict[str, dict], triage: Path) -> None:
    """Merge body measurements and favorites from Master TOSI.xlsx."""
    path = triage / "Master TOSI.xlsx"
    if not path.exists():
        print(f"  Step 2: SKIP — {path} not found")
        return

    rows = read_xlsx_rows(path)
    matched = 0

    for r in rows:
        name = safe_str(r.get("Name") or r.get("Performer", ""))
        if not name:
            continue

        key = normalize_name(name)
        if key not in performers:
            # Try fuzzy match — sometimes names differ slightly
            continue

        p = performers[key]
        # Body measurements (only fill if empty)
        if not p["waist"]:
            p["waist"] = safe_str(r.get("Waist", ""))
        if not p["hip"]:
            p["hip"] = safe_str(r.get("Hip", ""))
        if not p["bust_waist_hip"]:
            p["bust_waist_hip"] = safe_str(r.get("Bust-Waist-Hip") or r.get("BWH", ""))
        if not p["bust_to_frame"]:
            p["bust_to_frame"] = safe_str(r.get("Bust-to-Frame Description") or
                                          r.get("Bust to Frame", ""))

        # Years active
        ya = r.get("Years Active")
        if ya and not p["years_active"]:
            p["years_active"] = safe_int(ya)

        # Favorite markers (★ or similar)
        fav_raw = safe_str(r.get("Favorite") or r.get("Fav", ""))
        if fav_raw and fav_raw.strip() in ("★", "⭐", "1", "Yes", "TRUE", "True", "yes"):
            p["is_favorite"] = True

        matched += 1

    print(f"  Step 2: Merged TOSI data for {matched} performers")


# ─── Step 3: Bimbo scoring from Ultimate Bimbo DB ───────────────────────

def merge_bimbo_db(performers: dict[str, dict], triage: Path) -> None:
    """Merge bimbo scoring from Empire ZIP."""
    zip_path = triage / "Empire"
    # Look for the ZIP or extracted xlsx
    xlsx_direct = zip_path / "Ultimate_Bimbo_Performer_Database_Complete.xlsx"
    zip_file = None

    # Check for direct file first, then ZIP
    if xlsx_direct.exists():
        rows = read_xlsx_rows(xlsx_direct)
    else:
        # Look for any zip in Empire/
        zips = list(zip_path.glob("*.zip")) if zip_path.exists() else []
        if not zips:
            print(f"  Step 3: SKIP — No Empire ZIP/xlsx found")
            return
        zip_file = zips[0]
        try:
            with zipfile.ZipFile(zip_file, "r") as zf:
                xlsx_names = [n for n in zf.namelist() if "Ultimate_Bimbo" in n and n.endswith(".xlsx")]
                if not xlsx_names:
                    print(f"  Step 3: SKIP — No Ultimate_Bimbo xlsx in ZIP")
                    return
                rows = read_xlsx_from_zip(zip_file, xlsx_names[0])
        except Exception as e:
            print(f"  Step 3: SKIP — Error reading ZIP: {e}")
            return

    matched = 0
    for r in rows:
        name = safe_str(r.get("Name") or r.get("Performer", ""))
        if not name:
            continue

        key = normalize_name(name)
        if key not in performers:
            continue

        p = performers[key]
        p["bimbo_score"] = safe_int(r.get("Score") or r.get("Bimbo Score", 0))
        p["bimbo_match_pct"] = safe_int(r.get("bimbo_match_percentage") or
                                        r.get("Match %", 0))
        p["bimbo_subtype"] = safe_str(r.get("Subtype") or r.get("bimbo_subtype", ""))
        p["viewing_priority"] = safe_str(r.get("viewing_priority") or
                                         r.get("Viewing Priority", ""))
        p["content_areas"] = safe_str(r.get("Content Areas") or
                                      r.get("content_areas", ""))

        # "Shaun's Type" description
        shauns_type = safe_str(r.get("Shaun's Type") or r.get("shauns_type", ""))
        if shauns_type and not p["signature_attributes"]:
            p["signature_attributes"] = shauns_type

        matched += 1

    print(f"  Step 3: Merged bimbo scoring for {matched} performers")


# ─── Step 4: Enrichment from Master_Sheet_FINAL_POLISHED ────────────────

def merge_master_sheet(performers: dict[str, dict], triage: Path) -> None:
    """Fill gaps from the 36-column Master Sheet."""
    zip_path = triage / "Empire"
    xlsx_direct = zip_path / "Master_Sheet_FINAL_POLISHED.xlsx"

    if xlsx_direct.exists():
        rows = read_xlsx_rows(xlsx_direct)
    else:
        zips = list(zip_path.glob("*.zip")) if zip_path.exists() else []
        if not zips:
            print(f"  Step 4: SKIP — No Master_Sheet xlsx/ZIP found")
            return
        try:
            with zipfile.ZipFile(zips[0], "r") as zf:
                xlsx_names = [n for n in zf.namelist() if "Master_Sheet" in n and n.endswith(".xlsx")]
                if not xlsx_names:
                    print(f"  Step 4: SKIP — No Master_Sheet in ZIP")
                    return
                rows = read_xlsx_from_zip(zips[0], xlsx_names[0])
        except Exception as e:
            print(f"  Step 4: SKIP — Error: {e}")
            return

    matched = 0
    for r in rows:
        name = safe_str(r.get("Name") or r.get("Performer", ""))
        if not name:
            continue

        key = normalize_name(name)
        if key not in performers:
            continue

        p = performers[key]

        # Fill gaps only — don't overwrite existing data
        if not p.get("implant_status"):
            p["implant_status"] = safe_str(r.get("Implant Status", ""))
        if not p.get("bust") and r.get("Bust Size"):
            p["bust"] = safe_str(r.get("Bust Size", ""))
        if not p.get("height") and r.get("Height"):
            p["height"] = safe_str(r.get("Height", ""))

        # Implant detection from this source
        impl_raw = safe_str(r.get("Implant Status") or r.get("Implants", "")).lower()
        if not p["implants"] and impl_raw in ("yes", "enhanced", "high profile", "moderate profile"):
            p["implants"] = True

        matched += 1

    print(f"  Step 4: Enriched {matched} performers from Master Sheet")


# ─── Step 5: SOVEREIGN_DUMP CSVs ────────────────────────────────────────

def merge_sovereign_dump(performers: dict[str, dict], triage: Path) -> None:
    """Merge style match data from SOVEREIGN_DUMP CSVs."""
    dump_dir = triage / "SOVEREIGN_DUMP"
    if not dump_dir.exists():
        print(f"  Step 5: SKIP — {dump_dir} not found")
        return

    # Tits_On_Stick_Performers.csv
    tos_path = dump_dir / "Tits_On_Stick_Performers.csv"
    matched = 0
    if tos_path.exists():
        rows = read_csv_rows(tos_path)
        for r in rows:
            name = safe_str(r.get("Name") or r.get("name", ""))
            if not name:
                continue
            key = normalize_name(name)
            if key not in performers:
                continue
            p = performers[key]
            p["style_match"] = safe_int(r.get("style_match", 0))
            if not p["signature_attributes"]:
                p["signature_attributes"] = safe_str(r.get("signature_attributes", ""))
            if not p["content_specialization"]:
                p["content_specialization"] = safe_str(r.get("content_specialization", ""))
            if r.get("match_description"):
                p["bimbo_subtype"] = p["bimbo_subtype"] or safe_str(r.get("bimbo_subtype", ""))
            matched += 1
        print(f"  Step 5a: Merged {matched} from Tits_On_Stick CSV")

    # Top_100_Bimbo_Performers.csv
    top100_path = dump_dir / "Top_100_Bimbo_Performers.csv"
    if top100_path.exists():
        rows = read_csv_rows(top100_path)
        matched2 = 0
        for r in rows:
            name = safe_str(r.get("Name") or r.get("name", ""))
            if not name:
                continue
            key = normalize_name(name)
            if key not in performers:
                continue
            p = performers[key]
            # Only fill if not already set
            if not p["style_match"]:
                p["style_match"] = safe_int(r.get("style_match", 0))
            if not p["signature_attributes"]:
                p["signature_attributes"] = safe_str(r.get("signature_attributes", ""))
            matched2 += 1
        print(f"  Step 5b: Merged {matched2} from Top_100_Bimbo CSV")
    else:
        print(f"  Step 5b: SKIP — Top_100_Bimbo CSV not found")


# ─── Step 6: Compute gen_suitability ─────────────────────────────────────

def compute_gen_suitability(performers: dict[str, dict]) -> None:
    """Compute the 0-100 generation suitability score."""
    for p in performers.values():
        # Use pre-computed bimbo_match_percentage if available
        bimbo_pct = p.get("bimbo_match_pct", 0)
        if bimbo_pct and bimbo_pct > 0:
            p["gen_suitability"] = min(100, bimbo_pct)
        else:
            score = 0
            if p.get("implants"):
                score += 30
            body = p.get("body_type", "")
            if body_type_matches_slim(body):
                score += 20
            elif body_type_matches_athletic(body):
                score += 8
            sm = p.get("style_match", 0)
            if sm:
                score += int(15 * min(sm / 17, 1.0))
            if p.get("is_favorite"):
                score += 15
            bs = p.get("bimbo_score", 0)
            if bs:
                score += int(bs * 2.0)
            p["gen_suitability"] = min(100, score)

    print(f"  Step 6: Computed gen_suitability for {len(performers)} performers")


# ─── Step 7: Mark tiers ──────────────────────────────────────────────────

def mark_tiers(performers: dict[str, dict]) -> dict[str, int]:
    """Assign S/A/B tiers based on data."""
    counts = {"S": 0, "A": 0, "B": 0, "": 0}

    for key, p in performers.items():
        # S-Tier: user-specified
        if normalize_name(p["name"]) in S_TIER:
            p["tier"] = "S"
            p["is_favorite"] = True  # S-Tier are always favorites
            counts["S"] += 1
            continue

        # A-Tier: data-driven from multiple sources
        is_a = False
        if p.get("is_favorite"):
            is_a = True
        if p.get("viewing_priority", "").lower() in ("top priority",):
            is_a = True
        if p.get("bimbo_match_pct", 0) >= 70:
            is_a = True
        if p.get("style_match", 0) >= 14:
            is_a = True

        if is_a:
            p["tier"] = "A"
            counts["A"] += 1
            continue

        # B-Tier: good generation candidates
        is_b = False
        vp = p.get("viewing_priority", "").lower()
        if vp in ("high priority",):
            is_b = True
        if p.get("gen_suitability", 0) >= 60 and p.get("implants"):
            is_b = True

        if is_b:
            p["tier"] = "B"
            counts["B"] += 1
        else:
            p["tier"] = ""
            counts[""] += 1

    print(f"  Step 7: Tiers — S={counts['S']}, A={counts['A']}, B={counts['B']}, "
          f"untiered={counts['']}")
    return counts


# ─── Step 8: Output ──────────────────────────────────────────────────────

def output_json(performers: dict[str, dict], output_path: Path) -> None:
    """Write the final performers.json."""
    # Convert to sorted list
    result = sorted(performers.values(), key=lambda p: p.get("gen_suitability", 0), reverse=True)

    # Clean up None values
    for p in result:
        for k, v in list(p.items()):
            if v is None:
                p[k] = 0 if k in ("years_active", "total_scenes", "gen_suitability",
                                   "bimbo_score", "bimbo_match_pct", "style_match") else ""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Output: {len(result)} performers → {output_path}")


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build master performers database")
    parser.add_argument("--triage-dir", type=Path, default=TRIAGE_DIR,
                        help="Directory containing source files")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output path for performers.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write output, just show stats")
    args = parser.parse_args()

    triage = args.triage_dir
    print(f"Building performers database from: {triage}")
    print(f"{'=' * 60}")

    if not triage.exists():
        print(f"ERROR: Triage directory not found: {triage}")
        sys.exit(1)

    # Step 1: Backbone
    performers = load_backbone(triage)
    if not performers:
        print("ERROR: No performers loaded from backbone. Check Performer Data.xlsx")
        sys.exit(1)

    # Step 2: TOSI body measurements
    merge_tosi(performers, triage)

    # Step 3: Bimbo scoring
    merge_bimbo_db(performers, triage)

    # Step 4: Master Sheet enrichment
    merge_master_sheet(performers, triage)

    # Step 5: SOVEREIGN_DUMP
    merge_sovereign_dump(performers, triage)

    # Step 6: Compute gen_suitability
    compute_gen_suitability(performers)

    # Step 7: Mark tiers
    tier_counts = mark_tiers(performers)

    # Stats
    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"  Total performers: {len(performers)}")
    print(f"  With implants: {sum(1 for p in performers.values() if p.get('implants'))}")
    print(f"  Favorites: {sum(1 for p in performers.values() if p.get('is_favorite'))}")
    print(f"  Gen suitability ≥ 60: {sum(1 for p in performers.values() if p.get('gen_suitability', 0) >= 60)}")
    print(f"  Gen suitability ≥ 80: {sum(1 for p in performers.values() if p.get('gen_suitability', 0) >= 80)}")

    # S-Tier check
    s_tier_found = [p["name"] for p in performers.values() if p.get("tier") == "S"]
    print(f"\n  S-Tier performers ({len(s_tier_found)}):")
    for name in sorted(s_tier_found):
        p = performers[normalize_name(name)]
        print(f"    - {name}: gen_suit={p['gen_suitability']}, "
              f"implants={p['implants']}, bust={p.get('bust', '?')}")

    if args.dry_run:
        print("\n  DRY RUN — no output written")
        return

    # Step 8: Output
    output = args.output
    if not output:
        try:
            output = DEFAULT_OUTPUT
            # Test if UNC path is accessible
            output.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            print(f"  WARNING: Cannot write to VAULT UNC path, using local fallback")
            output = FALLBACK_OUTPUT

    output_json(performers, output)
    print(f"\nDone! Run the gateway service to load the new database.")


if __name__ == "__main__":
    main()
