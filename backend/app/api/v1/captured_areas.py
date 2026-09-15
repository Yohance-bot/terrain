"""Public, player-created loop overlays.

The map receives only the server-validated enclosed polygon, never raw GPS
samples. Fixed territory boundaries and their influence ownership stay intact.
"""

import json
import uuid

from fastapi import APIRouter, Depends
from geoalchemy2 import Geometry
from sqlalchemy import String, func, select
from sqlalchemy.orm import Session

from app.api.deps import public_device_id
from app.core.db import get_session
from app.models import Account, CapturedArea, DeviceLink, Run, SandboxAccount

router = APIRouter(prefix="/captured-areas", tags=["captured-areas"])


@router.get("")
def list_captured_areas(
    linked_only: bool = False,
    device_id: uuid.UUID = Depends(public_device_id),
    session: Session = Depends(get_session),
) -> dict:
    # One exact topological union per owner. Old captures are normalised when
    # read: touching/overlapping loops become a single Polygon, gaps stay a
    # MultiPolygon. No buffer or proximity rule is applied.
    merged = func.ST_UnaryUnion(func.ST_Collect(func.ST_MakeValid(CapturedArea.geom.cast(Geometry))))
    statement = (
        select(
            CapturedArea.owner_device_id,
            func.min(CapturedArea.run_id.cast(String)).label("run_id"),
            func.ST_AsGeoJSON(merged).label("geometry"),
            func.ST_AsGeoJSON(func.ST_PointOnSurface(merged)).label("label_point"),
        )
        .join(Run, Run.id == CapturedArea.run_id)
        .where(
            Run.status == "applied",
            # Test-lab runners never appear on the shared map. A disposable
            # account capturing ground would otherwise show up for every real
            # player and shift real ownership until it was torn down.
            CapturedArea.owner_device_id.not_in(select(SandboxAccount.device_id)),
        )
        .group_by(CapturedArea.owner_device_id)
    )
    if linked_only:
        statement = statement.join(DeviceLink, DeviceLink.device_id == CapturedArea.owner_device_id)
    rows = session.execute(statement).all()
    names = dict(session.execute(select(DeviceLink.device_id, Account.display_name)
        .join(Account, Account.id == DeviceLink.account_id)
        .where(DeviceLink.device_id.in_([row[0] for row in rows]))).all()) if rows else {}
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": str(owner_device_id),
                "geometry": json.loads(geojson),
                "properties": {
                    "run_id": str(run_id),
                    "owner_device_id": str(owner_device_id),
                    "owner_display_name": names.get(owner_device_id, f"Runner {str(owner_device_id)[:5]}"),
                    "label_coordinate": json.loads(label_point)["coordinates"] if label_point else None,
                    "is_owned_by_you": owner_device_id == device_id,
                },
            }
            for owner_device_id, run_id, geojson, label_point in rows
            if geojson
        ],
    }
