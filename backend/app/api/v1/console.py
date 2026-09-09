"""Named console accounts and shared notes. Every write has an authenticated author."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import console_member
from app.api.v1.authentication import Credentials, member_json
from app.core.authentication import password_hash
from app.core.db import get_session
from app.models import AuditEvent, AuthSession, ConsoleNote, ConsoleUser, LoginCredential

router = APIRouter(prefix="/admin/console", tags=["console"])


def audit(session, user, action, target, reason):
    session.add(
        AuditEvent(
            action=action,
            target_type="console",
            target_ref=str(target),
            actor_kind="console_user",
            actor_ref=str(user.id),
            reason=reason,
        )
    )


@router.get("/me")
def me(user: ConsoleUser = Depends(console_member), session: Session = Depends(get_session)):
    return member_json(session, user)


@router.get("/members")
def members(user: ConsoleUser = Depends(console_member), session: Session = Depends(get_session)):
    return [
        dict(member_json(session, p), active=p.active)
        for p in session.scalars(select(ConsoleUser).order_by(ConsoleUser.created_at))
    ]


class NewMember(Credentials):
    display_name: str = Field(min_length=2, max_length=64)
    role: Literal["owner", "admin"] = "admin"


@router.post("/members", status_code=201)
def add_member(
    payload: NewMember,
    user: ConsoleUser = Depends(console_member),
    session: Session = Depends(get_session),
):
    if user.role != "owner":
        raise HTTPException(403, "Only an owner can create console accounts")
    if len(payload.password) < 12:
        raise HTTPException(422, "Use at least 12 characters for the password")
    if session.scalar(
        select(LoginCredential.id).where(
            LoginCredential.scope == "admin", LoginCredential.username == payload.username
        )
    ):
        raise HTTPException(409, "That username is unavailable")
    member = ConsoleUser(display_name=payload.display_name.strip(), role=payload.role)
    session.add(member)
    session.flush()
    session.add(
        LoginCredential(
            scope="admin",
            principal_id=member.id,
            username=payload.username,
            password_hash=password_hash(payload.password),
        )
    )
    audit(session, user, "console.member.created", member.id, f"Created {payload.role} account")
    session.flush()
    return member_json(session, member)


class MemberState(BaseModel):
    active: bool


@router.patch("/members/{member_id}")
def member_state(
    member_id: uuid.UUID,
    payload: MemberState,
    user: ConsoleUser = Depends(console_member),
    session: Session = Depends(get_session),
):
    if user.role != "owner":
        raise HTTPException(403, "Only an owner can manage access")
    if member_id == user.id:
        raise HTTPException(409, "You cannot disable your own account")
    member = session.get(ConsoleUser, member_id)
    if not member:
        raise HTTPException(404, "Member not found")
    member.active = payload.active
    if not payload.active:
        session.execute(
            delete(AuthSession).where(
                AuthSession.scope == "admin", AuthSession.principal_id == member.id
            )
        )
    audit(
        session,
        user,
        "console.member.access",
        member.id,
        "Enabled" if payload.active else "Disabled",
    )
    return {"active": member.active}


class NoteInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(max_length=12000)
    status: Literal["open", "done"] = "open"

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("A title is required")
        return value.strip()


class NoteUpdate(NoteInput):
    version: str


def note_json(note, author):
    return {
        "id": str(note.id),
        "title": note.title,
        "body": note.body,
        "status": note.status,
        "author": author.display_name,
        "author_id": str(author.id),
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


@router.get("/notes")
def notes(user: ConsoleUser = Depends(console_member), session: Session = Depends(get_session)):
    rows = session.execute(
        select(ConsoleNote, ConsoleUser)
        .join(ConsoleUser, ConsoleUser.id == ConsoleNote.author_id)
        .order_by(ConsoleNote.updated_at.desc())
        .limit(200)
    )
    return [note_json(note, author) for note, author in rows]


@router.post("/notes", status_code=201)
def add_note(
    payload: NoteInput,
    user: ConsoleUser = Depends(console_member),
    session: Session = Depends(get_session),
):
    note = ConsoleNote(author_id=user.id, **payload.model_dump())
    session.add(note)
    session.flush()
    audit(session, user, "console.note.created", note.id, "Shared note created")
    return note_json(note, user)


@router.put("/notes/{note_id}")
def edit_note(
    note_id: uuid.UUID,
    payload: NoteUpdate,
    user: ConsoleUser = Depends(console_member),
    session: Session = Depends(get_session),
):
    note = session.scalar(select(ConsoleNote).where(ConsoleNote.id == note_id).with_for_update())
    if not note:
        raise HTTPException(404, "Note not found")
    if note.updated_at.isoformat() != payload.version:
        raise HTTPException(409, "This note changed. Refresh before editing again.")
    note.title, note.body, note.status = payload.title, payload.body, payload.status
    note.updated_at = func.clock_timestamp()
    session.flush()
    session.refresh(note)
    audit(session, user, "console.note.updated", note.id, "Shared note updated")
    return note_json(note, session.get(ConsoleUser, note.author_id))


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=6)


@router.post("/assistant")
def assistant_chat(
    payload: ChatRequest,
    user: ConsoleUser = Depends(console_member),
    session: Session = Depends(get_session),
):
    from app.core.authentication import throttle
    from app.services.assistant import answer

    throttle(f"assistant:{user.id}", limit=30)
    return answer(payload.question, [m.model_dump() for m in payload.history], session)
