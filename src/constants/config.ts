import Constants from 'expo-constants';

export const APP_NAME = 'run';

/**
 * Versioned OpenFreeMap Liberty fork. Keeping the style in the bundle prevents
 * upstream cartography changes from silently changing the game world.
 * Vector tiles, glyphs and sprites are still fetched from OpenFreeMap.
 */
const BROWSE_MAP_STYLE = require('../../assets/map/liberty-run.json');
export const MAP_STYLE = BROWSE_MAP_STYLE;

/** Required at all times by ODbL, with no exceptions. Never remove this. */
export const MAP_ATTRIBUTION = '© OpenStreetMap contributors · OpenFreeMap';

export const JAYANAGAR_CENTER: [number, number] = [77.5838, 12.925];
export const DEFAULT_ZOOM = 17.65;
export const DEFAULT_PITCH = 55;
export const DEFAULT_BEARING = -18;

/** Bump when `gameplay_territories.geojson` is republished to bust on-device cache. */
export const TERRITORY_DATA_VERSION = '16a6f8f18813';

/**
 * Cloud is the default in both development and standalone builds. Set
 * EXPO_PUBLIC_API_URL explicitly only when testing another backend.
 */
function resolveApiBaseUrl(): string {
  const explicit =
    process.env.EXPO_PUBLIC_API_URL?.trim() ??
    (Constants.expoConfig?.extra?.apiUrl as string | null | undefined)?.trim();
  if (explicit) {
    // Expo inlines EXPO_PUBLIC_* values into the native JavaScript bundle. A
    // public HTTPS tunnel or deployed API is therefore available to a Release
    // build even after the phone has left the development LAN.
    return explicit.replace(/\/$/, '');
  }

  return 'https://run-backend-ngyo.onrender.com';
}

export const API_BASE_URL = resolveApiBaseUrl();

/** Explicit opt-in for the on-device virtual-run controls used during POC QA. */
export const ENABLE_SIMULATION = process.env.EXPO_PUBLIC_ENABLE_SIMULATOR === 'true';

/** Discard fixes worse than this before they reach the route. Mirrors the server. */
export const MAX_ACCURACY_M = 50;

/** How often the recorder asks for a fix while a run is in progress. */
export const GPS_INTERVAL_MS = 1000;

// ── GPS Cleaning Pipeline Constants ─────────────────────────────────────────
// These drive gpsClean.ts. Adjust here to tune without touching algorithm code.

/**
 * Tighter accuracy cutoff applied by the cleaning pipeline (vs MAX_ACCURACY_M
 * which is the loose raw-sample gate). Points worse than this are dropped from
 * cleanPath but preserved in the raw SQLite log.
 */
export const GPS_ACCURACY_CUTOFF_M = 25;

/**
 * Maximum plausible distance (metres) a runner can travel between consecutive
 * GPS fixes. A fix that exceeds this from the last accepted clean point is
 * treated as a GPS teleport/spike and silently dropped from cleanPath.
 * At 1 Hz sampling, a sprinter runs ~10 m/s → 10 m/fix. 80 m is very generous.
 */
export const GPS_SPIKE_MAX_JUMP_M = 80;

/**
 * Exponential Moving Average smoothing factor applied to lat/lon after spike
 * rejection. Range (0, 1]: 1 = no smoothing, 0.3 = strong smoothing.
 * 0.4 gives light jitter reduction while preserving genuine direction changes.
 */
export const GPS_EMA_ALPHA = 0.4;

/**
 * Ramer-Douglas-Peucker epsilon (metres). Collinear GPS points closer than this
 * to the chord between their neighbours are collapsed. 4 m removes GPS jitter
 * on straight roads while keeping corners intact.
 */
export const GPS_RDP_EPSILON_M = 4;

/**
 * Minimum bearing change (degrees) between consecutive segments to classify the
 * middle point as a genuine turn vertex. Below this it's treated as straight-road
 * noise and left to EMA/RDP to handle.
 */
export const GPS_TURN_ANGLE_DEG = 25;

/**
 * Radius (metres) within which local chord smoothing is applied around each
 * detected turn apex. Softens sharp GPS corners without touching straight segments.
 */
export const GPS_TURN_SMOOTH_RADIUS_M = 10;

// ── POC Territory Capture Constants ───────────────────────────────────────
// Tuned deliberately as visible POC rules rather than hidden magic numbers.
export const LOOP_MIN_DISTANCE_M = 350;
export const LOOP_CLOSURE_DISTANCE_M = 45;
export const LOOP_MIN_AREA_M2 = 1_200;
export const TRAVERSAL_GRID_METRES = 24;
export const TRAVERSAL_MAX_SEGMENT_METRES = 32;
