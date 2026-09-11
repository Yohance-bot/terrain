# Player avatar

`runner.glb` — the rounded white robot from the character reference, with
Baymax-style jointed legs.

Built procedurally in Blender rather than sculpted, so the budgets that matter
when compositing over a live MapLibre map are held deliberately:

| | |
|---|---|
| Triangles | 6,176 |
| Materials | 3 (body, visor, emissive eyes) |
| Textures | none — flat colour plus emission |
| File size | 163 KB |

Draw calls, not triangles, are what cost when a second renderer is layered over
the map: three materials is the point of the design. For comparison, the EVE
model that was considered first had 54 material slots and 36,486 triangles.

## Animation

Two clips, each covering all nine moving nodes:

- **`Run`** — 0.71s loop. Thighs swing, knees bend through the carry, arms
  counter-swing, body bobs twice per stride, with a 9 degree forward lean.
- **`Idle`** — 2.04s loop. Slow hover and a little arm drift.

Both clips animate the *same* nine nodes on purpose. The exporter drops channels
whose values never change, which silently left the legs out of `Idle` and would
have stranded a thigh mid-stride when switching out of `Run`. The legs carry a
sub-degree drift so the channels survive.

Nodes: `Avatar_Root`, `Arm_L/R`, `Thigh_L/R`, `Shin_L/R`, `Foot_L/R`.
`Avatar_Root` carries the bob, so the app can place the character by moving the
root without disturbing the pose. The feet rest at z=0.
