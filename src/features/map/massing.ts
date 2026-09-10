/**
 * Architectural massing for real building footprints.
 *
 * Everything here works in metres in a frame local to one building, so an
 * "inset by 1.4" is a real 1.4 m setback rather than a percentage that warps
 * long or L-shaped footprints. Volumes are emitted as extrusion shapes that are
 * always carved out of the actual footprint — never scaled outward — so a roof
 * can never bridge an L-shaped notch or cover a courtyard.
 */

export type P = [number, number];
export type Ring = P[];
/** Outer ring first (counter-clockwise); any further rings are holes. */
export type Shape = Ring[];
/** `accent` carries the territory hue on the thin roof edge; `garden`, `panel`
 * and `door` are real materials and never take it. */
export type Tone = 'accent' | 'aqua' | 'clay' | 'slate' | 'garden' | 'cream' | 'panel' | 'door';
export type Archetype =
  | 'house' | 'terrace' | 'residential' | 'apartment'
  | 'commercial' | 'institutional' | 'office' | 'warehouse' | 'landmark';

/** tier 0 survives every level of detail; 3 is drawn only right beside the player. */
export type Volume = { shape: Shape; base: number; top: number; tone: Tone; tier: 0 | 1 | 2 | 3 };

export type Footprint = {
  shape: Shape;
  area: number;
  axis: P;
  length: number;
  width: number;
  /** area / oriented bounding box — 1 is a perfect rectangle. */
  rectangularity: number;
  vertices: number;
  solid: boolean;
};

export const ARCHETYPES: Archetype[] = ['house', 'terrace', 'residential', 'apartment', 'commercial', 'institutional', 'office', 'warehouse', 'landmark'];

function ringArea(r: Ring): number {
  let a = 0;
  for (let i = 0; i < r.length; i++) {
    const p = r[i]!, q = r[(i + 1) % r.length]!;
    a += p[0] * q[1] - q[0] * p[1];
  }
  return a / 2;
}
const reverse = (r: Ring): Ring => [...r].reverse();
const asCCW = (r: Ring): Ring => (ringArea(r) < 0 ? reverse(r) : r);

function unit(from: P, to: P): P | null {
  const dx = to[0] - from[0], dy = to[1] - from[1];
  const len = Math.hypot(dx, dy);
  return len < 1e-7 ? null : [dx / len, dy / len];
}

/**
 * Miter offset of a closed outline. `d > 0` moves every edge inward.
 * Returns null when the outline folds through itself, which is the signal for
 * callers to fall back to a simpler treatment instead of emitting a knot.
 */
export function offsetRing(ring: Ring, d: number): Ring | null {
  const n = ring.length;
  if (n < 3) return null;
  const wasCW = ringArea(ring) < 0;
  const src = wasCW ? reverse(ring) : ring;
  const out: Ring = [];
  for (let i = 0; i < n; i++) {
    const prev = src[(i - 1 + n) % n]!, cur = src[i]!, next = src[(i + 1) % n]!;
    const e1 = unit(prev, cur), e2 = unit(cur, next);
    if (!e1 || !e2) return null;
    const n1: P = [-e1[1], e1[0]], n2: P = [-e2[1], e2[0]];
    // Intersection of the two offset edges. The miter runs away to infinity at a
    // spike, so clamp it and let the edge check below reject a real collapse.
    const t = d / Math.max(0.35, 1 + n1[0] * n2[0] + n1[1] * n2[1]);
    out.push([cur[0] + t * (n1[0] + n2[0]), cur[1] + t * (n1[1] + n2[1])]);
  }
  for (let i = 0; i < n; i++) {
    const a0 = src[i]!, b0 = src[(i + 1) % n]!, a1 = out[i]!, b1 = out[(i + 1) % n]!;
    // A reversed edge means that side of the building has been consumed.
    if ((b0[0] - a0[0]) * (b1[0] - a1[0]) + (b0[1] - a0[1]) * (b1[1] - a1[1]) <= 0) return null;
  }
  const before = ringArea(src), after = ringArea(out);
  if (after <= 0) return null;
  if (d > 0 && (after >= before || after < before * 0.05)) return null;
  if (d < 0 && after <= before) return null;
  return wasCW ? reverse(out) : out;
}

/** Insets the outline and grows any courtyard by the same distance. */
export function offsetShape(shape: Shape, d: number): Shape | null {
  const outer = offsetRing(shape[0]!, d);
  if (!outer) return null;
  const holes: Ring[] = [];
  for (let i = 1; i < shape.length; i++) {
    const grown = offsetRing(shape[i]!, -d);
    if (!grown) return null;
    holes.push(grown);
  }
  return [outer, ...holes];
}

/** Keeps the half of `ring` on the positive side of the plane through `origin`. */
export function clipHalfPlane(ring: Ring, origin: P, normal: P): Ring | null {
  const out: Ring = [];
  const side = (p: P) => (p[0] - origin[0]) * normal[0] + (p[1] - origin[1]) * normal[1];
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
    const da = side(a), db = side(b);
    if (da >= 0) out.push(a);
    if ((da >= 0) !== (db >= 0)) {
      const t = da / (da - db);
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
  }
  return out.length >= 3 ? out : null;
}

export function extentAlong(ring: Ring, axis: P): { min: number; max: number } {
  let min = Infinity, max = -Infinity;
  for (const p of ring) {
    const t = p[0] * axis[0] + p[1] * axis[1];
    if (t < min) min = t;
    if (t > max) max = t;
  }
  return { min, max };
}

/** Takes the slab of `ring` between two fractions of its extent along `axis`. */
export function sliceAlong(ring: Ring, axis: P, from: number, to: number): Ring | null {
  const { min, max } = extentAlong(ring, axis);
  const span = max - min;
  if (!(span > 0.5)) return null;
  let out: Ring | null = ring;
  if (from > 0.001) {
    const t = min + span * from;
    out = clipHalfPlane(out, [axis[0] * t, axis[1] * t], axis);
  }
  if (out && to < 0.999) {
    const t = min + span * to;
    out = clipHalfPlane(out, [axis[0] * t, axis[1] * t], [-axis[0], -axis[1]]);
  }
  return out && Math.abs(ringArea(out)) > 1 ? out : null;
}

/** Length-weighted principal axis, so one detailed façade cannot skew it. */
export function principalAxis(ring: Ring): P {
  let cx = 0, cy = 0, w = 0;
  const mids: { p: P; w: number }[] = [];
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (len < 1e-6) continue;
    const m: P = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    mids.push({ p: m, w: len });
    cx += m[0] * len; cy += m[1] * len; w += len;
  }
  if (!w) return [1, 0];
  cx /= w; cy /= w;
  let sxx = 0, syy = 0, sxy = 0;
  for (const m of mids) {
    const dx = m.p[0] - cx, dy = m.p[1] - cy;
    sxx += m.w * dx * dx; syy += m.w * dy * dy; sxy += m.w * dx * dy;
  }
  const theta = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  return [Math.cos(theta), Math.sin(theta)];
}

export function describeFootprint(shape: Shape): Footprint | null {
  const outer = shape[0];
  if (!outer || outer.length < 3) return null;
  const area = ringArea(outer);
  if (!(area > 1)) return null;
  // A hole as large as the building is malformed data, not a courtyard.
  for (let i = 1; i < shape.length; i++) {
    const hole = Math.abs(ringArea(shape[i]!));
    if (!(hole > 0.5) || hole >= area * 0.85) return null;
  }
  const axis = principalAxis(outer);
  const cross: P = [-axis[1], axis[0]];
  const along = extentAlong(outer, axis), across = extentAlong(outer, cross);
  const length = along.max - along.min, width = across.max - across.min;
  if (!(length > 1) || !(width > 1)) return null;
  return {
    shape,
    area,
    axis: length >= width ? axis : cross,
    length: Math.max(length, width),
    width: Math.min(length, width),
    rectangularity: area / (length * width),
    vertices: outer.length,
    solid: shape.length === 1,
  };
}

export function classify(fp: Footprint, height: number): Archetype {
  const { area, vertices, rectangularity } = fp;
  const elongation = fp.length / Math.max(1, fp.width);
  if (area >= 2600 && height >= 17) return 'landmark';
  if (height >= 21) return 'office';
  // A long low shed is a shed however large, so this precedes the area rules.
  if (area >= 450 && elongation >= 2 && height <= 12) return 'warehouse';
  if (area >= 1200 || (area >= 700 && vertices >= 12)) return 'institutional';
  if (area >= 600 && height <= 13 && rectangularity >= 0.62) return 'commercial';
  if (area >= 350) return 'apartment';
  if (area >= 60 && elongation >= 1.9) return 'terrace';
  if (area >= 140) return 'residential';
  return 'house';
}

/**
 * Composes one building out of connected volumes. `volumes[0]` is the signature
 * mass — the single volume worth drawing when the building is far away or the
 * device is in economy mode — and later entries add architecture as it nears.
 */
export function massing(fp: Footprint, height: number, deck: number, seed: number, archetype: Archetype): Volume[] {
  const R = height + deck;
  const { shape, axis, solid, width } = fp;
  const cross: P = [-axis[1], axis[0]];
  const tone = (['aqua', 'clay', 'slate', 'cream'] as const)[seed % 4]!;
  const pick = (n: number) => Math.floor(seed / 7) % n;
  // Storey heights vary per building so a street of identical footprints still
  // has a skyline. Only added volumes move; the footprint itself is untouched.
  // The band sits below 1 on purpose: rooftop structures read better as low
  // additions to a building than as another storey stacked on top of it.
  const j = 0.72 + (seed % 7) * 0.04;
  const out: Volume[] = [];

  const add = (s: Shape | null, base: number, top: number, t: Tone, tier: 0 | 1 | 2 | 3) => {
    if (s && s[0] && s[0].length >= 3 && top > base + 0.02) out.push({ shape: s, base, top, tone: t, tier });
  };
  /** A parapet: the wall band around the roof edge, leaving the deck recessed. */
  const parapet = (d: number): Shape | null => {
    const i = offsetShape(shape, d);
    return i && i[0] ? [shape[0]!, reverse(i[0]), ...i.slice(1)] : null;
  };
  const inset = (d: number): Shape | null => offsetShape(shape, d);
  /** A slab of the inset footprint between two fractions along an axis. */
  const slab = (from: number, to: number, along: P, d: number): Shape | null => {
    if (!solid) return null;
    const src = d > 0 ? offsetShape(shape, d)?.[0] : shape[0];
    if (!src) return null;
    const cut = sliceAlong(src, along, from, to);
    return cut ? [cut] : null;
  };
  /** Enough room to inset by `d` and still leave a usable roof. */
  const roomy = (d: number) => width > d * 2.6;
  /** A small rectangular area of the roof, for objects that sit on top of it. */
  const patch = (u0: number, u1: number, v0: number, v1: number, d: number): Shape | null => {
    if (!solid) return null;
    const src = d > 0 ? offsetShape(shape, d)?.[0] : shape[0];
    const lengthwise = src ? sliceAlong(src, axis, u0, u1) : null;
    const both = lengthwise ? sliceAlong(lengthwise, cross, v0, v1) : null;
    return both ? [both] : null;
  };
  /** True when an upper storey already occupies the roof, leaving no deck. */
  let coversRoof = false;

  switch (archetype) {
    case 'house': {
      add(parapet(0.5), R, R + 0.42, 'accent', 0);
      const variant = pick(4);
      if (variant === 0) {
        add(slab(0, 0.34, axis, 0.85), R, R + 0.85 * j, tone, 1);
      } else if (variant === 1 && roomy(1.1)) {
        add(inset(1.1), R, R + 0.1, 'garden', 1);
      } else if (variant === 2) {
        add(slab(0.66, 1, cross, 0.9), R, R + 0.8 * j, tone, 1);
      }
      // variant 3 stays bare: a plain parapet roof is part of the vocabulary.
      break;
    }
    case 'terrace': {
      const end = pick(3);
      if (end === 2) {
        add(inset(0.8), R, R + 1.0 * j, tone, 0);
        add(parapet(0.4), R, R + 0.45, 'accent', 0);
        coversRoof = true;
      } else {
        add(end === 0 ? slab(0, 0.46, cross, 0.45) : slab(0.54, 1, cross, 0.45), R, R + 1.05 * j, tone, 0);
        add(parapet(0.45), R, R + 0.48, 'accent', 0);
      }
      break;
    }
    case 'residential': {
      const variant = pick(3);
      if (variant === 0 && roomy(1.5)) {
        add(inset(1.5), R, R + 1.5 * j, tone, 0);
        add(parapet(0.5), R, R + 0.5, 'accent', 0);
        const crown = offsetShape(shape, 1.5);
        if (crown?.[0]) {
          const lip = offsetRing(crown[0], 0.5);
          if (lip) add([crown[0], reverse(lip)], R + 1.5 * j, R + 1.85 * j, 'cream', 1);
        }
        coversRoof = true;
      } else if (variant === 1) {
        add(slab(0, 0.44, axis, 0.4), R, R + 1.6 * j, tone, 0);
        add(parapet(0.5), R, R + 0.5, 'accent', 0);
      } else {
        add(slab(0.5, 1, cross, 0.4), R, R + 1.45 * j, tone, 0);
        add(parapet(0.55), R, R + 0.52, 'accent', 0);
      }
      break;
    }
    case 'apartment': {
      const variant = pick(3);
      add(inset(1.0), R, R + 1.8 * j, tone, 0);
      add(parapet(0.55), R, R + 0.55, 'accent', 0);
      coversRoof = true;
      if (variant === 0) {
        add(slab(0.18, 0.78, axis, 3.1), R + 1.8 * j, R + 3.3 * j, tone, 1);
      } else if (variant === 1) {
        add(slab(0.12, 0.6, cross, 3.1), R + 1.8 * j, R + 3.6 * j, tone, 1);
      } else {
        add(inset(3.4), R + 1.8 * j, R + 3.1 * j, tone, 1);
        add(slab(0.66, 0.92, axis, 3.6), R + 3.1 * j, R + 3.9 * j, 'slate', 2);
      }
      break;
    }
    case 'commercial': {
      const variant = pick(3);
      if (variant === 0) {
        add(slab(0.28, 0.72, cross, 1.4), R, R + 0.9 * j, tone, 0);
        add(parapet(1.1), R, R + 0.7, 'accent', 0);
      } else if (variant === 1) {
        add(slab(0.22, 0.68, axis, 1.4), R, R + 1.05 * j, tone, 0);
        add(parapet(0.7), R, R + 0.52, 'accent', 0);
      } else {
        add(inset(1.8), R, R + 1.25 * j, tone, 0);
        add(parapet(1.3), R, R + 0.75, 'accent', 0);
        coversRoof = true;
      }
      break;
    }
    case 'institutional': {
      if (solid) {
        const split = pick(2) === 0 ? axis : cross;
        add(slab(0, 0.5, split, 0.6), R, R + 1.8 * j, tone, 0);
        add(slab(0.5, 1, split, 0.6), R, R + 1.0 * j, 'cream', 0);
        add(parapet(0.8), R, R + 0.55, 'accent', 1);
      } else {
        // Already has a courtyard: ring the void instead of inventing wings.
        add(parapet(0.85), R, R + 0.6, 'accent', 0);
        add(inset(2.4), R, R + 1.4 * j, tone, 1);
      }
      break;
    }
    case 'office': {
      add(inset(1.2), R, R + 2.4 * j, tone, 0);
      add(parapet(0.6), R, R + 0.5, 'accent', 0);
      coversRoof = true;
      const step = offsetShape(shape, 3.4);
      if (step?.[0] && pick(2) === 0) {
        add(step, R + 2.4 * j, R + 4.6 * j, tone, 1);
        const crown = offsetRing(step[0], 1.1);
        if (crown) add([step[0], reverse(crown)], R + 4.6 * j, R + 5.2 * j, 'cream', 2);
      } else {
        add(slab(0.14, 0.66, axis, 2.6), R + 2.4 * j, R + 5.2 * j, tone, 1);
      }
      break;
    }
    case 'warehouse': {
      // Bands stepping up and back down read as a pitched roof from above.
      const ridge = pick(2) === 0 ? cross : axis;
      add(slab(0.3, 0.7, ridge, 0.5), R, R + 1.25 * j, tone, 0);
      add(slab(0, 0.3, ridge, 0.5), R, R + 0.6 * j, tone, 1);
      add(slab(0.7, 1, ridge, 0.5), R, R + 0.6 * j, tone, 1);
      add(parapet(0.35), R, R + 0.3, 'accent', 2);
      coversRoof = true;
      break;
    }
    case 'landmark': {
      add(inset(1.4), R, R + 2.8 * j, tone, 0);
      add(parapet(0.7), R, R + 0.65, 'accent', 0);
      coversRoof = true;
      const tower = offsetShape(shape, 4.2);
      if (tower?.[0]) {
        add(tower, R + 2.8 * j, R + 5.6 * j, tone, 1);
        const cap = offsetRing(tower[0], 1.3);
        if (cap) add([tower[0], reverse(cap)], R + 5.6 * j, R + 6.4 * j, 'cream', 1);
      }
      break;
    }
  }

  // Rooftop objects, on buildings that still have an open deck. These are the
  // small flat things a real terrace carries — never another storey-sized box.
  if (!coversRoof) {
    switch (seed % 5) {
      case 0:
        add(patch(0.16, 0.5, 0.22, 0.58, 1.1), R, R + 0.16, 'panel', 2);
        break;
      case 1:
        add(patch(0.68, 0.86, 0.22, 0.44, 1.1), R, R + 0.85, 'slate', 2);
        break;
      case 2:
        add(patch(0.52, 0.9, 0.46, 0.86, 1.1), R, R + 0.1, 'garden', 2);
        break;
      case 3:
        add(patch(0.18, 0.5, 0.24, 0.52, 1.1), R, R + 0.16, 'panel', 2);
        add(patch(0.66, 0.84, 0.6, 0.82, 1.1), R, R + 0.8, 'slate', 2);
        break;
      // case 4 leaves the deck clear.
    }
  }

  // Façade openings. These sit proud of the wall so they read against a flat
  // extrusion, which is only affordable on the buildings nearest the player —
  // everything further away keeps a clean façade.
  const wall = shape[0]!;
  const edges = wall.map((a, i) => {
    const b = wall[(i + 1) % wall.length]!;
    return { a, b, length: Math.hypot(b[0] - a[0], b[1] - a[1]) };
  }).filter(e => e.length >= 4).sort((p, q) => q.length - p.length).slice(0, 2);

  const opening = (e: { a: P; b: P; length: number }, from: number, to: number, base: number, top: number, t: Tone, depth: number) => {
    const dx = (e.b[0] - e.a[0]) / e.length, dy = (e.b[1] - e.a[1]) / e.length;
    // Outward normal of a counter-clockwise ring.
    const nx = dy * depth, ny = -dx * depth;
    const p0: P = [e.a[0] + dx * from, e.a[1] + dy * from];
    const p1: P = [e.a[0] + dx * to, e.a[1] + dy * to];
    add([[p0, p1, [p1[0] + nx, p1[1] + ny], [p0[0] + nx, p0[1] + ny]]], base, top, t, 3);
  };

  // One opening, on some buildings rather than on every one. A full grid of
  // windows is a lot of geometry for something glimpsed in passing, and it read
  // as a repeating pattern rather than as a building. Which buildings get one
  // is fixed by the footprint's seed, so a street never flickers between frames.
  const facade = seed % 5;
  const edge = edges[Math.floor(seed / 13) % Math.max(1, edges.length)];
  if (edge && facade < 3) {
    const storeys = Math.min(2, Math.max(1, Math.floor(height / 3.2)));
    const sill = (Math.floor(seed / 3) % storeys) * 3.2 + 1.15;
    // A flush pane is glass; a box projects far enough to catch light on its
    // side, the way a bay window or a balcony does.
    const box = facade === 2;
    const head = sill + (box ? 1.4 : 1.25);
    if (head <= height - 0.35) {
      const half = (box ? 1.0 : 1.3) / 2;
      // Positive arithmetic throughout: `seed` runs past 2^31, and a signed
      // shift on it turns negative, which puts the pane off the end of the wall.
      const along = edge.length * (0.3 + (Math.floor(seed / 32) % 40) / 100);
      // Whatever the seed says, the pane stays on the wall it belongs to.
      const middle = Math.min(edge.length - half - 0.2, Math.max(half + 0.2, along));
      opening(edge, middle - half, middle + half, sill, head, 'panel', box ? 0.3 : 0.1);
    }
  }
  const entrance = edges[0];
  if (entrance && entrance.length >= 5 && height > 3) {
    const middle = entrance.length * 0.5;
    opening(entrance, middle - 0.65, middle + 0.65, 0, Math.min(2.25, height - 0.4), 'door', 0.14);
  }

  // Every building must own at least one drawable volume, whatever its shape.
  // Falling back to the raw footprint must still leave courtyards uncovered.
  if (!out.length) add(parapet(0.45) ?? [asCCW(shape[0]!), ...shape.slice(1)], R, R + 0.55, 'cream', 0);
  if (out.length && out[0]!.tier !== 0) out[0]!.tier = 0;
  return out;
}
