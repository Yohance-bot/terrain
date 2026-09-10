"""Account identity is additive: territory and run ledgers remain device-keyed."""

import uuid
from secrets import compare_digest

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import device_id_header, resolve_device
from app.core.config import settings
from app.core.db import get_session
from app.models import (
    Account,
    AccountAuthMethod,
    AccountDeletionRequest,
    AuditEvent,
    DeviceLink,
    Run,
    Territory,
    TerritoryOwnership,
    TerritoryStanding,
)
from app.schemas import AccountSummary, AccountUpdate, DeveloperLogin, LocalAccountCreate
from app.services.social import handle_for

router = APIRouter(prefix="/account", tags=["account"])

DEVELOPER_DEVICE_IDS = (
    uuid.UUID("10000000-0000-4000-8000-000000000001"),
    uuid.UUID("10000000-0000-4000-8000-000000000002"),
    uuid.UUID("10000000-0000-4000-8000-000000000003"),
)


def account_for_device(session: Session, device_id: uuid.UUID) -> Account | None:
    statement = (
        select(Account)
        .join(DeviceLink, DeviceLink.account_id == Account.id)
        .where(DeviceLink.device_id == device_id)
    )
    return session.execute(statement).scalar_one_or_none()


def link_device_to_account(
    session: Session, device_id: uuid.UUID, account_id: uuid.UUID
) -> DeviceLink:
    """Idempotently link a device to an account.

    Reuses existing links, avoids duplicate inserts within the same unit of work,
    and updates the account if the device is switching accounts.
    """
    resolve_device(session, device_id)
    link = session.get(DeviceLink, device_id)
    if link is None:
        for pending in session.new:
            if isinstance(pending, DeviceLink) and pending.device_id == device_id:
                link = pending
                break
    if link is None:
        link = DeviceLink(device_id=device_id, account_id=account_id)
        session.add(link)
    else:
        link.account_id = account_id
    return link


def summary(session: Session, account: Account) -> AccountSummary:
    device_ids = select(DeviceLink.device_id).where(DeviceLink.account_id == account.id)
    total_distance = session.execute(
        select(func.coalesce(func.sum(Run.distance_m), 0)).where(Run.device_id.in_(device_ids))
    ).scalar_one()
    territories_led = session.execute(
        select(func.count())
        .select_from(TerritoryOwnership)
        .where(TerritoryOwnership.owner_device_id.in_(device_ids))
    ).scalar_one()
    auth_method = session.execute(
        select(AccountAuthMethod.provider, AccountAuthMethod.provider_subject)
        .where(AccountAuthMethod.account_id == account.id)
        .order_by(AccountAuthMethod.created_at)
        .limit(1)
    ).one_or_none()
    provider = auth_method[0] if auth_method else None
    subject = auth_method[1] if auth_method else ""
    developer_slot = None
    if provider == "developer" and subject.startswith("local-developer:"):
        try:
            developer_slot = int(subject.rsplit(":", 1)[1])
        except ValueError:
            developer_slot = None
    return AccountSummary(
        id=account.id,
        display_name=account.display_name,
        handle=handle_for(session, account),
        avatar_url=account.avatar_url,
        role=account.role,
        created_at=account.created_at,
        provider=provider,
        total_distance_m=float(total_distance or 0),
        territories_led=int(territories_led or 0),
        developer_slot=developer_slot,
    )


@router.get("", response_model=AccountSummary | None)
def get_account(
    device_id: uuid.UUID = Depends(device_id_header), session: Session = Depends(get_session)
) -> AccountSummary | None:
    resolve_device(session, device_id)
    account = account_for_device(session, device_id)
    return summary(session, account) if account else None


@router.put("", response_model=AccountSummary)
def update_account(
    update: AccountUpdate,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> AccountSummary:
    account = account_for_device(session, device_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in before editing your profile")
    account.display_name = update.display_name.strip()
    return summary(session, account)


@router.post("/sign-out", status_code=204)
def sign_out(
    device_id: uuid.UUID = Depends(device_id_header), session: Session = Depends(get_session)
) -> None:
    # Logout revokes a session through /auth/logout; ledger ownership is permanent.
    return None


@router.post("/deletion-request", status_code=202)
def request_deletion(
    device_id: uuid.UUID = Depends(device_id_header), session: Session = Depends(get_session)
) -> None:
    account = account_for_device(session, device_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in before requesting account deletion")
    session.add(AccountDeletionRequest(account_id=account.id, device_id=device_id))


@router.post("/developer-login", response_model=AccountSummary)
def developer_login(
    login: DeveloperLogin,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> AccountSummary:
    if settings.authenticated_accounts_enabled:
        raise HTTPException(410, "Use your developer username and password")
    pins = [pin.strip() for pin in settings.developer_mode_pins.split(",") if pin.strip()]
    slot = next(
        (
            index + 1
            for index, configured_pin in enumerate(pins[:3])
            if compare_digest(login.pin, configured_pin)
        ),
        None,
    )
    if not settings.developer_mode_enabled or slot is None:
        raise HTTPException(status_code=403, detail="Developer mode is unavailable")
    resolve_device(session, device_id)
    # Each configured pin maps to a fixed, separate developer account and a
    # matching simulated device identity. There can only be three slots.
    subject = f"local-developer:{slot}"
    method = session.execute(
        select(AccountAuthMethod).where(
            AccountAuthMethod.provider == "developer",
            AccountAuthMethod.provider_subject == subject,
        )
    ).scalar_one_or_none()
    if method is None:
        # Reuse the old single-developer POC identity as slot one if it exists.
        legacy_method = session.execute(
            select(AccountAuthMethod).where(
                AccountAuthMethod.provider == "developer",
                AccountAuthMethod.provider_subject == "local-developer",
            )
        ).scalar_one_or_none()
        if slot == 1 and legacy_method is not None:
            account = session.get(Account, legacy_method.account_id)
            assert account is not None
            legacy_method.provider_subject = subject
        else:
            account = Account(display_name=f"Developer {slot}", role="developer")
            session.add(account)
            session.flush()
            session.add(
                AccountAuthMethod(
                    account_id=account.id, provider="developer", provider_subject=subject
                )
            )
    else:
        account = session.get(Account, method.account_id)
        assert account is not None
        account.role = "developer"
    simulated_device_id = DEVELOPER_DEVICE_IDS[slot - 1]
    target_device_ids = {device_id, simulated_device_id}
    for target_id in target_device_ids:
        link_device_to_account(session, target_id, account.id)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        # Recover gracefully if a concurrent request already initialized this slot
        method = session.execute(
            select(AccountAuthMethod).where(
                AccountAuthMethod.provider == "developer",
                AccountAuthMethod.provider_subject == subject,
            )
        ).scalar_one_or_none()
        if method is not None:
            account = session.get(Account, method.account_id)
            if account is not None:
                account.role = "developer"
                for target_id in target_device_ids:
                    link_device_to_account(session, target_id, account.id)
                session.flush()
                return summary(session, account)
        raise

    return summary(session, account)


def require_local_accounts() -> None:
    if settings.authenticated_accounts_enabled or not settings.local_accounts_enabled:
        raise HTTPException(status_code=404, detail="Local accounts are disabled")


@router.get("/local-accounts", response_model=list[AccountSummary])
def list_local_accounts(session: Session = Depends(get_session)) -> list[AccountSummary]:
    """POC account switcher; no passwords are used outside this local environment."""
    require_local_accounts()
    accounts = session.execute(
        select(Account).where(Account.role == "player").order_by(Account.created_at)
    ).scalars().all()
    return [summary(session, account) for account in accounts]


@router.post("/local-accounts", response_model=AccountSummary)
def create_local_account(
    payload: LocalAccountCreate,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> AccountSummary:
    require_local_accounts()
    resolve_device(session, device_id)
    account = Account(display_name=payload.display_name.strip(), role="player")
    session.add(account)
    session.flush()
    session.add(
        AccountAuthMethod(
            account_id=account.id, provider="local", provider_subject=f"local:{account.id}"
        )
    )
    link_device_to_account(session, device_id, account.id)
    session.flush()
    return summary(session, account)


@router.post("/local-accounts/{account_id}/sign-in", response_model=AccountSummary)
def sign_in_local_account(
    account_id: uuid.UUID,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> AccountSummary:
    require_local_accounts()
    resolve_device(session, device_id)
    account = session.get(Account, account_id)
    if account is None or account.role != "player":
        raise HTTPException(status_code=404, detail="Player account not found")
    link_device_to_account(session, device_id, account.id)
    session.flush()
    return summary(session, account)


def require_developer(session: Session, device_id: uuid.UUID) -> Account:
    account = account_for_device(session, device_id)
    if not settings.developer_mode_enabled or account is None or account.role != "developer":
        raise HTTPException(status_code=403, detail="Developer mode is unavailable")
    return account


@router.post("/developer/territories/{territory_id}/reset", status_code=204)
def reset_territory(
    territory_id: uuid.UUID,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> None:
    """Local developer reset: clears only derived state, never activity ledgers."""
    developer = require_developer(session, device_id)
    territory = session.get(Territory, territory_id)
    if territory is None:
        raise HTTPException(status_code=404, detail="Territory not found")
    ownership = session.get(TerritoryOwnership, territory_id)
    before = {"owner_device_id": str(ownership.owner_device_id) if ownership else None}
    session.execute(delete(TerritoryStanding).where(TerritoryStanding.territory_id == territory_id))
    session.execute(
        delete(TerritoryOwnership).where(TerritoryOwnership.territory_id == territory_id)
    )
    session.add(
        AuditEvent(
            actor_kind="developer",
            actor_ref=str(developer.id),
            action="developer_reset_territory",
            target_type="territory",
            target_ref=str(territory_id),
            before_state=before,
            after_state={"owner_device_id": None},
            reason="Local developer reset",
        )
    )
