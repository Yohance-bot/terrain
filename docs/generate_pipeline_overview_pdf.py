#!/usr/bin/env python3
"""Generate docs/Territory_Mapping_Pipeline_Overview.pdf"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "Territory_Mapping_Pipeline_Overview.pdf"


def _load_stats() -> dict:
    stats = {
        "territory_count": "—",
        "protected_count": "—",
        "fabric_median_m2": "—",
        "validation_status": "—",
    }
    pub = (
        ROOT
        / "data"
        / "pipeline"
        / "bengaluru"
        / "jayanagar_lalbagh"
        / "published"
        / "publish_manifest.json"
    )
    terr = pub.parent / "territories.geojson"
    if pub.exists():
        m = json.loads(pub.read_text())
        stats["territory_count"] = str(m.get("territory_count", "—"))
        stats["protected_count"] = str(m.get("protected_count", "—"))
        stats["validation_status"] = m.get("validation_status", "—")
    if terr.exists():
        d = json.loads(terr.read_text())
        areas = [
            float((f.get("properties") or {}).get("area_m2") or 0)
            for f in d.get("features") or []
            if not (f.get("properties") or {}).get("protected")
        ]
        if areas:
            areas.sort()
            stats["fabric_median_m2"] = f"{areas[len(areas) // 2]:,.0f}"
    return stats


def build_pdf() -> Path:
    stats = _load_stats()
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Territory Mapping Pipeline Overview",
        author="run project",
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "DocTitle",
        parent=styles["Title"],
        fontSize=22,
        spaceAfter=12,
        alignment=TA_CENTER,
    )
    subtitle = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#444444"),
        alignment=TA_CENTER,
        spaceAfter=24,
    )
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, spaceBefore=14, spaceAfter=8)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6)
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=14, bulletIndent=0)

    story: list = []

    # Title page
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("Territory Mapping Pipeline", title))
    story.append(Paragraph("What is built, how it works, and how it reaches the app", subtitle))
    story.append(Paragraph(f"Generated {date.today().isoformat()}", subtitle))
    story.append(Spacer(1, 1 * cm))
    story.append(
        Paragraph(
            "Region: <b>bengaluru_jayanagar_lalbagh</b> (Jayanagar → Lalbagh corridor, Bengaluru)",
            body,
        )
    )
    story.append(PageBreak())

    # 1. Why
    story.append(Paragraph("1. Why this pipeline exists", h1))
    story.append(
        Paragraph(
            "The game is played on <b>real places</b> — parks, lakes, named neighbourhood blocks — "
            "not arbitrary grids. Milestone 1 proved the run loop with ~8 hand-drawn territories. "
            "Milestone 2 replaces hand-drawing with a <b>deterministic, human-reviewed</b> build pipeline "
            "that turns OpenStreetMap and Overture data into exhaustive territory polygons for an area of interest (AOI).",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Core product rule:</b> the map is not the product; the feeling of changing the map is. "
            "Territories must read as places a local would recognise.",
            body,
        )
    )

    # 2. Architecture
    story.append(Paragraph("2. End-to-end architecture", h1))
    flow_data = [
        ["Layer", "Component", "Role"],
        ["Sources", "Overture Maps + Geofabrik OSM", "Pinned downloads; checksums in manifest"],
        ["Build", "tools/pipeline/ (stages 01–09)", "Offline GIS; never runs on the phone"],
        ["Review", "staging/candidates.geojson", "Human opens in QGIS/geojson.io; APPROVED file"],
        ["Publish", "published/territories.geojson", "Immutable audit artifact + manifest"],
        ["Serve", "FastAPI + PostGIS", "GET /v1/territories for the mobile app"],
        ["Client", "Expo + MapLibre", "Renders polygons; server matches runs"],
    ]
    t = Table(flow_data, colWidths=[2.2 * cm, 5.5 * cm, 9.3 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8fa")]),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph("Pipeline flow (build time):", h2))
    story.append(
        Paragraph(
            "01 download → 02 separators + 03 landmarks → 04 boundary graph → "
            "05 polygonize &amp; carve → 06 normalize sizes → 07 assign names → "
            "08 validate (fail closed) → [human APPROVED] → 09 publish",
            body,
        )
    )

    # 3. Stages
    story.append(PageBreak())
    story.append(Paragraph("3. Pipeline stages (01–09)", h1))
    stages = [
        ["01", "download_data", "Overture + Geofabrik extracts, SHA-256, manifest"],
        ["02", "extract_features", "Road/rail separators from highway_classes.yaml"],
        ["03", "extract_landmarks", "Named places; role major|minor; only majors protected"],
        ["04", "build_boundary_graph", "Snap, node, drop dangles; working CRS (UTM 43N)"],
        ["05", "polygonize_and_carve", "Faces inside AOI; carve protected majors whole"],
        ["06", "normalize_sizes", "Merge scraps; freeze protected; safe geometry"],
        ["07", "assign_names", "Place → landmark → street-pair → review; stable territory_id"],
        ["08", "validate", "Hard topology gate; candidates only on pass"],
        ["09", "publish", "Copy candidates to published/; gated on APPROVED"],
    ]
    st = Table([["#", "Stage", "Summary"]] + stages, colWidths=[1 * cm, 4.2 * cm, 11.8 * cm])
    st.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(st)

    story.append(Spacer(1, 10))
    story.append(Paragraph("Key invariants", h2))
    for line in [
        "Every point in the AOI belongs to exactly one territory (no gaps, no overlaps).",
        "All measurement in metres (UTM 43N); storage in EPSG:4326.",
        "Protected landmarks (e.g. Lalbagh) are never merged, split, or resized.",
        "territory_id = uuid5(city/area/slug) — permanent; geometry changes bump version only.",
        "Stage 08 fails closed: invalid topology → report only, no candidates file.",
        "No AI naming; names come from OSM/Overture or deterministic fallbacks.",
    ]:
        story.append(Paragraph(f"• {line}", bullet))

    # 4. Artifacts
    story.append(Paragraph("4. Where files live", h1))
    story.append(
        Paragraph(
            "All pipeline output under <b>data/pipeline/bengaluru/jayanagar_lalbagh/</b>:",
            body,
        )
    )
    artifacts = [
        ["raw/", "Download manifest + source extracts"],
        ["intermediate/", "02_separators … 07_named.geojson"],
        ["staging/", "candidates.geojson, validation_report.json, chain_fingerprint.json"],
        ["staging/APPROVED", "Human-created marker (not written by pipeline)"],
        ["published/", "territories.geojson, publish_manifest.json"],
    ]
    at = Table([["Path", "Contents"]] + artifacts, colWidths=[4.5 * cm, 12.5 * cm])
    at.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3460")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(at)

    # 5. Current build status
    story.append(PageBreak())
    story.append(Paragraph("5. What is built today", h1))
    story.append(Paragraph("<b>Pipeline:</b> All nine stages implemented and tested.", body))
    story.append(
        Paragraph(
            f"<b>Published AOI (jayanagar_lalbagh):</b> {stats['territory_count']} territories "
            f"({stats['protected_count']} protected landmarks), validation {stats['validation_status']}.",
            body,
        )
    )
    story.append(
        Paragraph(
            f"<b>Typical fabric median area:</b> ~{stats['fabric_median_m2']} m² "
            "(target soft band 20,000–80,000 m² for anonymous street fabric).",
            body,
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("Mobile + backend (Milestone 1 loop):", h2))
    for line in [
        "Expo app with MapLibre (custom dev client; not Expo Go).",
        "Foreground GPS recording; SQLite run durability.",
        "FastAPI backend: territories GeoJSON, ownership state, run upload + matching.",
        "Placeholder ownership rule: highest cumulative distance wins.",
        "Pipeline publish can be seeded into PostGIS via backend/scripts/seed_territories.py.",
    ]:
        story.append(Paragraph(f"• {line}", bullet))

    story.append(Spacer(1, 10))
    story.append(Paragraph("6. Sizing &amp; thresholds (config/thresholds.yaml)", h1))
    thresh = [
        ["scrap_m2", "5,000", "Below this: merge into neighbour (scrap)"],
        ["fabric_soft_min_m2", "20,000", "Target lower bound for anonymous fabric"],
        ["fabric_soft_max_m2", "80,000", "Target upper bound (~1–2 territories per run)"],
        ["territory_min_area_m2", "20,000", "Floor for protected major landmarks"],
        ["validation min_coverage", "0.999", "Stage 08 hard gate"],
    ]
    tt = Table([["Key", "Value", "Meaning"]] + thresh, colWidths=[4.5 * cm, 2.5 * cm, 10 * cm])
    tt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#533483")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(tt)
    story.append(
        Paragraph(
            "<b>Playtest note:</b> Current fabric is finer than the soft band (many small grid cells). "
            "Coarser merges or place-based dissolve are the likely next tuning pass — not random shapes.",
            body,
        )
    )

    # 7. How to run
    story.append(Paragraph("7. How to run the pipeline", h1))
    cmds = [
        "cd tools/pipeline && uv sync",
        "uv run python run_pipeline.py --list",
        "uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh",
        "uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh --from-stage 6 --to-stage 8",
        "# After human review:",
        "touch data/pipeline/bengaluru/jayanagar_lalbagh/staging/APPROVED",
        "uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh --from-stage 9",
        "# Seed mobile API:",
        "cd backend && uv run python scripts/seed_territories.py --source pipeline",
    ]
    for c in cmds:
        story.append(Paragraph(f"<font face='Courier' size='8'>{c}</font>", body))

    # 8. Not built / deferred
    story.append(Spacer(1, 10))
    story.append(Paragraph("8. Deferred (not in this milestone)", h1))
    for line in [
        "PostGIS upsert from Stage 09 (publish is file copy today; seed script bridges to API).",
        "data/territories/ versioned export layout for backend seed (partial bridge exists).",
        "H3 territory_cells indexing.",
        "Influence model, decay, clubs, anti-cheat detection.",
        "AI-assisted naming.",
        "Admin console; file-based APPROVED gate only.",
    ]:
        story.append(Paragraph(f"• {line}", bullet))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(
        Paragraph(
            "Canonical contract: docs/09_TERRITORY_GENERATION_PIPELINE.md · "
            "Operational detail: tools/pipeline/README.md",
            ParagraphStyle("Footer", parent=body, fontSize=8, textColor=colors.grey, alignment=TA_CENTER),
        )
    )

    doc.build(story)
    return OUT


if __name__ == "__main__":
    path = build_pdf()
    print(f"Wrote {path}")
