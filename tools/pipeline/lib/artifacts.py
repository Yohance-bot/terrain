"""Every file the pipeline reads or writes, declared once.

Stages import these constants rather than spelling out paths. That way the
handoff between two stages is a shared object, not two string literals that
have to agree -- and a typo becomes an import error instead of an empty result
three stages later.

Filenames carry their producing stage number so that a half-finished run is
readable on disk without consulting this file.
"""

from __future__ import annotations

from lib.contracts import ArtifactFormat, ArtifactSpec

# --- Stage 01: raw source extracts ------------------------------------------

RAW_MANIFEST = ArtifactSpec(
    key="raw_manifest",
    relative_path="raw/download_manifest.json",
    format=ArtifactFormat.JSON,
    description=(
        "One entry per downloaded source file: url, local filename, byte size, "
        "sha256, and the pinned Overture release. This is the audit record that "
        "makes a pipeline run reproducible, so it is the artifact later stages "
        "depend on rather than the extracts themselves."
    ),
)

# --- Stage 02: separator features -------------------------------------------

SEPARATORS = ArtifactSpec(
    key="separators",
    relative_path="intermediate/02_separators.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Linework that is permitted to become a territory border: included road "
        "classes, rail, linear water, and the outer rings of area boundaries. "
        "Clipped to the AOI bbox. Excluded classes from highway_classes.yaml are "
        "already gone by this point."
    ),
)

# --- Stage 03: landmarks (majors protected, minors for naming) --------------

LANDMARKS = ArtifactSpec(
    key="landmarks",
    relative_path="intermediate/03_landmarks.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Named places extracted from source data, each with `role: major|minor`. "
        "Only majors carry `protected: true` and are carved in stage 05 / frozen "
        "in stage 06. Minors keep name and geometry for naming hints only."
    ),
)

# --- Stage 04: boundary graph -----------------------------------------------

BOUNDARY_GRAPH = ArtifactSpec(
    key="boundary_graph",
    relative_path="intermediate/04_boundary_graph.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Separators noded at every intersection and snapped within snap_m, in "
        "the working CRS. This is the input polygonization needs: a planar, "
        "fully-noded line set where every crossing is a shared vertex."
    ),
)

# --- Stage 05: candidate faces ----------------------------------------------

FACES = ArtifactSpec(
    key="faces",
    relative_path="intermediate/05_faces.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "The first exhaustive partition of the AOI. Every face is a closed "
        "polygon bounded by separators, with protected major landmarks carved "
        "out and reinserted whole. Minors are not carved. No gaps, no overlaps."
    ),
)

# --- Stage 06: size-normalised faces ----------------------------------------

NORMALIZED = ArtifactSpec(
    key="normalized",
    relative_path="intermediate/06_normalized.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Faces after size normalisation: scraps merged into their "
        "longest-shared-border fabric neighbour; oversized anonymous fabric "
        "flagged needs_review (not split). Protected majors pass through "
        "untouched."
    ),
)

# --- Stage 07: named territories --------------------------------------------

NAMED = ArtifactSpec(
    key="named",
    relative_path="intermediate/07_named.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Territories with `name`, `slug`, `kind`, a stable `territory_id`, and "
        "`needs_review` set wherever naming fell through to a fallback or "
        "failed entirely."
    ),
)

# --- Stage 08: staged candidates for human review ---------------------------

CANDIDATES = ArtifactSpec(
    key="candidates",
    relative_path="staging/candidates.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "What a human opens in QGIS or geojson.io to review. Storage CRS, "
        "final properties, publish-ready geometry."
    ),
)

VALIDATION_REPORT = ArtifactSpec(
    key="validation_report",
    relative_path="staging/validation_report.json",
    format=ArtifactFormat.JSON,
    description=(
        "Machine-readable verdict: coverage ratio, gap and overlap totals, size "
        "distribution, unnamed count, and the list of territories flagged for "
        "review. Stage 08 fails closed -- a topology violation means no "
        "candidates file is written at all."
    ),
)

# --- The human gate ---------------------------------------------------------

APPROVED = ArtifactSpec(
    key="approved",
    relative_path="staging/APPROVED",
    format=ArtifactFormat.MARKER,
    description=(
        "Created by a human, never by the pipeline. Its presence is the "
        "statement 'I have looked at candidates.geojson against satellite "
        "imagery and these are real places.' `03` requires human sign-off "
        "before any territory becomes live game data."
    ),
)

# --- Stage 09: publish record (parcel / reality layer) ----------------------

PUBLISHED_TERRITORIES = ArtifactSpec(
    key="published_territories",
    relative_path="published/territories.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Immutable parcel / reality territories: exact copy of staging "
        "candidates after human APPROVED. Stage 10 consumes this; the phone "
        "eventually consumes gameplay publish instead."
    ),
)

PUBLISH_MANIFEST = ArtifactSpec(
    key="publish_manifest",
    relative_path="published/publish_manifest.json",
    format=ArtifactFormat.JSON,
    description=(
        "What was published, when, from which source checksums, and which "
        "territories changed shape and therefore had their version bumped. The "
        "record that lets a bad publish be traced and rolled back."
    ),
)

# --- Stage 10: gameplay clustering ------------------------------------------

GAMEPLAY_CANDIDATES = ArtifactSpec(
    key="gameplay_candidates",
    relative_path="staging/gameplay_candidates.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Playable territories after barrier-aware agglomerative clustering of "
        "Stage 09 parcels. Protected landmarks pass through unchanged. Stage 11 "
        "beautifies these before human GAMEPLAY_APPROVED."
    ),
)

GAMEPLAY_CLUSTER_REPORT = ArtifactSpec(
    key="gameplay_cluster_report",
    relative_path="staging/gameplay_cluster_report.json",
    format=ArtifactFormat.JSON,
    description=(
        "Merge audit for Stage 10: input/output counts, size distribution, "
        "barrier-blocked edges, merge counts, soft review flags, and input "
        "fingerprint hashes."
    ),
)

GAMEPLAY_VALIDATION_REPORT = ArtifactSpec(
    key="gameplay_validation_report",
    relative_path="staging/gameplay_validation_report.json",
    format=ArtifactFormat.JSON,
    description=(
        "Hard/soft validation of gameplay candidates (gap, overlap, coverage, "
        "unique ids, protected freeze). Fail-closed: no candidates on hard fail."
    ),
)

# --- Stage 11: beautification critic + GIS apply ----------------------------

GAMEPLAY_METRICS = ArtifactSpec(
    key="gameplay_metrics",
    relative_path="staging/gameplay_metrics.json",
    format=ArtifactFormat.JSON,
    description=(
        "Per-territory design metrics for Stage 11: area, perimeter, "
        "compactness, convexity, boundary complexity, neighbours."
    ),
)

BEAUTIFY_SUGGESTIONS = ArtifactSpec(
    key="beautify_suggestions",
    relative_path="staging/beautify_suggestions.json",
    format=ArtifactFormat.JSON,
    description=(
        "Critic output: restricted toolbox suggestions (merge, absorb_peninsula, "
        "reject_merge, …) with reasons and confidence scores."
    ),
)

BEAUTIFY_APPLY_REPORT = ArtifactSpec(
    key="beautify_apply_report",
    relative_path="staging/beautify_apply_report.json",
    format=ArtifactFormat.JSON,
    description=(
        "Which Stage 11 suggestions were auto-applied, skipped, or refused "
        "by GIS topology / barrier / protected guards."
    ),
)

GAMEPLAY_BEAUTIFIED = ArtifactSpec(
    key="gameplay_beautified",
    relative_path="staging/gameplay_beautified.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Gameplay territories after Stage 11 critic auto-apply. Stage 12 human "
        "review and Stage 13 publish consume this artifact."
    ),
)

GAMEPLAY_BEAUTIFY_VALIDATION_REPORT = ArtifactSpec(
    key="gameplay_beautify_validation_report",
    relative_path="staging/gameplay_beautify_validation_report.json",
    format=ArtifactFormat.JSON,
    description=(
        "Hard/soft validation of gameplay_beautified (same gates as Stage 10)."
    ),
)

# --- Stage 12: gameplay human gate ------------------------------------------

GAMEPLAY_APPROVED = ArtifactSpec(
    key="gameplay_approved",
    relative_path="staging/GAMEPLAY_APPROVED",
    format=ArtifactFormat.MARKER,
    description=(
        "Created by a human after reviewing gameplay_beautified.geojson. "
        "Independent of parcel APPROVED so reality and playability can be "
        "signed off separately."
    ),
)

GAMEPLAY_REVIEW = ArtifactSpec(
    key="gameplay_review",
    relative_path="staging/gameplay_review.json",
    format=ArtifactFormat.JSON,
    description=(
        "Stage 12 ack that beautified gameplay was approved for publish. "
        "Written only when GAMEPLAY_APPROVED exists."
    ),
)

# --- Stage 13: gameplay publish ---------------------------------------------

PUBLISHED_GAMEPLAY_TERRITORIES = ArtifactSpec(
    key="published_gameplay_territories",
    relative_path="published/gameplay_territories.geojson",
    format=ArtifactFormat.GEOJSON,
    description=(
        "Final playable territory layer for the phone / seed script. Exact "
        "copy of staging gameplay_beautified after GAMEPLAY_APPROVED."
    ),
)

GAMEPLAY_PUBLISH_MANIFEST = ArtifactSpec(
    key="gameplay_publish_manifest",
    relative_path="published/gameplay_publish_manifest.json",
    format=ArtifactFormat.JSON,
    description=(
        "Publish record for the gameplay layer: counts, hashes, and the "
        "parcel publish hash Stage 10 clustered from."
    ),
)


ALL_ARTIFACTS: tuple[ArtifactSpec, ...] = (
    RAW_MANIFEST,
    SEPARATORS,
    LANDMARKS,
    BOUNDARY_GRAPH,
    FACES,
    NORMALIZED,
    NAMED,
    CANDIDATES,
    VALIDATION_REPORT,
    APPROVED,
    PUBLISHED_TERRITORIES,
    PUBLISH_MANIFEST,
    GAMEPLAY_CANDIDATES,
    GAMEPLAY_CLUSTER_REPORT,
    GAMEPLAY_VALIDATION_REPORT,
    GAMEPLAY_METRICS,
    BEAUTIFY_SUGGESTIONS,
    BEAUTIFY_APPLY_REPORT,
    GAMEPLAY_BEAUTIFIED,
    GAMEPLAY_BEAUTIFY_VALIDATION_REPORT,
    GAMEPLAY_APPROVED,
    GAMEPLAY_REVIEW,
    PUBLISHED_GAMEPLAY_TERRITORIES,
    GAMEPLAY_PUBLISH_MANIFEST,
)
