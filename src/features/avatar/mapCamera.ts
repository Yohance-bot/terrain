/**
 * Rebuilding MapLibre's camera inside Filament.
 *
 * MapLibre exposes no projection matrix — only centre, zoom, bearing and pitch —
 * so a 3D object drawn over the map has to reconstruct the same camera from
 * those four numbers. Get it right and the avatar behaves like something
 * standing in the world: it leans as it moves off centre, foreshortens as the
 * map tilts, and swings around as the map turns. Get it wrong and it is a
 * sticker sliding over the screen, which is what a screen-space overlay is.
 *
 * Everything here works in **map pixels**, the unit MapLibre itself projects
 * into: at zero pitch, one map pixel on the ground is one point on screen. That
 * makes the whole thing checkable — see `projectGround`.
 */

/** MapLibre's tile size, and so the width of the world at zoom 0. */
const TILE_SIZE = 512;

/**
 * MapLibre's vertical field of view, 36.87°. Filament takes a focal length
 * rather than an angle, against a 35mm frame whose height is 24mm:
 * fov = 2·atan(12/f), so f = 12/tan(fov/2) = 36mm.
 */
export const MAP_FOV_RADIANS = 0.6435011087932844;
export const FOCAL_LENGTH_MM = 12 / Math.tan(MAP_FOV_RADIANS / 2);

/** World units are map pixels and the camera sits over a thousand of them from
 *  its target, so Filament's 0.1/100 defaults would clip the scene entirely. */
export const NEAR_PLANE = 1;
export const FAR_PLANE = 100_000;

export type Float3 = [number, number, number];

export type MapPose = {
  center: [number, number];
  zoom: number;
  /** Degrees clockwise from true north. */
  bearing: number;
  /** Degrees from straight down. */
  pitch: number;
};

const degrees = (value: number) => (value * Math.PI) / 180;

/** Web Mercator, normalised to 0..1. */
export function mercator(lon: number, lat: number): { x: number; y: number } {
  const clamped = Math.max(-85.051129, Math.min(85.051129, lat));
  const phi = degrees(clamped);
  return {
    x: (lon + 180) / 360,
    y: (1 - Math.log(Math.tan(phi) + 1 / Math.cos(phi)) / Math.PI) / 2,
  };
}

export function worldSize(zoom: number): number {
  return TILE_SIZE * Math.pow(2, zoom);
}

/**
 * Where a coordinate sits on the ground plane relative to the map centre.
 *
 * The frame matches the screen when the map is flat: +x is right, +z is toward
 * the viewer (down the screen), +y is up out of the ground.
 */
export function groundOffset(pose: MapPose, coordinate: [number, number]): { x: number; z: number } {
  const size = worldSize(pose.zoom);
  const centre = mercator(pose.center[0], pose.center[1]);
  const point = mercator(coordinate[0], coordinate[1]);
  // Mercator y grows southward, which is already the direction of +z.
  const east = (point.x - centre.x) * size;
  const south = (point.y - centre.y) * size;

  const bearing = degrees(pose.bearing);
  const cos = Math.cos(bearing);
  const sin = Math.sin(bearing);
  return {
    x: east * cos + south * sin,
    z: south * cos - east * sin,
  };
}

/**
 * How far the camera sits from the point it is looking at.
 *
 * This is the value that makes map pixels and screen points the same thing:
 * place the camera so the viewport exactly spans `viewportHeight` units at the
 * target, and an object that many units tall fills the screen.
 */
export function cameraDistance(viewportHeight: number): number {
  return (0.5 * viewportHeight) / Math.tan(MAP_FOV_RADIANS / 2);
}

/** The camera pulls back toward the viewer and rises as the map tilts. */
export function cameraEye(pitch: number, distance: number): Float3 {
  const angle = degrees(pitch);
  return [0, distance * Math.cos(angle), distance * Math.sin(angle)];
}

/**
 * Screen-up, expressed on the ground plane.
 *
 * At zero pitch the camera looks straight down, where a naive [0,1,0] would be
 * parallel to the view direction and give a degenerate basis.
 */
export function cameraUp(pitch: number): Float3 {
  const angle = degrees(pitch);
  return [0, Math.sin(angle), -Math.cos(angle)];
}

function subtract(a: Float3, b: Float3): Float3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

function cross(a: Float3, b: Float3): Float3 {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function normalise(v: Float3): Float3 {
  const length = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / length, v[1] / length, v[2] / length];
}

function dot(a: Float3, b: Float3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/**
 * Where a ground point lands on screen, under the camera this module builds.
 *
 * This duplicates what the GPU will do, which is the point: the map can be
 * asked the same question through `project()`, and the two answers must agree.
 * Any disagreement is the camera model being wrong, measurable in pixels
 * instead of argued about from a screenshot.
 */
export function projectGround(
  point: { x: number; z: number },
  pose: MapPose,
  viewport: { width: number; height: number },
): { x: number; y: number } | null {
  const distance = cameraDistance(viewport.height);
  const eye = cameraEye(pose.pitch, distance);
  const up = cameraUp(pose.pitch);
  const forward = normalise(subtract([0, 0, 0], eye));
  const right = normalise(cross(forward, up));
  const trueUp = cross(right, forward);

  const relative = subtract([point.x, 0, point.z], eye);
  const depth = dot(relative, forward);
  // Behind the camera, or on the horizon: there is no honest screen position.
  if (depth <= NEAR_PLANE) return null;

  const halfHeight = Math.tan(MAP_FOV_RADIANS / 2);
  const aspect = viewport.width / viewport.height;
  const ndcX = dot(relative, right) / (depth * halfHeight * aspect);
  const ndcY = dot(relative, trueUp) / (depth * halfHeight);
  return {
    x: (ndcX * 0.5 + 0.5) * viewport.width,
    y: (0.5 - ndcY * 0.5) * viewport.height,
  };
}

/** runner.glb faces +Z (toward the viewer). Compass north is -Z. */
export function avatarYaw(heading: number, mapBearing: number): number {
  return Math.PI - degrees(heading - mapBearing);
}
