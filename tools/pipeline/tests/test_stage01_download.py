"""Stage 01 download behaviour, without touching the network."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import artifacts
from lib.contracts import StageStatus
from lib.download import DownloadedFile, write_checksum
from lib.io import is_placeholder, read_json
from lib.registry import discover_stages


def _fake_overture(**kwargs) -> DownloadedFile:
    dest: Path = kwargs["dest"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"FAKE-OVERTURE")
    digest = write_checksum(dest)
    return DownloadedFile(
        key=f"overture_fake_{dest.stem}",
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


def _fake_http(**kwargs) -> DownloadedFile:
    dest: Path = kwargs["dest"]
    dest.parent.mkdir(parents=True, exist_ok=True)
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


@pytest.fixture
def stage01():
    return next(s for s in discover_stages() if s.number == 1)


def test_stage01_writes_real_manifest(ctx, stage01, monkeypatch):
    monkeypatch.setattr("lib.download.download_overture_type", _fake_overture)
    monkeypatch.setattr("lib.download.download_http_file", _fake_http)

    result = stage01.run(ctx)

    assert result.status is StageStatus.OK
    manifest_path = artifacts.RAW_MANIFEST.path(ctx)
    assert manifest_path.exists()
    assert not is_placeholder(manifest_path)

    manifest = read_json(manifest_path)
    assert manifest["status"] == "ok"
    assert manifest["overture_release"] == "2026-07-22.0"
    assert manifest["bbox"]["south"] == pytest.approx(12.9)
    assert {f["source"] for f in manifest["files"]} == {"overture", "geofabrik"}
    assert all("sha256" in f and f["bytes"] > 0 for f in manifest["files"])
    # Stable ordering: two identical runs must produce the same key sequence.
    keys = [f["key"] for f in manifest["files"]]
    assert keys == sorted(keys)


def test_stage01_skips_when_checksum_matches(ctx, stage01, monkeypatch):
    from lib.determinism import file_hash
    from lib.download import already_valid

    monkeypatch.setattr("lib.download.download_overture_type", _fake_overture)
    monkeypatch.setattr("lib.download.download_http_file", _fake_http)
    stage01.run(ctx)

    # Exercise the real skip path on files already on disk.
    sample = next(ctx.raw_dir.glob("overture_*.geoparquet"))
    assert already_valid(sample, force=False) == file_hash(str(sample))
    assert already_valid(sample, force=True) is None


def test_download_http_skips_when_checksum_matches(tmp_path, monkeypatch):
    from lib.download import download_http_file

    dest = tmp_path / "southern-zone.osm.pbf"
    dest.write_bytes(b"already-here")
    digest = write_checksum(dest)

    def boom(*_args, **_kwargs):
        raise AssertionError("network should not be touched when checksum matches")

    monkeypatch.setattr("lib.download.requests.get", boom)
    result = download_http_file(
        key="geofabrik_extract",
        source="geofabrik",
        url="https://example.invalid/extract.osm.pbf",
        dest=dest,
        force=False,
    )
    assert result.skipped is True
    assert result.sha256 == digest


def test_already_valid_rejects_truncated_file(tmp_path):
    from lib.download import already_valid

    path = tmp_path / "extract.pbf"
    path.write_bytes(b"complete-payload")
    write_checksum(path)
    path.write_bytes(b"truncated")
    assert already_valid(path, force=False) is None
