"""Network downloads for stage 01.

Kept out of the stage module so tests can monkeypatch the two entry points
without loading stages by path or touching the network. Everything here is
build-time only -- the running app never calls it.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
from overturemaps.core import record_batch_reader, type_theme_map
from overturemaps.writers import copy, get_writer

from lib.determinism import file_hash

USER_AGENT = "run-territory-pipeline/0.1 (build-time; +https://github.com/)"

# Feature types to pull for each configured theme. Stage 01 downloads whole
# types for the AOI bbox; stage 02 decides which classes become borders.
THEME_TYPES: dict[str, tuple[str, ...]] = {
    "base": ("land", "land_use", "water", "infrastructure"),
    "divisions": ("division", "division_area", "division_boundary"),
    "transportation": ("segment", "connector"),
}


@dataclass(frozen=True)
class DownloadedFile:
    """One file that ends up in the region's raw/ directory."""

    key: str
    source: str
    url: str
    filename: str
    path: Path
    sha256: str
    bytes: int
    skipped: bool
    theme: str | None = None
    feature_type: str | None = None
    release: str | None = None


def sha256_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".sha256")


def write_checksum(path: Path, digest: str | None = None) -> str:
    """Write `<file>.sha256` containing just the hex digest.

    The checksum sidecar is what later runs use to decide whether a re-download
    is needed, and what gets committed for auditability even when the extract
    itself is gitignored.
    """
    digest = digest or file_hash(str(path))
    sha256_path(path).write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return digest


def read_checksum(path: Path) -> str | None:
    sidecar = sha256_path(path)
    if not sidecar.exists():
        return None
    line = sidecar.read_text(encoding="utf-8").strip()
    return line.split()[0] if line else None


def already_valid(path: Path, force: bool) -> str | None:
    """Return the existing sha256 if the file is present and matches its sidecar.

    Verification is against the sidecar written after a previous successful
    download. A truncated file with a stale sidecar will not match and will be
    re-downloaded -- that is the whole point of checking after writing.
    """
    if force or not path.exists():
        return None
    recorded = read_checksum(path)
    if not recorded:
        return None
    if file_hash(str(path)) != recorded:
        return None
    return recorded


def download_http_file(
    *,
    key: str,
    source: str,
    url: str,
    dest: Path,
    force: bool = False,
    timeout: tuple[float, float] = (30.0, 600.0),
    chunk_bytes: int = 1024 * 1024,
) -> DownloadedFile:
    """Stream an HTTP(S) URL to disk, verify, and write a .sha256 sidecar."""
    existing = already_valid(dest, force)
    if existing is not None:
        return DownloadedFile(
            key=key,
            source=source,
            url=url,
            filename=dest.name,
            path=dest,
            sha256=existing,
            bytes=dest.stat().st_size,
            skipped=True,
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}

    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
        tmp_path = Path(tmp.name)
        try:
            with requests.get(url, stream=True, headers=headers, timeout=timeout) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=chunk_bytes):
                    if chunk:
                        tmp.write(chunk)
            tmp.flush()
            # Verify after the download, never before. A truncated part file that
            # somehow got renamed would poison every downstream stage.
            digest = file_hash(str(tmp_path))
            tmp_path.replace(dest)
            write_checksum(dest, digest)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    return DownloadedFile(
        key=key,
        source=source,
        url=url,
        filename=dest.name,
        path=dest,
        sha256=file_hash(str(dest)),
        bytes=dest.stat().st_size,
        skipped=False,
    )


def download_overture_type(
    *,
    feature_type: str,
    release: str,
    bbox_wsen: tuple[float, float, float, float],
    dest: Path,
    force: bool = False,
    connect_timeout: int = 30,
    request_timeout: int = 600,
) -> DownloadedFile:
    """Download one Overture feature type for the AOI bbox as GeoParquet.

    This is a spatial fetch filter, not geometry clipping: the raw extract still
    holds full features that intersect the bbox. Stage 02 owns class filtering;
    stage 05 owns carving. Using the bbox here is the only practical way to
    fetch Overture without pulling hundreds of gigabytes of planet data.
    """
    theme = type_theme_map[feature_type]
    url = (
        f"s3://overturemaps-us-west-2/release/{release}/"
        f"theme={theme}/type={feature_type}/"
    )
    key = f"overture_{theme}_{feature_type}"

    existing = already_valid(dest, force)
    if existing is not None:
        return DownloadedFile(
            key=key,
            source="overture",
            url=url,
            filename=dest.name,
            path=dest,
            sha256=existing,
            bytes=dest.stat().st_size,
            skipped=True,
            theme=theme,
            feature_type=feature_type,
            release=release,
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    reader = record_batch_reader(
        feature_type,
        bbox=list(bbox_wsen),
        release=release,
        connect_timeout=connect_timeout,
        request_timeout=request_timeout,
        stac=True,
    )
    if reader is None:
        raise RuntimeError(
            f"Overture returned no reader for type={feature_type} "
            f"release={release} bbox={bbox_wsen}. The release may have expired "
            f"(Overture keeps ~60 days of public releases) or the bbox misses all data."
        )

    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
        tmp_path = Path(tmp.name)

    try:
        with get_writer("geoparquet", str(tmp_path), schema=reader.schema) as writer:
            copy(reader, writer)
        digest = file_hash(str(tmp_path))
        tmp_path.replace(dest)
        write_checksum(dest, digest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    return DownloadedFile(
        key=key,
        source="overture",
        url=url,
        filename=dest.name,
        path=dest,
        sha256=file_hash(str(dest)),
        bytes=dest.stat().st_size,
        skipped=False,
        theme=theme,
        feature_type=feature_type,
        release=release,
    )


def types_for_themes(themes: tuple[str, ...]) -> list[tuple[str, str]]:
    """Expand configured themes into (theme, feature_type) pairs, sorted."""
    pairs: list[tuple[str, str]] = []
    for theme in themes:
        if theme not in THEME_TYPES:
            raise ValueError(
                f"theme {theme!r} has no type mapping in lib.download.THEME_TYPES"
            )
        for feature_type in THEME_TYPES[theme]:
            pairs.append((theme, feature_type))
    return sorted(pairs)


# Hook point for tests: replace this to avoid network I/O in the suite.
DownloadOvertureFn = Callable[..., DownloadedFile]
DownloadHttpFn = Callable[..., DownloadedFile]
