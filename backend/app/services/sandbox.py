"""The test lab's account fixtures, and the teardown that removes them.

The lab drives the real player API rather than a mock of it, which means the
console needs a genuine session token per test runner. That is a sharp tool, so
it is blunted in one place: `require_sandbox` refuses any account that is not in
`sandbox_accounts`, and only `create_runner` ever writes that table.

Teardown is the other half of the contract. A lab that leaves runs and influence
behind would distort the live world it is testing against, so removing a runner
also reverses everything it did to shared state.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.authentication import issue_session
from app.core.config import settings
from app.models import (
    Account,
    AccountAuthMethod,
    AuthSession,
    CapturedArea,
    Challenge,
    ChallengeStake,
    Device,
    DeviceLink,
    FriendShareSettings,
    Friendship,
    GhostAttempt,
    GhostRun,
    InfluenceGrant,
    LivePosition,
    Race,
    Run,
    RunLifecycleEvent,
    RunTerritorySegment,
    SandboxAccount,
    SocialEvent,
)
from app.services.ownership import recompute_ownership

# Test runners are named so they are obvious in any list an operator opens.
LABEL_PREFIX = "Test"


def require_enabled() -> None:
    """The lab is a developer tool and never runs on a locked-down deployment."""
    if not settings.developer_mode_enabled:
        raise HTTPException(403, "The test lab is disabled on this deployment.")


def require_sandbox(session: Session, account_id: uuid.UUID) -> SandboxAccount:
    """The only gate that authorises acting as a player.

    Refusing anything outside `sandbox_accounts` is what stops this becoming a
    way to take over a real player's account from the console.
    """
    runner = session.get(SandboxAccount, account_id)
    if runner is None:
        raise HTTPException(404, "That is not a test runner.")
    return runner


def sandbox_account_ids(session: Session) -> list[uuid.UUID]:
    return list(session.execute(select(SandboxAccount.account_id)).scalars())


def sandbox_device_ids(session: Session) -> list[uuid.UUID]:
    return list(session.execute(select(SandboxAccount.device_id)).scalars())


def create_runner(session: Session, label: str, created_by: str | None) -> SandboxAccount:
    """An account, a device, and the link between them — a complete player."""
    display_name = label.strip()[:32] or f"{LABEL_PREFIX} Runner"
    account = Account(display_name=display_name, role="player")
    session.add(account)
    session.flush()

    device = Device(id=uuid.uuid4())
    session.add(device)
    session.flush()
    session.add(DeviceLink(device_id=device.id, account_id=account.id))

    runner = SandboxAccount(
        account_id=account.id, device_id=device.id, label=display_name, created_by=created_by
    )
    session.add(runner)
    session.flush()
    return runner


def mint_session(session: Session, account_id: uuid.UUID) -> str:
    """Issue a real app session so the console can call the real endpoints."""
    require_sandbox(session, account_id)
    return issue_session(session, "app", account_id)


# A synthetic route runs due north from its start, one fix every ten seconds.
SYNTHETIC_SPACING_M = 20.0
DEGREES_PER_M = 1 / 111_320.0


def synthesise_run(
    session: Session,
    runner: SandboxAccount,
    *,
    distance_m: float,
    duration_s: int,
    ended_at: datetime | None = None,
    route_from: tuple[float, float] | None = None,
) -> Run:
    """Write an applied run directly, for scoring without driving one.

    This bypasses the matching pipeline on purpose: it writes a number into the
    ledger so a challenge can be settled, and creates no influence grants, no
    territory segments and no captured areas. Geometry is therefore safe to
    include — it is what makes a run saveable as a ghost — and claims nothing.
    """
    ended = ended_at or datetime.now(UTC)
    started = ended - timedelta(seconds=duration_s)
    geom = None
    sample_ts = None
    accuracy = None
    if route_from is not None:
        lon, lat = route_from
        points = max(2, min(400, int(distance_m / SYNTHETIC_SPACING_M) + 1))
        step = SYNTHETIC_SPACING_M * DEGREES_PER_M
        origin_ms = int(started.timestamp() * 1000)
        interval = max(1, int(duration_s / (points - 1)))
        coordinates = [(lon, lat + step * index) for index in range(points)]
        geom = "SRID=4326;LINESTRING(" + ", ".join(f"{x} {y}" for x, y in coordinates) + ")"
        sample_ts = [origin_ms + index * interval * 1000 for index in range(points)]
        accuracy = [5.0] * points

    run = Run(
        id=uuid.uuid4(),
        device_id=runner.device_id,
        started_at=started,
        ended_at=ended,
        duration_s=duration_s,
        distance_m=distance_m,
        geom=geom,
        sample_ts=sample_ts,
        sample_accuracy_m=accuracy,
        raw_payload={"synthetic": True, "source": "admin-test-lab"},
        status="applied",
        source="tracked",
        pipeline_version=settings.pipeline_version,
    )
    session.add(run)
    session.flush()
    session.add(
        RunLifecycleEvent(
            run_id=run.id,
            sequence=1,
            from_status=None,
            to_status="applied",
            actor_kind="admin",
            actor_ref="test-lab",
            reason="Synthetic run created by the console test lab",
        )
    )
    return run


def fast_forward_challenge(session: Session, challenge: Challenge) -> Challenge:
    """Move a challenge's whole window into the past so it comes due now.

    The window is shifted rather than truncated: `window_end > window_start` is a
    database constraint, and a challenge whose window collapsed would not be a
    realistic thing to settle.
    """
    # The window ends *now*, not a second ago: an operator who has just added
    # runs and pressed "settle" means those runs to count, and a run finishing
    # after `window_end` is excluded by the resolver.
    length = challenge.window_end - challenge.window_start
    challenge.window_end = datetime.now(UTC)
    challenge.window_start = challenge.window_end - length
    if challenge.status == "pending":
        challenge.accept_deadline = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()
    return challenge


def fast_forward_race(session: Session, race: Race) -> Race:
    """Age a race out, to check that an abandoned one lapses quietly."""
    now = datetime.now(UTC) - timedelta(seconds=1)
    race.accept_deadline = min(race.accept_deadline, now)
    if race.expires_at is not None:
        race.expires_at = now
    session.flush()
    return race


def teardown(session: Session, account_ids: list[uuid.UUID] | None = None) -> dict[str, int]:
    """Remove test runners and everything they did to shared state.

    Influence is reversed before the rows go, and every territory the lab touched
    is recomputed, so the live map is left exactly as it was found.
    """
    ids = account_ids if account_ids is not None else sandbox_account_ids(session)
    if not ids:
        return {"runners": 0, "runs": 0, "territories_recomputed": 0}

    devices = list(
        session.execute(
            select(SandboxAccount.device_id).where(SandboxAccount.account_id.in_(ids))
        ).scalars()
    )
    run_ids = list(
        session.execute(select(Run.id).where(Run.device_id.in_(devices))).scalars()
    )
    touched = set(
        session.execute(
            select(InfluenceGrant.territory_id).where(InfluenceGrant.device_id.in_(devices))
        ).scalars()
    )

    # Social state first: these reference accounts, and some cascade from runs.
    ghost_ids = list(
        session.execute(select(GhostRun.id).where(GhostRun.account_id.in_(ids))).scalars()
    )
    if ghost_ids:
        session.execute(delete(GhostAttempt).where(GhostAttempt.ghost_id.in_(ghost_ids)))
    session.execute(delete(GhostAttempt).where(GhostAttempt.account_id.in_(ids)))
    session.execute(delete(GhostRun).where(GhostRun.account_id.in_(ids)))

    challenge_ids = list(
        session.execute(
            select(Challenge.id).where(
                or_(Challenge.challenger_id.in_(ids), Challenge.opponent_id.in_(ids))
            )
        ).scalars()
    )
    if challenge_ids:
        session.execute(delete(ChallengeStake).where(ChallengeStake.challenge_id.in_(challenge_ids)))
        # A transferred stake points back at the challenge that moved it.
        session.execute(
            text(
                "UPDATE captured_areas SET transferred_by_challenge_id = NULL "
                "WHERE transferred_by_challenge_id = ANY(:ids)"
            ),
            {"ids": challenge_ids},
        )
        session.execute(delete(Challenge).where(Challenge.id.in_(challenge_ids)))

    session.execute(
        delete(Race).where(or_(Race.challenger_id.in_(ids), Race.opponent_id.in_(ids)))
    )
    session.execute(
        delete(Friendship).where(
            or_(Friendship.requester_id.in_(ids), Friendship.addressee_id.in_(ids))
        )
    )
    session.execute(
        delete(FriendShareSettings).where(
            or_(
                FriendShareSettings.owner_id.in_(ids),
                FriendShareSettings.viewer_id.in_(ids),
            )
        )
    )
    session.execute(delete(LivePosition).where(LivePosition.account_id.in_(ids)))
    session.execute(
        delete(SocialEvent).where(
            or_(SocialEvent.account_id.in_(ids), SocialEvent.actor_id.in_(ids))
        )
    )

    # Then the run ledger, which is what shared territory state derives from.
    if run_ids:
        session.execute(delete(CapturedArea).where(CapturedArea.run_id.in_(run_ids)))
        session.execute(delete(InfluenceGrant).where(InfluenceGrant.run_id.in_(run_ids)))
        session.execute(delete(RunTerritorySegment).where(RunTerritorySegment.run_id.in_(run_ids)))
        session.execute(delete(RunLifecycleEvent).where(RunLifecycleEvent.run_id.in_(run_ids)))
        session.execute(delete(Run).where(Run.id.in_(run_ids)))
    session.execute(
        text("DELETE FROM territory_standings WHERE device_id = ANY(:ids)"), {"ids": devices}
    )

    session.execute(delete(AuthSession).where(AuthSession.principal_id.in_(ids)))
    session.execute(delete(AccountAuthMethod).where(AccountAuthMethod.account_id.in_(ids)))
    session.execute(delete(SandboxAccount).where(SandboxAccount.account_id.in_(ids)))
    session.execute(delete(DeviceLink).where(DeviceLink.account_id.in_(ids)))
    session.execute(delete(Account).where(Account.id.in_(ids)))
    session.execute(delete(Device).where(Device.id.in_(devices)))
    session.flush()

    # Recompute last, once the lab's grants are gone, so ownership settles back.
    for territory_id in touched:
        recompute_ownership(session, territory_id)

    return {
        "runners": len(ids),
        "runs": len(run_ids),
        "territories_recomputed": len(touched),
    }


def public_exclusion(session: Session) -> list[uuid.UUID]:
    """Devices the public map must not show.

    A test runner capturing ground in Jayanagar would appear on every real
    player's map, so the lab is kept out of the shared view entirely.
    """
    return sandbox_device_ids(session)


def count_runners(session: Session) -> int:
    return int(
        session.execute(select(func.count()).select_from(SandboxAccount)).scalar_one() or 0
    )
