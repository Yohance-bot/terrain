"""Identity and reproducibility helpers.

Fully implemented in Phase A. These are small, and every other stage depends on
them being exactly right, so they are not left as stubs.

The pipeline promises two things:

1. The same source inputs produce byte-identical output.
2. A territory keeps its identifier forever, even when its shape is redrawn.

Those pull in opposite directions if you are careless, and the trap is worth
spelling out. It is tempting to derive a territory's id from a hash of its
geometry -- it makes the id feel "content addressed". It is wrong. Redrawing
Lalbagh's boundary by one metre would mint a brand new territory, orphaning
every run segment, standing and ownership row that pointed at the old one.

So: identity comes from `city/area/slug` and nothing else. Geometry hashes are
used only to *detect* that a shape changed, which is what bumps the version
column. `03_MAP_AND_TERRITORY_PIPELINE` requires exactly this split.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

# Shared with tools/territory-import so Milestone 1 and Milestone 2 mint the
# same id for the same place. Do not change this value, ever.
TERRITORY_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

T = TypeVar("T")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Lowercase, hyphenated, ASCII-safe key derived from a display name.

    Used for both filenames and the `territories.slug` column, so it must stay
    stable: changing this function renames every territory and, through
    `territory_id`, re-identifies them.
    """
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"name {name!r} does not reduce to a usable slug")
    return slug


def territory_id(city: str, area: str, slug: str) -> uuid.UUID:
    """Permanent identifier for a territory.

    Deliberately independent of geometry, name and version. See module docstring.
    """
    return uuid.uuid5(TERRITORY_NAMESPACE, f"{city}/{area}/{slug}")


def gameplay_territory_id(city: str, area: str, slug: str) -> uuid.UUID:
    """Permanent identifier for a Stage 10 gameplay territory.

    Separate namespace path from parcel ids so multi-parcel merges never collide
    with Stage 09 parcel identity. Protected passthrough may reuse the parcel
    ``territory_id`` instead; see ``lib.cluster``.
    """
    return uuid.uuid5(TERRITORY_NAMESPACE, f"{city}/{area}/gameplay/{slug}")


def canonical_json(value: Any) -> str:
    """JSON with sorted keys and no incidental whitespace.

    Two pipeline runs that computed the same thing must produce the same bytes,
    otherwise "did anything change?" can only be answered by reading diffs by
    hand. Sorting keys is what makes that true regardless of dict insertion
    order.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    """Stable SHA-256 of any JSON-serialisable value.

    Applied to a geometry's coordinates this answers "has this shape changed
    since the last publish?", which is the signal stage 09 uses to decide
    whether to bump a territory's version.
    """
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: str, chunk_bytes: int = 1024 * 1024) -> str:
    """SHA-256 of a file, streamed.

    Source extracts are hundreds of megabytes, so stage 01 must not read them
    into memory to verify a download.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sort(items: Iterable[T], key: Callable[[T], Any]) -> list[T]:
    """Sort with an explicit key, for use before writing any collection.

    Set iteration order, dict ordering from a parallel read, and most GIS
    library outputs are not reproducible across runs. Every stage sorts its
    features on a stable key -- normally the slug or a coordinate tuple -- as
    the last thing it does before writing.
    """
    return sorted(items, key=key)
