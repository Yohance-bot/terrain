# Map world and trail display — 2026-09-08

This supersedes the fog and flat-map descriptions in the original HUD notes.

## Visible changes

- Fog of war, its tracking/persistence writes, settings and map anchor are removed.
  Old exploration metadata is unused; no run or ownership data was deleted.
- Cream local roads, gold avenues, mint paths, teal borders and distinct center
  markings replace the lighting layer's former single road color. Shared width
  tokens keep the highlighted street surface the same width as the basemap.
- The default view is zoom 17.65 at 55 degrees, with a close, gently reactive run
  camera. Reduced motion/battery saver retain a calmer north-up view.
- Buildings remain visible during runs. Roof terraces, pavilions, stepped roofs,
  garden decks and canopies sit on actual OpenMapTiles footprints. They are
  stylized scenery, not claims about the architecture of real buildings.
- Every suitable loaded footprint in the viewport and its small guard band gets a
  rooftop feature, including buildings inside territory areas. The old nearest-90
  cutoff is gone. Nearby buildings get several tiers; farther/economy buildings
  retain one raised ornament. Concave and courtyard footprints receive an
  inscribed pavilion that avoids holes and boundaries. Invalid or sub-metre
  geometry retains the native roof rim rather than emitting broken polygons.
  At zooms below 16, flat footprints replace the 3D scene.
- Both run-trail modes use cyan, independent of ownership/player colors. GPS
  trails have rounded quadratic corners with an 8 m maximum corner cut; matched
  streets use a smaller 2 m cut to remain on the street. Curves do not overshoot
  their corner triangle, cross GPS gaps, move endpoints or change recorded data.

## Choosing the trail

Use **Settings → Run trail** or the map's trail button during a run:

- **Light up streets** (default): color only the traversed part of the loaded
  street geometry, including real junction vertices and individual carriageways.
  Ambiguous/off-road/unavailable-tile sections show a dotted cyan GPS trace.
- **GPS trail**: show the accepted recorded path with visual corner rounding,
  including parks and shortcuts. This path is not snapped to the road network.

The choice is saved locally as `hud.route-display.v1`. Matching and smoothing
are rendering operations. GPS samples, distance, submission and ownership rules
are unchanged.

## Performance and verification

Scenery uses native extrusions and local vector-tile queries, with no extra map
provider or GPS upload. Query batches run at most every 3 seconds (6 in economy)
and heavy geometry is refreshed only when the camera changes or after 15 seconds
stationary. A single batch is in flight. Roof placement plans are cached for up to
6,000 footprints. Viewport filtering controls coverage; LOD reduces tier count
instead of leaving distant buildings undecorated.

The road cache is limited to 1,800 lines / 12,000 vertices. Matching uses a cached
spatial index, caps output to 3,072 vertices and never bridges unobserved sections.
Rounded GPS trails cap added geometry at 4,608 vertices (2,304 in economy).
Street rounding uses a 6,144-vertex ceiling; unmatched trace rounding uses 4,608.
Offscreen/background presentation queries stop.

Typecheck, lint, full MapLibre style validation, timestamp tests and production
module regressions pass. Tests cover partial road lighting, junctions, parallel
street ambiguity, tile/off-road fallback, GPS gaps, curve shape/budgets,
MultiPolygon buildings, complete coverage beyond 90 buildings, and roof placement
on concave/courtyard footprints. Native iOS simulator review also verified both
trail modes, a persisted GPS-trail preference, roof details and carriageway
alignment using an isolated localhost fixture. Temporary QA controls were removed;
no synthetic run was submitted to the real backend. A subsequent night-theme
review verified the expanded roof coverage and the cyan curved GPS trail on
the simulator. The operating-system status bar now follows the map route
declaratively, fixing its dark-on-dark text.

Physical-device battery, thermal and motion tuning, Android rendering and a fresh
native build remain unverified. No native dependency was added. Follow the
45-minute device protocol in [the audit](10_HUD_AUDIT.md).
