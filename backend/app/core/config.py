from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = "https://wqhwnfnesigiytyhikuj.supabase.co"
    supabase_publishable_key: str = "sb_publishable_NEaAQwLQLCNXxYVyNtIKpg_sWZAg0xL"
    groq_api_key: SecretStr | None = None
    api_key: SecretStr | None = None  # Compatibility with the user-provided .env name.
    groq_model: str = "openai/gpt-oss-120b"
    authenticated_accounts_enabled: bool = True

    database_url: str = "postgresql+psycopg://localhost:5432/run_prototype"
    # Internal operations are deliberately disabled until a non-empty token is
    # configured. This is a temporary boundary, not a replacement for RBAC.
    admin_operations_token: SecretStr | None = None
    # Allowed origin for the Admin Dashboard SPA to support CORS.
    admin_frontend_url: str | None = None
    # Local developer tooling has two independent gates: the mobile client only
    # renders it in a debug bundle and the server refuses it unless this local
    # switch and pin are configured. Never enable these in a deployed backend.
    developer_mode_enabled: bool = False
    # Comma-separated local POC pins for the three fixed developer runners.
    developer_mode_pins: str = "2468,1357,9876"
    # POC-only local identities. This must remain disabled once real provider
    # authentication is configured for a shared environment.
    local_accounts_enabled: bool = False

    # Privacy retention is enforced by the scheduled backend job, never by the
    # mobile client. These values implement the declared Phase 1 policy.
    raw_trace_retention_days: int = 30
    route_polyline_full_precision_days: int = 90
    reduced_route_simplification_m: float = 25.0

    # Server-authoritative Phase 1 matching parameters.
    # A GPS sample less accurate than this is dropped before the route is built.
    max_accuracy_m: float = 50.0
    # Any valid, non-zero segment inside a territory contributes to its normal
    # leaderboard standing. Loop capture remains a distinct ownership action.
    min_presence_m: float = 1.0
    min_presence_s: int = 0

    # Phase 2 loop capture. These are evaluated exclusively from the submitted
    # trace on the server; the phone's live loop preview carries no authority.
    loop_min_distance_m: float = 350.0
    loop_closure_distance_m: float = 45.0
    loop_min_area_m2: float = 1200.0
    # A confirmed loop must overcome the current leader rather than merely
    # contributing a small amount of ordinary traversal influence.
    loop_capture_margin: float = 1.0

    # Stamped onto every run so results can be attributed to the matching logic
    # that produced them, and reprocessed when that logic changes.
    pipeline_version: int = 1

    # Version of the rules used to interpret matched segments. It is separate
    # from pipeline_version so matching can change independently from gameplay
    # rules. S0 keeps this local; a future configuration revision service will
    # resolve it from persisted, audited configuration.
    ruleset_version: int = 1

    # Phase 1 influence tuning. These stay server-side and are stamped on each
    # immutable grant so later ruleset changes can be replayed deterministically.
    influence_distance_weight: float = 1.0
    influence_moving_time_weight: float = 0.01
    walking_weight: float = 0.7
    running_weight: float = 1.0
    influence_gamma: float = 1.0
    running_pace_ceiling_s_per_km: float = 600.0
    default_decay_half_life_days: float = 14.0
    abandonment_floor: float = 1.0

    # S4 progression constants. They are intentionally explicit and returned in
    # profile summaries so this prototype does not hide progression formulas.
    home_change_cooldown_days: int = 30
    xp_meters_per_point: float = 10.0
    xp_per_level: int = 1_000
    prestige_legacy_weight: float = 1.0
    prestige_active_weight: float = 1.0
    prestige_run_weight: float = 10.0

    territory_city: str = "bengaluru"
    territory_area: str = "jayanagar"

    # When enabled, log complete HTTP 422 response bodies for local debugging.
    # Disable in production deployments via LOG_HTTP_422_RESPONSE_BODIES=false.
    log_http_422_response_bodies: bool = True


settings = Settings()
