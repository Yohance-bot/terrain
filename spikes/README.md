# Rendering spikes

Kept out of `app/` on purpose: anything in `app/` becomes an expo-router route
and ships in the bundle. These are throwaway experiments, not app screens.

- `filament-spike.tsx` — the original probe: can react-native-filament load and
  render a GLB at all. Answered yes.
- `filament-map-test.tsx` — Filament layered over a live MapLibre map, with a
  scripted camera flight and instrumentation.

## What the map test found, on an iPhone 16 (A18), 11 Sep 2026

- Both renderers coexist. Filament resolved the Metal backend and ran its own
  choreographer while MapLibre animated underneath. No crash.
- Transparent rendering works: the map stays fully legible under the layer.
- ~50 fps during an active pan, with a single cube and nothing else drawn.
- Anchor drift between two `project()` calls: p50 0.0px, p95 0.0px, max 43.6px.
  Normally tight, occasionally a large lurch.
- MapLibre exposes no projection matrix and no synchronous camera read, so any
  overlay is at least one async bridge hop stale.
- Depth/occlusion against extruded buildings is not possible this way: two
  renderers, two depth buffers, composited as stacked views.

Conclusion: viable for markers floating above the map; not for 3D that must sit
among the buildings. That would need a custom MapLibre layer rendering into the
map's own Metal context.
