03 — Map and Territory Pipeline

Status: Stable Design (v4)

Revision Notes (v3 → v4)

GPS-to-territory matching architecture formalised as a pipeline with explicit stages.
H3 spatial indexing promoted to a dedicated section; clarified that H3 is an indexing layer only and never player-visible.
Overture Places integration added as a future partner layer — not a launch dependency.
Territory generation safety pass and exclusion pass added as required pre-publish steps.
Bengaluru data-quality validation step added before territory generation.
Territory balancing simulator added as a pre-launch recommendation.
Stale influence-cap reference removed from GeoJSON section.

Revision Notes (v2 → v3)

Territory coverage is decided: territories exhaustively tile the city. Added as its own section with topology rules.
Territory sizing philosophy added — a normal run should interact with roughly one to two territories, and influence capacity scales with runnable path length rather than area.
Boundaries now have a stated rule: follow separators people do not run along. This is the primary structural defence against border-hugging.
Territory versioning promoted from a note at the bottom of the document into a proper section, with the full published record shape.
Projection and measurement rule added — a silent correctness trap that would otherwise be discovered late.
Anti-cheat scope boundary now points at `05_ANTICHEAT_AND_TRUST`, which exists.
Removed unincorporated review notes and stale influence-cap numbers from the tail of the document. Caps as described there no longer exist; see `01_CORE_MECHANICS` v2.
`03_MAP_PIPELINE_DUE_DILIGENCE` is referenced throughout but has not been written. Marked as such rather than left as a dangling reference.

Revision Notes (v1 → v2)

This version closes six gaps found in review of v1:

The pipeline diagram incorrectly showed Overture Maps flowing through GeoFabrik. They are separate, parallel ingestion paths — fixed below.
Licensing (ODbL attribution) was entirely absent despite this being the canonical rendering reference. Added as its own section and added to Layer Order.
GPS submission and anti-cheat were named as in-scope in the original Purpose section but never addressed. This version explicitly scopes them out to a dedicated future document rather than leaving the gap silent.
Overture vs. OpenStreetMap was described as an open either/or. It isn't — Overture is the primary source, GeoFabrik/raw OSM is the fallback. Wording corrected.
Static territory shape data and dynamic ownership/influence data were never distinguished at the API/render level. Added as an explicit split with a concrete data-flow.
Two known open problems are now named explicitly rather than left undiscovered: territory boundary regeneration invalidating historical influence, and line-based (corridor) territories needing different generation logic than area-based ones.

Related document: 03_MAP_PIPELINE_DUE_DILIGENCE (not yet written) is to cover provider comparison, cost projections, and full licensing rationale. This document covers architecture — how the system actually works, not why each vendor was chosen.

Purpose

This document defines the complete spatial architecture of the project.

It explains where geographic data comes from, how it becomes game territories, how those territories are stored, how static shape data and live gameplay state combine at render time, and how everything is ultimately rendered inside the mobile application.

This document is the canonical reference for all future work involving maps, territories, rendering, or spatial databases.

Explicitly out of scope: GPS route validation and anti-cheat. This pipeline assumes route data reaching it has already been validated — see the scope boundary section below.

The architecture described here is intended to scale from a single-city prototype to millions of players worldwide without requiring fundamental redesign.

Core Philosophy

The application does not own the map.

It owns the game world.

Roads, parks, lakes, neighbourhoods, and buildings exist only to provide a believable foundation on top of which gameplay takes place.

The game's real assets are:

Territories
Checkpoints
Events
Player influence
Ownership
Historical activity
Game metadata

These systems belong entirely to our backend and are never tied to any specific map provider.

The map itself is simply a visualization layer.

This separation is intentional and is one of the core architectural principles of the project.

High-Level Pipeline
   OpenStreetMap                    Overture Maps
   (via GeoFabrik .osm.pbf)         (via Overture CLI / cloud releases)
        │                                  │
        └────────────────┬─────────────────┘
                          ▼
                  PostGIS Database
                          │
                          ▼
          AI Territory Generation Pipeline
                          │
                          ▼
               Human Review & Approval
                          │
                          ▼
             Production Territory Data
              (static shapes + metadata)
                          │
                          ▼
                  FastAPI Backend
                  │                │
                  ▼                ▼
     GeoJSON Territory Shapes   Live Territory State
     (rarely changes, cached)   (ownership, influence — polled)
                  │                │
                  └───────┬────────┘
                          ▼
              React Native Mobile App
           (joins shapes + state client-side)
                          │
                          ▼
                 MapLibre Renderer
                          │
                          ▼
   OpenFreeMap (development) → Self-Hosted PMTiles (production)

OpenStreetMap and Overture Maps are two independent ingestion paths, not one shared step — they are distributed differently (GeoFabrik .osm.pbf extracts vs. Overture's own CLI/cloud releases) and both land in PostGIS separately. Each remaining stage has a single responsibility, and no stage should perform the responsibilities of another.

Geographic Data

The project uses OpenStreetMap as its foundational geographic data source, accessed through two parallel routes: raw extracts via GeoFabrik, and cleaned exports via Overture Maps.

OpenStreetMap contains the real-world geometry of roads, parks, lakes, footpaths, neighbourhoods, buildings, rivers, campuses, sports grounds, and thousands of other geographic features.

The application never modifies OpenStreetMap itself. It imports geographic information into its own database and builds gameplay systems entirely on top of that imported copy.

Overture Maps

Overture Maps is the preferred source where coverage and classification quality are superior. OpenStreetMap remains the fallback and foundational. Its Base and Divisions themes provide land use (including a clean park classification), water features, and neighbourhood-level administrative boundaries — already standardized, where raw OSM tagging for the same features is often inconsistent.

Raw OpenStreetMap, via GeoFabrik, is the fallback: used wherever Overture's export is missing or incomplete for a specific feature in Bengaluru. The pipeline is designed so either source can be imported into the same PostGIS schema without affecting anything downstream.

Full comparison and rationale: see 03_MAP_PIPELINE_DUE_DILIGENCE.

Overture Places — Future Partner Layer

Not a launch dependency. Documented here so the spatial model can accommodate it when the commerce and social layers arrive.

Overture Places can provide structured point-of-interest data for:

cafés and restaurants
running stores and sports retailers
gyms and fitness studios
juice shops and health-food outlets
other local businesses with a physical presence

Potential uses, all future:

checkpoint locations and sponsored stops
sponsor discovery and merchant partnerships
territory enrichment — a named business inside a territory, not a replacement for the territory itself
local event anchoring

This layer sits above the territory polygon model. Territories remain the gameplay unit; Places are optional metadata attached to points inside them. Players interact with named places — Cubbon Park, Lalbagh, Koramangala — never with hexagons or POI identifiers.

Phase: future monetisation and social layer. See `07_ROADMAP_AND_LAUNCH`.

GeoFabrik

The application never depends on the public Overpass API for production traffic — it is rate-limited and meant for occasional queries, not a live dependency.

Instead, geographic data is downloaded as regional GeoFabrik extracts:

India → Karnataka → Bangalore

Launch Districts

The first published dataset covers a contiguous, dense running corridor rather than the whole city:

Indiranagar
Ulsoor
Cubbon Park and the Shivajinagar / Richmond Town surrounds
Lalbagh
Jayanagar
Koramangala

The corridor is chosen for three reasons: the districts are adjacent, so a single player can plausibly reach several of them; the area contains three landmark destinations that give the map its headline objectives; and it is where Bengaluru's existing run-club culture is concentrated, which is the only credible answer to the cold-start problem.

Publishing the whole city would spread a small beta cohort across seven hundred square kilometres and produce an empty world. Territory density is a gameplay parameter, not just a content one.

GeoFabrik distributes OpenStreetMap as downloadable .osm.pbf files, updated regularly. These are periodically imported into the project's own spatial database using osm2pgsql or osmium.

This approach provides:

complete ownership of the data pipeline
predictable performance
no external rate limits
offline processing
deterministic territory generation

Once imported, every geographic query is answered by our own infrastructure, never a live third-party call.

PostGIS

PostGIS is the spatial database powering the project. It stores:

imported map geometry (from both OSM and Overture)
approved territory polygons
H3 cell index (`territory_cells` table, rebuilt on publish)
checkpoint locations
event locations
spatial indexes
future gameplay metadata

PostGIS answers spatial queries such as:

Which territory contains this GPS point? — via H3 index in the common case; direct containment for boundary cells only
Which territories intersect this running route?
Which checkpoints are nearby?
Which territories border each other?

Spatial queries should always be performed inside PostGIS whenever possible, rather than in application code. The H3 index handles the hot path; PostGIS handles exact geometry for distance clipping and boundary resolution.

GPS Data and Anti-Cheat (Scope Boundary)

This document assumes any GPS route data reaching the spatial queries above has already been validated — speed-cap checks, accelerometer cross-referencing, spoofing detection, and any other trust-establishing logic happen upstream, before a route is treated as real movement.

That validation pipeline is deliberately out of scope for this document. It is defined in `05_ANTICHEAT_AND_TRUST`. This boundary is stated explicitly so it isn't mistaken for solved — territory ownership is entirely downstream of "which territories does this route intersect," which makes route trustworthiness a prerequisite this pipeline depends on but does not itself provide.

Territory Generation

Unlike traditional location-based games that divide cities into artificial grids, this project uses meaningful real-world locations:

Parks
Lakes
Universities and campuses
Residential neighbourhoods
Stadiums
Waterfronts
Major public spaces
Running loops
Large recreational grounds

Players should feel like they are fighting for real places rather than anonymous squares on a grid — the goal is someone naturally saying "I own Cubbon Park," never "I own hex 48F7."

Area-based vs. line-based territories. Most examples above (parks, lakes, campuses) are natural enclosed polygons. Running loops and paths are not — they're lines. These require a distinct generation step: buffering the path geometry outward by a fixed width to produce a corridor-shaped polygon, rather than using an existing enclosed shape. The AI generation pipeline and human review step both need to treat these as a separate category with separate rules, not force them through the same "is this a closed polygon" logic as a park.

AI-Assisted Territory Generation

Territory generation happens during development. It is never part of live gameplay.

The AI pipeline analyses imported geographic data and proposes territories based on:

natural boundaries
roads and rivers
parks and lakes
pedestrian paths
neighbourhood structure
overall walkability and running suitability
expected gameplay balance
territory size
expected player density
running accessibility
competition potential
difficulty of defending

The AI may recommend splitting oversized areas, merging tiny fragmented ones, adjusting borders, assigning names, estimating strategic importance, and recommending influence capacity and decay half-life.

A note on where the work actually is. Partitioning a city into sensible polygons is mostly classical GIS — extracting landuse, leisure and natural features from the imported data, partitioning the remainder along the road network, enforcing minimum and maximum areas, and cleaning topology so the result tiles without gaps or overlaps. The language model's contribution is naming, importance estimation, plausibility review and flagging results a human should look at. Treating polygon generation itself as a language model task produces invalid geometry and cities that cannot be reproduced. The pipeline is GIS with AI assistance, not the reverse.

The word "deterministic" applies to the published artifact, not to the process. A language model is not deterministic in any engineering sense. What matters — and what is guaranteed — is that once a city is reviewed and published, its territory definitions are frozen, versioned and identical for every player until deliberately republished.

The AI never invents geography. It works exclusively from real-world map data — reshaping and labeling real polygons, never generating coordinates from nothing.

Bengaluru Data-Quality Validation

Before territory generation begins on a new city, run a one-day GIS validation pass against the imported data.

Sample representative features across the launch area:

parks
lakes and waterfronts
university and corporate campuses
neighbourhoods and residential pockets
markets and commercial districts
known running locations and popular loops

For each sample, check:

does geometry exist at all?
is the boundary approximately correct when compared to local knowledge?
does it have a meaningful, locally recognisable name?
are OSM or Overture tags accurate for the feature type?

If a significant portion of samples require manual correction, create a mapping correction workflow before proceeding to generation. Bad input geometry produces bad territories, and bad territories are expensive to fix after players have accumulated influence against them.

This step is cheap relative to everything downstream and should not be skipped.

Safety Pass

Before any territory is published, run an automated safety validation. No territory should incentivise unsafe movement. Territory value must never encourage dangerous running behaviour.

Reject or downgrade territories that contain:

high-speed roads without pedestrian access
highway-only or motorway-only areas
unsafe corridors — narrow shoulders, blind curves, unlit stretches
restricted zones where public running is not permitted

Flag for human review any territory whose runnable path network intersects arterial roads more than a stated threshold. The human reviewer decides whether the boundary can be redrawn to exclude the hazard.

This pass is enforced in the admin console before publish. See `06_ADMIN_AND_OPERATIONS`.

Exclusion Pass

Territory generation must exclude areas that should never be playable, regardless of whether geometry exists in the source data:

airport restricted zones
military and defence installations
restricted government facilities
private land without public access
large water-only regions with no runnable shoreline
motorway-only areas

Excluded areas are cut from the city boundary or marked unplayable. They do not become territories. If a generated proposal includes any of the above, it is rejected automatically and returned to the review queue.

Human Review

AI suggestions are never published automatically. Every generated territory is reviewed manually before release.

Humans remain responsible for approving:

territory boundaries
names
gameplay suitability
influence capacity and decay half-life
strategic balance
topology — that the set tiles the city with no gaps and no overlaps

Only approved territories become production data. This guarantees every published city is frozen and stable.

AI proposes. Humans publish.

This review step requires a real internal tool — a map view with editable polygons, an approval queue, and topology validation. It is a product in its own right and it sits on the critical path for launching any city.

Production Territory Data

Once approved, territories become permanent game assets, stored as ordinary spatial records. At runtime they are no different from hand-created data.

The mobile application never communicates with an AI model. Gameplay never depends on AI availability. This keeps the world deterministic, reproducible, inexpensive, fast, and scalable.

Boundary regeneration is handled through territory versioning — see the Territory Versioning section below. Versioning preserves history; migrating *active* influence across a boundary change remains an open problem and is named there.

Static Shapes vs. Live Territory State

Territory data splits into two categories that must not be conflated:

Static shape data (published once by the AI + human review pipeline, changes rarely): id, version, name, polygon geometry, importance, influence capacity, decay half-life, strategic metadata. Delivered as GeoJSON. Because it changes so infrequently, it can be cached aggressively client-side — fetched once per city and reused across sessions, refreshed only when that city's data version changes.

Milestone 2 publishes two layers: **parcels** (`published/territories.geojson`, Stage 09) and **gameplay** territories (`published/gameplay_territories.geojson`, Stage 12). The phone / `seed_territories.py --source pipeline` prefers the gameplay layer when present.

Live territory state (constantly changing): current ownership, influence share breakdown by contributor, whether the owner is a player or a club, and how closely contested it is. This is backend-calculated and queried far more frequently than shape data — on app open and foreground is sufficient given that influence decays on a multi-week half-life rather than changing second to second, so a live websocket is not warranted. Revisit once real usage data exists.

How they combine: the mobile app fetches static shapes once (and caches them), separately fetches live state keyed by territory ID, and joins the two client-side at render time. Conceptually:

GET /territories/{city_id}          → static shapes (cacheable, versioned)
GET /territories/{city_id}/state    → live ownership/influence (polled)

Rendering never waits on both to be freshly fetched together — shapes can be shown immediately from cache while state loads in behind them.

GeoJSON

Territories are delivered to the mobile application as GeoJSON, the standard format for geographic polygons. Each static territory record contains:

polygon geometry
unique identifier
display name
influence capacity
decay half-life
strategic metadata
rendering information

Additional gameplay properties can be added over time without changing the rendering pipeline, since live state is layered on separately rather than embedded in the shape data itself.

Mobile Rendering

The mobile application uses MapLibre. MapLibre renders:

roads
buildings
parks
water
territory polygons
checkpoints
player location
future gameplay overlays

MapLibre is responsible only for visualization. It never calculates gameplay.

Licensing

OpenStreetMap data is licensed under ODbL. Attribution — "© OpenStreetMap contributors," or a link to the license — is required at all times, with no exceptions, and applies even when data is accessed indirectly through OpenFreeMap, Overture, or self-hosted PMTiles rather than OSM directly. This must be visible somewhere in the app UI (a map corner credit or splash screen both satisfy it) and must be included in the Layer Order below, not treated as an afterthought.

Share-alike only applies if the territory database itself is ever exposed as a public bulk-download or API — the game, as a Produced Work, is otherwise exempt and only requires attribution. Full detail: see 03_MAP_PIPELINE_DUE_DILIGENCE, Section 4.

Tile Providers

During development the application uses OpenFreeMap — free vector tiles compatible with MapLibre, no API key required.

For production, tile serving migrates to self-hosted PMTiles served through Cloudflare R2 and a CDN.

Development:
OpenFreeMap
    ↓
MapLibre

Production:
OSM / Overture source data
    ↓
PMTiles (self-hosted)
    ↓
Cloudflare R2 + CDN
    ↓
MapLibre

Reasons for migration:

lower dependency risk — no reliance on an external provider with no SLA
better latency for Bengaluru users when tiles are served from ap-south-1
full control over caching, availability and update cadence
no commercial tile API restrictions or per-load billing
the renderer never changes — only the tile source URL changes

Migration trigger: the first of — first real payment accepted, a second OpenFreeMap reliability incident within a single month, or roughly 5,000 daily active users.

Layer Order

Rendering order is important — MapLibre draws layers in the order they're added, and misordering can visually bury something important.

Base map
Water
Roads
Territory fills
Territory borders
Checkpoints
Events
Player location
Temporary gameplay effects
OpenStreetMap attribution (always visible, never buried under other layers)

The player's own location marker should always remain visible above everything except temporary effects and attribution.

Runtime Responsibilities

The mobile application is responsible for:

requesting map tiles
requesting static territory shapes (cached) and live territory state (polled)
rendering layers
displaying player location

The backend is responsible for:

territory storage
spatial queries
gameplay logic
influence calculations
ownership calculations
checkpoint management
validating GPS data before it reaches any spatial query (per the scope boundary above, detailed elsewhere)

The mobile application should never implement gameplay rules that belong on the server.

Scalability

The architecture is intentionally designed so that no component becomes impossible to replace. Future changes should affect only isolated parts of the system, never the entire pipeline:

replacing OpenFreeMap with self-hosted PMTiles
replacing or upgrading AI models
importing additional cities or countries
expanding territory metadata
introducing seasonal events
correcting a city's territory boundaries post-launch (see the open problem noted above)

This separation of responsibilities is one of the project's primary engineering goals.

Territory Coverage

Territories exhaustively tile the city. Every point inside a published city belongs to exactly one territory. There is no null space in which movement earns nothing, and there are no overlaps.

This was an open question in v2 and is now decided. It has consequences the generation pipeline must respect:

No gaps. A city's territories must union to the city's published boundary with no interior holes.
No overlaps. Any two territories intersect only along their shared boundary.
Enclaves are permitted. A park entirely inside a neighbourhood is its own territory, and the neighbourhood becomes a polygon with a hole.
Coastline and water. Lakes are territories in their own right where they have runnable shoreline; open water without access is excluded from the city boundary rather than assigned.

Territory Sizing

Territories should not follow a fixed size. A territory should feel like a real place — Cubbon Park is one territory; a small residential pocket is a much smaller one.

The design target is that a normal run interacts with roughly one to two territories. That is tight enough that where a player runs is a genuine strategic decision, and loose enough that they are not crossing a border every ninety seconds.

Territories should be large enough to matter and small enough that a player has options nearby. Generation should balance:

running accessibility — how much runnable path is actually inside
natural boundaries — water, rail, arterial roads, walls, elevation
identity — does this correspond to a place a resident would name
competition — can several people plausibly contest it

Influence capacity scales with runnable path length inside a territory, not with raw area. A residential grid with ten kilometres of streets and a park with three kilometres of paths may be the same size and should not hold the same influence.

Boundaries Follow Separators

Territory boundaries should follow features people do not run along — arterial roads, rail lines, storm drains, water, walls — and never bisect a park, a lake shore, or a popular running loop.

This is the primary defence against border-hugging, where a player harvests many territories cheaply by running along their edges. A minimum presence threshold in `01_CORE_MECHANICS` provides a second defence, but geometry is the stronger one: if a border is a place nobody runs, the exploit has nowhere to happen.

Territory Versioning

Territories have immutable identity and versioned geometry.

territory_id — permanent, assigned once, never reused, never changed
version — incremented whenever geometry or gameplay parameters are republished

Cubbon Park is territory 1001 forever. Correcting its boundary produces territory 1001 version 2. Influence is always recorded against the territory version under which it was earned, so historical gameplay data survives a boundary correction instead of being orphaned by it.

Every published territory version carries:

id
version
geometry
name
influence_capacity
decay_half_life
strategic_value
difficulty
kind — area or corridor
source_ref — the underlying map features it was derived from

Open problem — influence migration. Versioning preserves history but does not by itself decide what happens to *active* influence when a boundary moves. A redrawn park could split, absorb or shed area that players have already contributed to. Three directions exist — map old influence proportionally onto the new geometry by area or by path length, freeze the old version and start the new one clean, or run both versions in parallel through a transition period. None is chosen. This must be resolved before any city is republished after launch, and it is listed as an open question in `01_CORE_MECHANICS` as well because it affects influence, not only geometry.

Route Matching

Turning a recorded route into per-territory distances is the single hottest path in the backend and the one most likely to produce visible unfairness if done naively. It has two separate problems that are often confused: lookup cost, and GPS noise.

The Problem With Point-In-Polygon

Raw point-in-polygon checks are insufficient.

Typical urban GPS accuracy in Bengaluru fluctuates between twenty and fifty metres under tree cover and beside tall buildings. A runner near a territory boundary may appear to jump between territories on successive fixes. Point-by-point assignment fragments a single clean run into many small segments, each of which may fail the minimum presence threshold defined in `01_CORE_MECHANICS`. The player did a legitimate five kilometre run and the game tells them it earned almost nothing.

That is a worse outcome than any cheat this system defends against, and it is nobody's fault.

Required Architecture

```
GPS trace
    ↓
GPS noise correction
    ↓
Spatial lookup using H3
    ↓
Boundary resolution
    ↓
Territory assignment
    ↓
Influence calculation
```

The system uses:

H3 for fast territory lookup in the common case
exact polygon geometry only for ambiguous boundary cases
segment-level assignment rather than individual GPS point assignment

Recommended starting approach:

H3 lookup for normal cases
hysteresis plus segment-level assignment for boundary cases

Candidate approaches to evaluate against real traces:

snap traces to the imported OSM road and path network before territory matching
apply hysteresis around territory boundaries — a transition is recognised only when the trace crosses by more than the reported horizontal accuracy and stays across
assign contiguous time segments by majority territory probability rather than classifying each fix independently

The exact algorithm is unresolved. It must be tested using real running traces recorded in the launch districts before the influence engine is built. Recording those traces is cheap and happens during the GPS reality test in `07_ROADMAP_AND_LAUNCH`.

H3 Spatial Indexing

Territories remain polygons. H3 is only an indexing layer. It is never visible to players — they interact with named places, not hexagons.

The problem H3 solves:

Every GPS point asking "which territory polygon contains me?" requires an expensive spatial query against the full polygon set. At one hertz for a forty-five minute run that is roughly two thousand seven hundred queries per activity.

The approach:

At territory publish time, generate H3 cells covering every territory geometry and store a flat lookup table:

```
territory_cells

h3_cell      BIGINT PRIMARY KEY
territory_id UUID
version      INT
```

At runtime:

```
GPS coordinate
    ↓
Convert to H3 cell (arithmetic, O(1))
    ↓
Lookup territory_id in territory_cells
    ↓
Return territory ID
```

Only boundary cells — cells whose centre falls within the horizontal accuracy radius of a territory edge — require a PostGIS containment check against the actual polygon. Everything else resolves from the index alone.

Resolution 10 cells average roughly fifteen thousand square metres, about sixty-six metres across. A cell straddling a boundary must be assigned to exactly one territory, so the index is an approximation near edges by design. For distance measurement, the route polyline is clipped against the actual polygon geometry for the small set of territories the index identified as candidates. Fast approximate lookup, exact measurement.

The cell index is derived data. It is rebuilt whenever a territory version is published and never edited by hand.

GPS Noise At Boundaries

H3 does not solve GPS jitter and neither does exact clipping alone.

Three defences, all required:

Boundaries follow separators. The structural fix, already stated above. If a boundary runs down the middle of a railway line rather than down a street people run on, the jitter has nowhere to happen. This is a generation rule, not a runtime one.

Hysteresis. A territory transition is only recognised when the trace crosses the boundary by more than the reported horizontal accuracy, and stays across. Movement within the error radius of a boundary does not change the assignment.

Segment assignment, not point assignment. The route is divided into contiguous time segments and each segment is assigned as a whole, by majority, rather than each fix being classified independently. A player is in one place at a time; the model should reflect that.

Territory Balancing Simulator

Before launch, build a simulation tool that models how the territory system behaves at different player densities. This is a recommendation, not a launch blocker, but it is the cheapest way to discover that territories are the wrong size before real players do.

Test scenarios:

Low density — 50 players
Does one person own everything?
Are territories too large for meaningful competition?
Can a new player find an uncontested neighbourhood?

Medium density — 500 players
Are competitions happening?
Are places changing ownership?
Does the 30% contested-territory target from `07_ROADMAP_AND_LAUNCH` look achievable?

High density — 5,000 players
Are territories too unstable?
Does ownership change so fast that tenure has no meaning?
Do diminishing returns and decay still produce readable standings?

The goal is to find the correct balance between meaningful ownership, genuine competition, and accessibility for new players. Territory size, influence capacity and decay half-life are the levers. The simulator exercises them against synthetic player behaviour before any of it is tuned on live users.

Measurement And Projection

Geometry is stored in EPSG:4326. Length and area must never be computed on 4326 geometry directly — the result is in degrees, not metres, and varies with latitude. All distance and area calculations use the geography type or a projected CRS appropriate to the city. This is stated because it is a silent correctness bug that produces plausible-looking wrong numbers.

Architectural Principles
The application owns the game world, not the map provider.
AI is a development tool, never a runtime dependency.
Every territory is deterministic once published.
Geographic data is imported into infrastructure we control — never queried live from a third party in production.
The renderer remains independent of gameplay.
Gameplay remains independent of tile providers.
Static shape data and live gameplay state are always fetched and cached separately, never conflated.
GPS validation is a prerequisite this pipeline depends on, not something it performs itself.
Every component should be replaceable with minimal changes to the rest of the system.
Prefer open standards whenever practical.
Design for long-term scalability rather than short-term convenience