# TerraRun console and authentication — September 2026

## Confirmed login root cause
The mobile `.env.local` pointed to an expired ngrok tunnel and overrode the correct production Render URL. That tunnel returned HTTP 404 / ERR_NGROK_3200. Render was running, `/health` returned 200, and Supabase terrain-production was active and reachable. A warm account request also took 10.45 seconds, exceeding the previous 8-second client timeout. Account requests now allow 90 seconds for the free Render instance to wake.

## Release contents
- Mobile Google OAuth through Supabase, username/password login and registration, editable profile credentials, and revised home/sign-in icons.
- Separate named console accounts, owner-controlled additional accounts and access revocation. Unknown Owl and Unknown Eagle are initial owners; developer.1 through developer.3 preserve the existing developer slots.
- Persistent shared notes with authors, open/done status and optimistic conflict detection.
- Scout: Groq-backed source search, file inspection, source citations, live aggregate counts, navigation links, and explanatory/test-plan drafts. It has no shell, arbitrary SQL, deployment or write tools.
- Console world map reuses app road colors, roofs and cyan smoothing. Footprint availability depends on the basemap provider; roof detail cannot restore absent footprint data.
- Joystick / keyboard run simulation, explicit publication to a developer slot, normal scoring pipeline, idempotency, recorded operator and reason.
- Accurate combined account/device statistics, run inspection, auditable reversals, derived ownership rebuild and effective cloud configuration.
- The previous HUD, cyan curved trails, street illumination option and fog removal are preserved.

## Deploy configuration
Both Render services must use repository root (`rootDir: .`) because the admin imports shared map modules and the backend builds a source index for Scout. The Blueprint contains the exact commands:

Backend build: `python backend/scripts/build_codebase_context.py && pip install uv && cd backend && uv sync --frozen --no-dev`

Backend start: `cd backend && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Health check: `/health`

Admin build: `npm --prefix admin ci && npm --prefix admin run build`

Admin publish directory: `admin/dist`

Set AUTHENTICATED_ACCOUNTS_ENABLED=true, LOCAL_ACCOUNTS_ENABLED=false, DEVELOPER_MODE_ENABLED=true. Keep GROQ_API_KEY exclusively on the backend. VITE_API_URL points to https://run-backend-ngyo.onrender.com. Preserve the existing DATABASE_URL and ADMIN_OPERATIONS_TOKEN.

Migration 0012 was applied to the live Supabase project before the code push. Its four tables have RLS enabled and no anon/authenticated table grants. Existing player and territory data were preserved. Password hashes use scrypt; sessions are random opaque tokens, stored hashed server-side, revocable and scoped to app or console. Password changes invalidate other sessions. Console sessions last 12 hours; app sessions last 30 days. Mobile tokens are stored in the app's private SQLite metadata; web tokens use browser storage. Passwords are never stored by the clients.

The exact iPhone OAuth callback `run://auth/callback` was added to Supabase. A complete Google account consent/return test still requires the signed phone build. A web app host, if deployed later, needs its exact `/auth/callback` URL allowlisted; the admin console uses its separate named accounts.

## Local device distribution
`npm run ios:standalone` builds a Release app containing JavaScript, so launching it does not need Metro. The backend is hosted on Render. Free Apple signing still expires and must be renewed; this is separate from backend availability. The known profile expires September 10, 2026. USB connection and an unlocked NOVA may be needed to install; earlier wireless attempts failed.

## Checks and practical limits
Focused backend tests use real PostGIS inside rollback transactions. They cover account/session isolation, revocation, credential changes, note edit conflicts, member permissions, simulation idempotency and audit logging. TypeScript, app/admin lint, production admin build, and HUD/route/roof checks are also run.

Desktop synthetic timing tests are not a 45-minute physical-device battery/FPS audit. Basemap and Google OAuth UI need device review. Scout is rate-limited, retrieves relevant files rather than loading every file into each prompt, and can hit provider quotas. Secrets, environment files, generated assets and authentication/config implementation files are excluded from its source index.

Runs created by this build record their account-owned ledger ID. Upload refuses runs belonging to a different account. Older queued runs without ownership metadata remain saved for recovery; they are not silently reassigned to whichever account signs in next.
