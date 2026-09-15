import json
import uuid
from collections.abc import Iterable
from hashlib import sha256

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import func, select, text
from geoalchemy2 import Geometry
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_session
from app.models import (
    Account,
    DeviceLink,
    SandboxAccount,
    Territory,
    TerritoryOwnership,
    TerritoryStanding,
)
from app.schemas import (
    FeatureCollection,
    TerritoryDetails,
    TerritoryInfluenceEntry,
    TerritoryState,
)

router = APIRouter(prefix="/territories", tags=["territories"])

# Required at all times, no exceptions, per `03_MAP_AND_TERRITORY_PIPELINE`.
# Served alongside the data so a client cannot render boundaries without it.
ATTRIBUTION = "© OpenStreetMap contributors"
DATASET_VERSION_HEADER = "X-Territory-Dataset-Version"

_OWNED_AREAS_SQL = text(
    """
    SELECT
        ownership.owner_device_id,
        ST_AsGeoJSON(ST_UnaryUnion(ST_Collect(territory.geom::geometry))) AS geometry
    FROM territories AS territory
    JOIN territory_ownership AS ownership
      ON ownership.territory_id = territory.id
    WHERE territory.city = :city
      AND territory.area = :area
      AND ownership.owner_device_id IS NOT NULL
    GROUP BY ownership.owner_device_id
    """
)


def territory_dataset_version(
    territories: Iterable[Territory], *, city: str, area: str
) -> str:
    """Return a stable version for the published shape set in one region.

    A territory's individual version is not a dataset version: adding, removing,
    or changing a different territory must also invalidate the mobile cache.
    The opaque digest is safe to compare for equality but has no ordering
    semantics.  The legacy integer body field remains for existing clients.
    """
    payload = {
        "city": city,
        "area": area,
        "territories": sorted(
            (
                {
                    "id": str(territory.id),
                    "version": territory.version,
                }
                for territory in territories
            ),
            key=lambda territory: territory["id"],
        ),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return sha256(encoded).hexdigest()


def dataset_headers(version: str, *, cacheable: bool = False) -> dict[str, str]:
    headers = {DATASET_VERSION_HEADER: version}
    if cacheable:
        # A republish changes the ETag, while the custom header is easier for
        # native clients to persist beside their cached GeoJSON.
        headers.update({"ETag": f'"{version}"', "Cache-Control": "public, max-age=86400"})
    return headers


def etag_matches(if_none_match: str | None, version: str) -> bool:
    if not if_none_match:
        return False
    tags = {tag.strip().strip('"') for tag in if_none_match.split(",")}
    return "*" in tags or version in tags


@router.get("", response_model=FeatureCollection)
def list_territories(
    response: Response,
    city: str = settings.territory_city,
    area: str = settings.territory_area,
    if_none_match: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> FeatureCollection | Response:
    rows = session.execute(
        select(Territory, func.ST_AsGeoJSON(Territory.geom))
        .where(Territory.city == city, Territory.area == area)
        .order_by(Territory.name)
    ).all()

    features = [
        {
            "type": "Feature",
            "id": str(territory.id),
            "geometry": json.loads(geojson),
            "properties": {
                "territory_id": str(territory.id),
                "slug": territory.slug,
                "name": territory.name,
                "kind": territory.kind,
                "version": territory.version,
            },
        }
        for territory, geojson in rows
    ]

    version_tag = territory_dataset_version(
        (territory for territory, _ in rows), city=city, area=area
    )
    headers = dataset_headers(version_tag, cacheable=True)
    if etag_matches(if_none_match, version_tag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    # Kept as an integer so the established FeatureCollection response remains
    # compatible. New clients should use X-Territory-Dataset-Version, which is
    # a collision-resistant version of the complete published set.
    dataset_version = int(version_tag[:8], 16)
    return FeatureCollection(
        dataset_version=dataset_version,
        attribution=ATTRIBUTION,
        features=features,
    )


@router.get("/state", response_model=list[TerritoryState])
def territory_state(
    response: Response,
    city: str = settings.territory_city,
    area: str = settings.territory_area,
    session: Session = Depends(get_session),
) -> list[TerritoryState]:
    """Current owner per territory, for colouring the map.

    Deliberately carries no influence, share or standing breakdown -- only who
    holds it and how much distance the leader has.
    """
    leader_distance = (
        select(func.max(TerritoryStanding.total_distance_m))
        .where(
            TerritoryStanding.territory_id == Territory.id,
            TerritoryStanding.device_id.not_in(select(SandboxAccount.device_id)),
        )
        .correlate(Territory)
        .scalar_subquery()
    )

    rows = session.execute(
        select(Territory, TerritoryOwnership.owner_device_id, leader_distance, Account.display_name,
               func.ST_AsGeoJSON(func.ST_PointOnSurface(Territory.geom.cast(Geometry))))
        .outerjoin(TerritoryOwnership, TerritoryOwnership.territory_id == Territory.id)
        .outerjoin(DeviceLink, DeviceLink.device_id == TerritoryOwnership.owner_device_id)
        .outerjoin(Account, Account.id == DeviceLink.account_id)
        .where(Territory.city == city, Territory.area == area)
        .order_by(Territory.name)
    ).all()

    response.headers.update(
        dataset_headers(
            territory_dataset_version(
                (territory for territory, *_ in rows), city=city, area=area
            )
        )
    )

    return [
        TerritoryState(
            territory_id=territory.id,
            slug=territory.slug,
            name=territory.name,
            kind=territory.kind,
            version=territory.version,
            owner_device_id=owner_id,
            owner_display_name=(display_name or f"Runner {str(owner_id)[:5]}") if owner_id else None,
            label_coordinate=json.loads(label_point)["coordinates"] if label_point else None,
            total_distance_m=float(total or 0),
        )
        for territory, owner_id, total, display_name, label_point in rows
    ]


@router.get("/owned-areas")
def owned_territory_areas(
    city: str = settings.territory_city,
    area: str = settings.territory_area,
    x_device_id: uuid.UUID | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """Return one dissolved geometry per owner for map rendering only.

    ST_UnaryUnion merges only overlapping or touching polygon topology. It has
    no buffer or distance threshold, so territory gaps and different owners
    remain separate. Fixed territory ownership and scoring are not changed.
    """
    rows = session.execute(_OWNED_AREAS_SQL, {"city": city, "area": area}).mappings().all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": str(row["owner_device_id"]),
                "geometry": json.loads(row["geometry"]),
                "properties": {
                    "owner_device_id": str(row["owner_device_id"]),
                    "is_owned_by_you": row["owner_device_id"] == x_device_id,
                },
            }
            for row in rows
            if row["geometry"]
        ],
    }


@router.get("/{territory_id}", response_model=TerritoryDetails)
def territory_details(
    territory_id: uuid.UUID,
    x_device_id: uuid.UUID | None = Header(default=None),
    session: Session = Depends(get_session),
) -> TerritoryDetails:
    """Return the public leaderboard for a territory.

    Device ids are intentionally pseudonymous in this prototype. The client gets
    a stable short label, influence shares, distance and legacy; it never gets
    raw traces or private profile data.
    """
    territory = session.get(Territory, territory_id)
    if territory is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Territory not found")

    owner = session.execute(
        select(TerritoryOwnership.owner_device_id).where(
            TerritoryOwnership.territory_id == territory_id
        )
    ).scalar_one_or_none()
    rows = session.execute(
        select(TerritoryStanding, Account.display_name)
        .outerjoin(DeviceLink, DeviceLink.device_id == TerritoryStanding.device_id)
        .outerjoin(Account, Account.id == DeviceLink.account_id)
        .where(
            TerritoryStanding.territory_id == territory_id,
            TerritoryStanding.total_distance_m > 0,
            # The test lab is invisible in the shared world it tests against.
            TerritoryStanding.device_id.not_in(select(SandboxAccount.device_id)),
        )
        .order_by(
            TerritoryStanding.active_influence.desc(), TerritoryStanding.total_distance_m.desc()
        )
    ).all()
    total_active = sum(float(standing.active_influence or 0) for standing, _ in rows)
    total_distance = sum(float(standing.total_distance_m or 0) for standing, _ in rows)

    standings = [
        TerritoryInfluenceEntry(
            device_id=standing.device_id,
            display_name=display_name or f"Runner {str(standing.device_id)[:6].upper()}",
            active_influence=round(float(standing.active_influence or 0), 2),
            legacy_influence=round(float(standing.legacy_influence or 0), 2),
            total_distance_m=round(float(standing.total_distance_m or 0), 1),
            share=round(
                (float(standing.active_influence or 0) / total_active * 100)
                if total_active
                else (float(standing.total_distance_m or 0) / total_distance * 100),
                1,
            ) if total_distance else 0,
            is_owner=standing.device_id == owner,
            is_you=x_device_id is not None and standing.device_id == x_device_id,
        )
        for standing, display_name in rows
    ]
    return TerritoryDetails(
        territory_id=territory.id,
        slug=territory.slug,
        name=territory.name,
        kind=territory.kind,
        owner_device_id=owner,
        total_active_influence=round(total_active, 2),
        standings=standings,
    )
