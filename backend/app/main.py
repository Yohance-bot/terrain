from fastapi import FastAPI

from app.api.v1 import accounts, admin_review, captured_areas, privacy, profile, runs, territories
from app.core.observability import configure_observability

app = FastAPI(
    title="Milestone 1 — Map and Territory Foundation",
    version="0.1.0",
    description=(
        "Prototype backend. Ownership is raw cumulative distance and nothing else; "
        "the influence model in 01_CORE_MECHANICS is deliberately not implemented."
    ),
)

app.include_router(territories.router, prefix="/v1")
app.include_router(captured_areas.router, prefix="/v1")
app.include_router(runs.router, prefix="/v1")
app.include_router(profile.router, prefix="/v1")
app.include_router(accounts.router, prefix="/v1")
app.include_router(privacy.router, prefix="/v1")
app.include_router(admin_review.router, prefix="/v1")
configure_observability(app)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness endpoint that does not depend on database availability."""
    return {"status": "ok", "service": "run-backend", "version": app.version}
