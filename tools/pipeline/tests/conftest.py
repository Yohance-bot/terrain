"""Shared fixtures.

Tests build a `PipelineContext` rooted at a temporary directory so that running
the suite never touches `data/pipeline/`. The configs are the real ones on
purpose -- a test that passes against a fake config proves nothing about the
config the pipeline actually loads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.config import load_feature_classes, load_region, load_thresholds
from lib.contracts import PipelineContext
from lib.download import DownloadedFile, write_checksum
from lib.registry import discover_stages

REGION_NAME = "bengaluru_jayanagar_lalbagh"


@pytest.fixture
def region():
    return load_region(REGION_NAME)


@pytest.fixture
def thresholds():
    return load_thresholds()


@pytest.fixture
def feature_classes():
    return load_feature_classes()


@pytest.fixture
def ctx(tmp_path: Path, region, thresholds, feature_classes) -> PipelineContext:
    context = PipelineContext(
        region=region,
        thresholds=thresholds,
        feature_classes=feature_classes,
        repo_root=tmp_path,
    )
    context.ensure_dirs()
    return context


@pytest.fixture
def stub_downloads(monkeypatch):
    """Keep the suite offline once stage 01 is a real network stage.

    Orchestrator tests still need stage 01 to write a real (non-placeholder)
    manifest so later stages can assert on REQUIRES. The bytes themselves are
    irrelevant -- stage 02 is what reads them.
    """

    def fake_overture(**kwargs) -> DownloadedFile:
        dest: Path = kwargs["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(b"FAKE-OVERTURE")
        digest = write_checksum(dest)
        return DownloadedFile(
            key=f"overture_{dest.stem}",
            source="overture",
            url="s3://fake",
            filename=dest.name,
            path=dest,
            sha256=digest,
            bytes=dest.stat().st_size,
            skipped=False,
            theme="base",
            feature_type="land",
            release=kwargs["release"],
        )

    def fake_http(**kwargs) -> DownloadedFile:
        dest: Path = kwargs["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(b"FAKE-GEOFABRIK")
        digest = write_checksum(dest)
        return DownloadedFile(
            key="geofabrik_extract",
            source="geofabrik",
            url=kwargs["url"],
            filename=dest.name,
            path=dest,
            sha256=digest,
            bytes=dest.stat().st_size,
            skipped=False,
        )

    monkeypatch.setattr("lib.download.download_overture_type", fake_overture)
    monkeypatch.setattr("lib.download.download_http_file", fake_http)
    return next(s for s in discover_stages() if s.number == 1)


@pytest.fixture
def stub_extract(monkeypatch):
    """Stage 02 without reading real parquet / osmium.

    Returns one deterministic residential line so the separators artifact is
    recognisably real (not a placeholder) without needing Geofabrik on disk.
    """

    def fake_extract(_ctx):
        return [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.57, 12.91], [77.58, 12.92]],
                },
                "properties": {
                    "source": "overture",
                    "group": "highway",
                    "class": "residential",
                    "id": "test-seg-1",
                },
            }
        ]

    monkeypatch.setattr("lib.extract.extract_separators", fake_extract)
    return fake_extract


@pytest.fixture
def stub_landmarks(monkeypatch):
    """Stage 03 without reading real parquet / osmium."""

    def fake_landmarks(_ctx):
        return [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [77.58, 12.94],
                                [77.59, 12.94],
                                [77.59, 12.95],
                                [77.58, 12.95],
                                [77.58, 12.94],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "protected": True,
                    "role": "major",
                    "name": "Lalbagh Botanical Garden",
                    "slug": "lalbagh-botanical-garden",
                    "kind": "park",
                    "category": "park",
                    "source": "overture",
                    "source_id": "test-lalbagh",
                    "area_m2": 900000.0,
                },
            }
        ]

    monkeypatch.setattr("lib.landmarks.extract_landmarks", fake_landmarks)
    return fake_landmarks


@pytest.fixture
def stub_graph(monkeypatch):
    """Stage 04 without reading real separators."""

    def fake_graph(_ctx):
        # Tiny cross in working CRS metres -- enough to prove the stage writes.
        return [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0.0, 0.0], [10.0, 0.0]],
                },
                "properties": {"edge_id": 1},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[5.0, -5.0], [5.0, 5.0]],
                },
                "properties": {"edge_id": 2},
            },
        ]

    monkeypatch.setattr("lib.graph.build_boundary_graph", fake_graph)
    return fake_graph


@pytest.fixture
def stub_faces(monkeypatch):
    """Stage 05 without real polygonization."""

    def fake_faces(_ctx):
        from lib.faces import FaceBuildStats

        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [77.58, 12.94],
                                [77.59, 12.94],
                                [77.59, 12.95],
                                [77.58, 12.95],
                                [77.58, 12.94],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "face_id": "face-00001",
                    "protected": True,
                    "role": "major",
                    "name": "Lalbagh Botanical Garden",
                    "slug": "lalbagh-botanical-garden",
                    "kind": "park",
                    "area_m2": 900000.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [77.57, 12.91],
                                [77.58, 12.91],
                                [77.58, 12.92],
                                [77.57, 12.92],
                                [77.57, 12.91],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "face_id": "face-00002",
                    "protected": False,
                    "role": None,
                    "kind": "fabric",
                    "area_m2": 50000.0,
                },
            },
        ]
        stats = FaceBuildStats(
            face_count=2,
            protected_count=1,
            fabric_count=1,
            area_min_m2=50000.0,
            area_max_m2=900000.0,
            area_mean_m2=475000.0,
            area_total_m2=950000.0,
            scrap_count=0,
            aoi_area_m2=1.0,
        )
        return features, stats

    monkeypatch.setattr("lib.faces.build_faces", fake_faces)
    return fake_faces


@pytest.fixture
def stub_normalize(monkeypatch):
    """Stage 06 without real scrap merging."""

    def fake_normalize(_ctx):
        from lib.normalize import NormalizeStats

        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [77.58, 12.94],
                                [77.59, 12.94],
                                [77.59, 12.95],
                                [77.58, 12.95],
                                [77.58, 12.94],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "face_id": "face-00001",
                    "protected": True,
                    "role": "major",
                    "name": "Lalbagh Botanical Garden",
                    "slug": "lalbagh-botanical-garden",
                    "kind": "park",
                    "area_m2": 900000.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [77.57, 12.91],
                                [77.58, 12.91],
                                [77.58, 12.92],
                                [77.57, 12.92],
                                [77.57, 12.91],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "face_id": "face-00002",
                    "protected": False,
                    "role": None,
                    "kind": "fabric",
                    "area_m2": 50000.0,
                },
            },
        ]
        stats = NormalizeStats(
            input_face_count=2,
            output_face_count=2,
            protected_count=1,
            fabric_count=1,
            scrap_merges=0,
            orphan_scraps=0,
            needs_review_count=0,
            below_soft_min=0,
            in_soft_band=1,
            above_soft_max=0,
            above_review_max=0,
            area_min_m2=50000.0,
            area_max_m2=900000.0,
            area_mean_m2=475000.0,
            area_total_m2=950000.0,
            input_area_total_m2=950000.0,
        )
        return features, stats

    monkeypatch.setattr("lib.normalize.normalize_faces", fake_normalize)
    return fake_normalize


@pytest.fixture
def stub_naming(monkeypatch):
    """Stage 07 without reading places / roads from disk."""

    from lib.determinism import territory_id as mint_id
    from lib.naming import NamingStats

    def fake_names(_ctx):
        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [77.58, 12.94],
                                [77.59, 12.94],
                                [77.59, 12.95],
                                [77.58, 12.95],
                                [77.58, 12.94],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "face_id": "face-00001",
                    "protected": True,
                    "role": "major",
                    "name": "Lalbagh Botanical Garden",
                    "slug": "lalbagh-botanical-garden",
                    "kind": "park",
                    "name_source": "landmark",
                    "needs_review": False,
                    "area_m2": 900000.0,
                    "territory_id": str(
                        mint_id("bengaluru", "jayanagar_lalbagh", "lalbagh-botanical-garden")
                    ),
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [77.57, 12.91],
                                [77.58, 12.91],
                                [77.58, 12.92],
                                [77.57, 12.92],
                                [77.57, 12.91],
                            ]
                        ]
                    ],
                },
                "properties": {
                    "face_id": "face-00002",
                    "protected": False,
                    "name": "Between A Street and B Road",
                    "slug": "between-a-street-and-b-road",
                    "kind": "block",
                    "name_source": "street_pair",
                    "needs_review": True,
                    "area_m2": 50000.0,
                    "territory_id": str(
                        mint_id(
                            "bengaluru",
                            "jayanagar_lalbagh",
                            "between-a-street-and-b-road",
                        )
                    ),
                },
            },
        ]
        stats = NamingStats(
            feature_count=2,
            by_name_source={"landmark": 1, "street_pair": 1},
            needs_review_count=1,
            protected_count=1,
            unique_slugs=2,
            unique_ids=2,
        )
        return features, stats

    monkeypatch.setattr("lib.naming.assign_names", fake_names)
    return fake_names


@pytest.fixture
def stub_validate(monkeypatch):
    """Stage 08 without requiring full AOI coverage from earlier stubs."""

    from lib import artifacts
    from lib.io import read_geojson
    from lib.validate import ValidationResult, write_chain_fingerprint

    def fake_validate(ctx):
        fingerprint = write_chain_fingerprint(ctx)
        named = read_geojson(artifacts.NAMED.path(ctx))
        features = [
            {
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": dict(f.get("properties") or {}),
            }
            for f in named.get("features") or []
        ]
        needs = [
            {
                "slug": (f.get("properties") or {}).get("slug"),
                "name": (f.get("properties") or {}).get("name"),
                "name_source": (f.get("properties") or {}).get("name_source"),
                "area_m2": (f.get("properties") or {}).get("area_m2"),
            }
            for f in features
            if (f.get("properties") or {}).get("needs_review") is True
        ]
        report = {
            "status": "pass",
            "stage": "validate",
            "hard": {"passed": True, "failures": []},
            "metrics": {
                "feature_count": len(features),
                "protected_count": sum(
                    1 for f in features if (f.get("properties") or {}).get("protected")
                ),
                "coverage_ratio": 1.0,
                "gap_m2": 0.0,
                "overlap_m2": 0.0,
                "projected_area_m2": 0.0,
                "geodesic_area_m2": 0.0,
                "aoi_area_m2": 0.0,
            },
            "soft": {
                "needs_review": needs,
                "needs_review_count": len(needs),
                "by_name_source": {},
                "size_bands": {},
                "unexpected_kinds": [],
            },
            "fingerprint_path": str(fingerprint.relative_to(ctx.repo_root)),
        }
        return ValidationResult(
            passed=True,
            report=report,
            candidates=features,
            fingerprint_path=fingerprint,
        )

    monkeypatch.setattr("lib.validate.validate_named", fake_validate)
    return fake_validate


@pytest.fixture
def stub_cluster(monkeypatch):
    """Stage 10 without requiring full-AOI coverage from stub parcels."""

    from lib import artifacts
    from lib.cluster import ClusterReport, ClusterResult
    from lib.determinism import content_hash
    from lib.io import artifact_hash_input, read_geojson

    def fake_cluster(ctx, **_kwargs):
        parcels = list(
            read_geojson(artifacts.PUBLISHED_TERRITORIES.path(ctx)).get("features") or []
        )
        features = []
        for feature in parcels:
            props = dict(feature.get("properties") or {})
            tid = str(props.get("territory_id"))
            props["member_territory_ids"] = [tid]
            props["member_count"] = 1
            props["layer"] = "gameplay"
            features.append(
                {
                    "type": "Feature",
                    "geometry": feature["geometry"],
                    "properties": props,
                }
            )
        report = ClusterReport(
            input_count=len(parcels),
            output_count=len(features),
            protected_count=sum(
                1 for f in features if (f.get("properties") or {}).get("protected")
            ),
            fabric_input_count=sum(
                1 for f in parcels if not (f.get("properties") or {}).get("protected")
            ),
            fabric_output_count=sum(
                1 for f in features if not (f.get("properties") or {}).get("protected")
            ),
            merges=0,
            barrier_blocked_edges=0,
            adjacency_edges=0,
            undersized_stuck=0,
            needs_review_count=sum(
                1 for f in features if (f.get("properties") or {}).get("needs_review")
            ),
            below_soft_min=0,
            in_soft_band=1,
            above_soft_max=0,
            above_review_max=0,
            area_min_m2=50000.0,
            area_max_m2=900000.0,
            area_median_m2=50000.0,
            area_mean_m2=475000.0,
            parcel_hash=content_hash(
                artifact_hash_input({"type": "FeatureCollection", "features": parcels})
            ),
            separators_hash="stub",
        )
        return ClusterResult(features=features, report=report)

    def fake_validate_gameplay(ctx, features, parcel_features=None, strict_shape=False):
        return {
            "status": "pass",
            "stage": "cluster_gameplay",
            "hard": {"passed": True, "failures": []},
            "metrics": {
                "feature_count": len(features),
                "protected_count": sum(
                    1 for f in features if (f.get("properties") or {}).get("protected")
                ),
                "coverage_ratio": 1.0,
                "gap_m2": 0.0,
                "overlap_m2": 0.0,
            },
            "soft": {"needs_review": [], "needs_review_count": 0},
        }

    monkeypatch.setattr("lib.cluster.cluster_parcels", fake_cluster)
    monkeypatch.setattr("lib.validate.validate_gameplay_features", fake_validate_gameplay)
    return fake_cluster


@pytest.fixture
def stub_pipeline_io(
    stub_downloads,
    stub_extract,
    stub_landmarks,
    stub_graph,
    stub_faces,
    stub_normalize,
    stub_naming,
    stub_validate,
    stub_cluster,
):
    """Stages 01–10 without network or GIS source files."""
    return (
        stub_downloads,
        stub_extract,
        stub_landmarks,
        stub_graph,
        stub_faces,
        stub_normalize,
        stub_naming,
        stub_validate,
        stub_cluster,
    )
