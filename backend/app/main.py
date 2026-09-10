from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    accounts,
    admin_dashboard,
    admin_review,
    admin_social,
    authentication,
    captured_areas,
    challenges,
    console,
    ghosts,
    presence,
    privacy,
    profile,
    races,
    runs,
    social,
    territories,
)
from app.core.config import settings
from app.core.observability import configure_observability

app = FastAPI(
    title="Milestone 1 — Map and Territory Foundation",
    version="0.1.0",
    description=(
        "Prototype backend. Ownership is raw cumulative distance and nothing else; "
        "the influence model in 01_CORE_MECHANICS is deliberately not implemented."
    ),
)

if settings.admin_frontend_url:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.admin_frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(territories.router, prefix="/v1")
app.include_router(captured_areas.router, prefix="/v1")
app.include_router(runs.router, prefix="/v1")
app.include_router(profile.router, prefix="/v1")
app.include_router(accounts.router, prefix="/v1")
app.include_router(social.router, prefix="/v1")
app.include_router(presence.router, prefix="/v1")
app.include_router(challenges.router, prefix="/v1")
app.include_router(races.router, prefix="/v1")
app.include_router(ghosts.router, prefix="/v1")
app.include_router(authentication.router, prefix="/v1")
app.include_router(console.router, prefix="/v1")
app.include_router(privacy.router, prefix="/v1")
app.include_router(admin_review.router, prefix="/v1")
app.include_router(admin_dashboard.router, prefix="/v1")
app.include_router(admin_social.router, prefix="/v1")
configure_observability(app)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness endpoint that does not depend on database availability."""
    return {"status": "ok", "service": "run-backend", "version": app.version}
