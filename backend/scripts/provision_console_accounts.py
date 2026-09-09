"""One-time named account provisioning. Never changes existing passwords.
Run from backend. Credentials are written ONLY to the supplied private local path.
"""

import json
import os
import secrets
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.authentication import password_hash
from app.core.db import SessionLocal
from app.models import AccountAuthMethod, ConsoleUser, LoginCredential

output = Path(sys.argv[1]).resolve()
if output.exists():
    raise SystemExit("Credential output exists; refusing to overwrite it")
rows = []
with SessionLocal.begin() as session:
    for name, username in [("Unknown Owl", "unknown.owl"), ("Unknown Eagle", "unknown.eagle")]:
        if session.scalar(
            select(LoginCredential.id).where(
                LoginCredential.scope == "admin", LoginCredential.username == username
            )
        ):
            continue
        user = ConsoleUser(display_name=name, role="owner")
        session.add(user)
        session.flush()
        password = secrets.token_urlsafe(18)
        session.add(
            LoginCredential(
                scope="admin",
                principal_id=user.id,
                username=username,
                password_hash=password_hash(password),
            )
        )
        rows.append({"kind": "Admin", "name": name, "username": username, "password": password})
    for slot in (1, 2, 3):
        method = session.scalar(
            select(AccountAuthMethod).where(
                AccountAuthMethod.provider == "developer",
                AccountAuthMethod.provider_subject == f"local-developer:{slot}",
            )
        )
        if not method:
            raise RuntimeError(f"Developer slot {slot} is missing; provisioning rolled back")
        if session.scalar(
            select(LoginCredential.id).where(
                LoginCredential.scope == "app", LoginCredential.principal_id == method.account_id
            )
        ):
            continue
        password = secrets.token_urlsafe(18)
        username = f"developer.{slot}"
        session.add(
            LoginCredential(
                scope="app",
                principal_id=method.account_id,
                username=username,
                password_hash=password_hash(password),
            )
        )
        rows.append(
            {
                "kind": "Developer",
                "name": f"Developer {slot}",
                "username": username,
                "password": password,
            }
        )
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(rows, stream, indent=2)
print(f"Provisioned {len(rows)} accounts; credentials saved privately at {output}")
