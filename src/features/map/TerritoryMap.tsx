import { useAvatarVisibility } from '@/features/avatar/visibility';
import { LeaderBanners } from './LeaderBanners';
import {
  Camera,
  type CameraRef,
  GeoJSONSource,
  Layer,
  Map,
  type MapRef,
  type ViewState,
  useCurrentPosition,
} from '@maplibre/maplibre-react-native';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import {
  DEFAULT_BEARING,
  DEFAULT_PITCH,
  DEFAULT_ZOOM,
  JAYANAGAR_CENTER,
  MAP_STYLE,
} from '@/constants/config';
import { useHudDiagnostics } from '@/features/hud/useHudDiagnostics';
import { useRunCamera } from '@/features/hud/useRunCamera';
import { useRecorder } from '@/features/recorder/useRecorder';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { useBrowseLocation } from './useBrowseLocation';
import { territoryFill } from './territoryAppearance';
import { WorldStructures } from './WorldStructures';
import { GroundBorders } from './GroundBorderLayers';
import { withAlpha } from '@/features/hud/lighting';
import { useWorldFeatures } from './useWorldFeatures';
import { illuminateStreets } from './streetMatching';
import { StreetTrailLayers } from './StreetTrailLayers';
import { TrailLayers } from '@/features/hud/TrailLayers';
import { SocialMapLayers } from '@/features/social/SocialMapLayers';
import { smoothBearing } from '@/features/hud/telemetry';
import { RecenterIcon } from '@/components/icons';
import { MapAttribution } from './MapAttribution';
import { PlayerAvatar } from '@/features/avatar/PlayerAvatar';
import { useAvatarCamera } from '@/features/avatar/useAvatarCamera';
import { AVATAR_3D_SUPPORTED } from '@/features/avatar/support';
import type { TerritoryState, GhostSummary } from '@/services/api/types';
import { CueMapLayers } from '@/features/hud/CueMapLayers';
import { ContestedBorders } from '@/features/hud/ContestedBorders';
import { mockAdjacentBorders, sharedBorders, selectBorders } from '@/features/hud/borders';
import { ThemeLayers } from '@/features/hud/ThemeLayers';
import { useLighting } from '@/features/hud/useLighting';
import type { RunFix } from '@/features/hud/telemetry';
import { MAP_ART } from '@/features/map/mapArt';
import { assignTerritoryColors } from '@/lib/territoryColors';
import { colors, CAPTURE_COLOR_PALETTE, DEFAULT_CAPTURE_COLOR_INDEX } from '@/theme';

// Keep the offline geometry referentially stable. Requiring it during every
// ownership update used to repeat the costly territory colour calculation.
const OFFLINE_TERRITORIES = require('@/assets/map/gameplay_territories.json') as GeoJSON.FeatureCollection;

type Props = {
  territories: GeoJSON.FeatureCollection | null;
  capturedAreas?: GeoJSON.FeatureCollection | null;
  /** Server-dissolved fixed territory geometry grouped by owner. */
  ownedTerritoryAreas?: GeoJSON.FeatureCollection | null;
  /** Ownership, used only to choose a fill colour. */
  territoryLeaders?: TerritoryState[];
  ownedByYou: Set<string>;
  ownedByOthers: Set<string>;
  /**
   * Cleaned GPS route while recording.
   * This is the authoritative path for rendering — never raw GPS noise.
   * Accuracy-filtered, spike-rejected, EMA-smoothed during the run;
   * Visual LOD is gap-aware; the recorded evidence stays unchanged.
   */
  traversedRoads: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  fix?: RunFix | null;
  presentationActive?: boolean;
  reducedMotion?: boolean;
  economy?: boolean;
  simulation?: boolean;
  bottomInset?: number;
  onDayChange?: (day: boolean) => void;
  /** Future multiplayer feed: only shared line geometry, never whole territories. */
  contestedBorders?: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  loopCandidate: GeoJSON.Feature<GeoJSON.Polygon> | null;
  /**
   * Territory IDs visited in the current run (populated via point-in-polygon
   * against the clean path in the parent screen).
   * These territories receive an extra visual pulse to communicate activation.
   */
  activeTerritoryIds: Set<string>;
  recording: boolean;
  isRunning?: boolean;
  onTerritoryPress?: (territoryId: string) => void;
  onSimulationMove?: (coordinate: [number, number]) => void;
  activationColor?: string;
  /** Index into CAPTURE_COLOR_PALETTE for the player's chosen capture color. */
  captureColorIndex?: number;
  /** Controls which overlay layers are visible: territories, captures, or both. */
  visibleLayers?: 'all' | 'territories' | 'captures';
  /** Public ghosts to draw. Only passed when the player turns that layer on. */
  nearbyGhosts?: GhostSummary[];
  /** Long-pressing the map drops a race pin, when the screen offers that. */
  onDropRacePin?: (coordinate: [number, number]) => void;
  /** Draw the 3D player avatar above the map. Off for the run summary, which
   *  shows a finished route rather than a live position. */
  showAvatar?: boolean;
};

/** The hologram the avatar stands on: cyan rather than the marker's blue, so it
 *  reads as light cast on the road and not as a second dot under the feet. */
const HOLOGRAM = colors.route;

/** Below a walking pace the run cycle reads as skating, so the avatar idles.
 *  Measured against the cleaned fix, not raw GPS, so a stationary jitter of a
 *  metre or two does not flip the clip back and forth. */
const RUNNING_SPEED_MPS = 0.8;

const DEVELOPER_COLORS: Record<string, string> = {
  '10000000-0000-4000-8000-000000000001': '#22C55E',
  '10000000-0000-4000-8000-000000000002': '#A855F7',
  '10000000-0000-4000-8000-000000000003': '#F97316',
};

function colourForOwner(ownerId: unknown) {
  return DEVELOPER_COLORS[String(ownerId)] ?? colors.ownedByOther;
}

function withOwnerColors(collection: GeoJSON.FeatureCollection | null | undefined) {
  if (!collection) return null;
  return {
    ...collection,
    features: collection.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        owner_color: colourForOwner(feature.properties?.owner_device_id),
        owner_fill: withAlpha(colourForOwner(feature.properties?.owner_device_id), 0.16),
        owner_fill_mid: withAlpha(colourForOwner(feature.properties?.owner_device_id), 0.26),
        owner_fill_far: withAlpha(colourForOwner(feature.properties?.owner_device_id), 0.40),
      },
    })),
  } as GeoJSON.FeatureCollection;
}

/**
 * Rendering only. This component draws geometry and decides nothing about the
 * game — `03` keeps the map layer separate from raw geographic data and from
 * game logic, and forbids MapLibre from calculating gameplay.
 *
 * Live run visual design:
 *   cleanPath → user-selected GPS trail or matched street illumination
 *   activeTerritoryIds → territory fill pulses cyan as the runner enters it
 */
export const TerritoryMap = memo(function TerritoryMap({
  territories,
  capturedAreas,
  ownedTerritoryAreas,
  territoryLeaders = [],
  ownedByYou,
  ownedByOthers,
  traversedRoads,
  loopCandidate,
  activeTerritoryIds,
  recording,
  isRunning = false,
  onTerritoryPress,
  onSimulationMove,
  activationColor = colors.route,
  captureColorIndex = DEFAULT_CAPTURE_COLOR_INDEX,
  visibleLayers = 'all',
  nearbyGhosts,
  onDropRacePin,
  showAvatar = false, onDayChange,
  fix = null, presentationActive = true, reducedMotion = false, economy = false, simulation = false, bottomInset = 8, contestedBorders,
}: Props) {
  const showTerritories = visibleLayers === 'all' || visibleLayers === 'territories';
  const showCaptures = visibleLayers === 'all' || visibleLayers === 'captures';
  const onRenderedFrame = useHudDiagnostics(presentationActive && recording);
  const mapRef = useRef<MapRef>(null);
  const cameraRef = useRef<CameraRef>(null);
  const [mapReady, setMapReady] = useState(false);
  // MapLibre will start its location feed without asking. On a fresh Android
  // install that feed is empty until a run requests permission, so the camera
  // stays on Jayanagar. Ask here, then start the feed only once it can succeed.
  const locating = useBrowseLocation(presentationActive && !simulation);
  const nativePosition = useCurrentPosition({ enabled: locating && !recording && presentationActive && !simulation, minDisplacement: 5 });
  const browseFix = useMemo<RunFix | null>(() => nativePosition ? { coordinate: [nativePosition.coords.longitude, nativePosition.coords.latitude], ts: nativePosition.timestamp, speedMps: 0, bearing: null, accuracyM: nativePosition.coords.accuracy, segment: 0 } : null, [nativePosition]);
  const effectiveFix = recording || simulation ? fix : browseFix ?? fix;
  const follow = useRunCamera(cameraRef, effectiveFix, recording, presentationActive, reducedMotion, economy, mapReady);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const runId = useRecorder(s => s.runId);
  const routeDisplay = useHudPreferences(s => s.routeDisplay);
  // Some people want the character, some want the dot they already knew where
  // to look for. Both are drawn from the same fix, so this only swaps the marks.
  // The character is additionally gated on being renderable at all: while it
  // crashes the app, a stored preference for it must not be obeyed.
  const playerMarker = useHudPreferences(s => s.playerMarker);
  const wantsAvatar = AVATAR_3D_SUPPORTED && playerMarker === 'avatar';
  const palette = useLighting(effectiveFix, presentationActive, simulation);
  useEffect(() => { onDayChange?.(palette.isDay); }, [palette.isDay, onDayChange]);
  const hasOwnedAreaGeometry = Boolean(ownedTerritoryAreas?.features.length);
  const ownerColouredAreas = useMemo(() => withOwnerColors(ownedTerritoryAreas), [ownedTerritoryAreas]);

  // Captured loop areas get a single user-chosen colour, distinct from the
  // territory zone palette, so players can immediately tell "I created this".
  const captureColor = CAPTURE_COLOR_PALETTE[captureColorIndex] ?? CAPTURE_COLOR_PALETTE[0];
  const styledCapturedAreas = useMemo(() => {
    if (!capturedAreas) return null;
    return {
      ...capturedAreas,
      features: capturedAreas.features.map((feature) => ({
        ...feature,
        properties: {
          ...feature.properties,
          capture_color: captureColor,
          capture_fill: withAlpha(captureColor, 0.3),
          capture_fill_mid: withAlpha(captureColor, 0.44),
          capture_fill_far: withAlpha(captureColor, 0.6),
        },
      })),
    } as GeoJSON.FeatureCollection;
  }, [capturedAreas, captureColor]);

  const sourceTerritories = useMemo(
    () => (territories?.features?.length ? territories : OFFLINE_TERRITORIES),
    [territories],
  );

  // Neighbour-aware palette assignment builds an adjacency graph for ~310
  // polygons. It is static map data, so never rebuild it for an ownership
  // refresh or a moving runner.
  const colorByTerritory = useMemo(
    () => assignTerritoryColors(sourceTerritories.features),
    [sourceTerritories],
  );

  // Base territory rendering: colors + ownership state.
  const decorated: GeoJSON.FeatureCollection | null = useMemo(() => {
    return {
      ...sourceTerritories,
      features: sourceTerritories.features.map((feature) => {
        const id = String(feature.properties?.territory_id);
        const zoneColor = colorByTerritory.get(id) ?? '#A87CDC';
        return {
          ...feature,
          properties: {
            ...feature.properties,
            ownership: ownedByYou.has(id) ? 'you' : ownedByOthers.has(id) ? 'other' : 'none',
            terrain_color: zoneColor,
            // Keep transparency in the color itself. MapLibre React Native's
            // fill-opacity bridge can dereference a released style value on
            // iOS when these layers are updated during a style swap.
            terrain_fill: withAlpha(zoneColor, 0.14),
            terrain_fill_mid: withAlpha(zoneColor, 0.22),
            terrain_fill_far: withAlpha(zoneColor, 0.34),
            fill_color: zoneColor,
            outline_color: zoneColor,
          },
        };
      }),
    };
  }, [colorByTerritory, ownedByYou, ownedByOthers, sourceTerritories]);

  const buildingTerritories = useMemo(() => [
    ...(showCaptures && !isRunning ? styledCapturedAreas?.features ?? [] : []),
    ...(showTerritories ? ownerColouredAreas?.features ?? [] : []),
    ...(showTerritories ? decorated?.features ?? [] : []),
  ], [showCaptures, isRunning, styledCapturedAreas, showTerritories, ownerColouredAreas, decorated]);
  const world = useWorldFeatures(mapRef, mapReady, presentationActive, economy, zoom, recording ? runId : null, buildingTerritories, palette.building);
  const streetTrail = useMemo(() => routeDisplay === 'streets' && recording ? illuminateStreets(traversedRoads, world.roads) : null, [routeDisplay, recording, traversedRoads, world.roads]);

  /**
   * Subset of territories that the runner is currently traversing.
   * Rendered as a separate source so the pulse layer can be styled
   * independently without rebuilding the full decorated collection.
   */
  const activePulseCollection = useMemo((): GeoJSON.FeatureCollection | null => {
    if (!decorated || activeTerritoryIds.size === 0) return null;
    const activeIds = activeTerritoryIds;
    const activeFeatures = decorated.features.filter((f) =>
      activeIds.has(String(f.properties?.territory_id ?? '')),
    );
    if (activeFeatures.length === 0) return null;
    return { type: 'FeatureCollection', features: activeFeatures };
  }, [decorated, activeTerritoryIds]);

  const edges = useMemo(() => sharedBorders(sourceTerritories.features), [sourceTerritories]);
  const borders = useMemo(() => contestedBorders ?? (simulation ? mockAdjacentBorders(JAYANAGAR_CENTER) : selectBorders(edges, ownedByYou, ownedByOthers)), [contestedBorders, edges, ownedByYou, ownedByOthers, simulation]);

  const handleTerritoryPress = useCallback(
    (event: { nativeEvent?: { features?: GeoJSON.Feature[] } }) => {
      const feature = event.nativeEvent?.features?.[0];
      const id = feature?.properties?.territory_id ?? feature?.id;
      if (id != null) onTerritoryPress?.(String(id));
    },
    [onTerritoryPress]
  );

  /**
   * The map's camera, mirrored so the avatar can be drawn in the same space.
   *
   * The pose goes straight into shared values the render thread reads — see
   * `useAvatarCamera` for why it must not go through component state — and the
   * events carry the whole view state, so nothing has to be asked for. Only the
   * very first camera is read back, to place the avatar before the map is
   * touched.
   */
  const avatarCamera = useAvatarCamera();
  const avatarCoordinate = showAvatar && wantsAvatar && presentationActive && !economy
    ? effectiveFix?.coordinate ?? null
    : null;
  const avatarEnabled = Boolean(avatarCoordinate) && mapReady;
  // Read through a ref so the map's event handlers never need rebinding as the
  // player moves: a new fix must not cost a re-render of every layer.
  const avatarTarget = useRef(avatarCoordinate);
  avatarTarget.current = avatarCoordinate;
  const avatarHeading = useRef(0);
  const lastHeadingTs = useRef<number | null>(null);
  const lastPose = useRef<ViewState | null>(null);
  const cameraRevision = useRef(0);
  const { track: placeAvatar, clear: clearAvatar } = avatarCamera;
  const trackCamera = useCallback((state: ViewState) => {
    cameraRevision.current += 1;
    lastPose.current = state;
    placeAvatar(state, avatarTarget.current, avatarHeading.current);
  }, [placeAvatar]);
  useEffect(() => {
    // Heading comes from displacement, not the phone compass. Keep the last
    // reliable heading at rest and interpolate across north's 359°/0° seam.
    if (effectiveFix?.bearing != null && effectiveFix.speedMps >= RUNNING_SPEED_MPS && effectiveFix.ts !== lastHeadingTs.current) {
      avatarHeading.current = lastHeadingTs.current == null ? effectiveFix.bearing : smoothBearing(avatarHeading.current, effectiveFix.bearing, 0.45);
      lastHeadingTs.current = effectiveFix.ts;
    }
    if (avatarEnabled && lastPose.current) placeAvatar(lastPose.current, avatarCoordinate, avatarHeading.current);
  }, [effectiveFix, avatarCoordinate, avatarEnabled, placeAvatar]);
  useEffect(() => {
    if (!avatarEnabled) { clearAvatar(); return; }
    if (lastPose.current) {
      placeAvatar(lastPose.current, avatarTarget.current, avatarHeading.current);
      return;
    }
    let cancelled = false;
    const revision = cameraRevision.current;
    void mapRef.current?.getViewState().then(state => {
      // A slow bridge response must never overwrite a newer gesture event.
      if (!cancelled && revision === cameraRevision.current && state) trackCamera(state);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [avatarEnabled, clearAvatar, placeAvatar, trackCamera]);
  const modelLoaded = useAvatarVisibility(s => s.ids.includes('self'));
  const avatarDrawn = avatarEnabled && avatarCamera.placed && modelLoaded;

  return (
    <View style={styles.container} onLayout={avatarCamera.onLayout}>
      <Map
        ref={mapRef}
        style={styles.map}
        // A style swap during every run start/finish reloads all native layers
        // and can race React Native layer updates. One stable base style keeps
        // the transition responsive; the run-specific treatment is layered.
        mapStyle={MAP_STYLE}
        attribution={false}
        compass={false}
        logo={false}
        scaleBar={false}
        onDidFinishLoadingMap={() => setMapReady(true)}
        onRegionWillChange={event => { follow.onGesture(event.nativeEvent); trackCamera(event.nativeEvent); }}
        onRegionIsChanging={event => { trackCamera(event.nativeEvent); }}
        onDidFinishRenderingFrame={onRenderedFrame}
        preferredFramesPerSecond={recording ? 30 : 60}
        onRegionDidChange={event => { setZoom(event.nativeEvent.zoom); trackCamera(event.nativeEvent); }}
        onPress={(event) => {
          if (!onSimulationMove) return;
          const [lon, lat] = event.nativeEvent.lngLat;
          onSimulationMove([lon, lat]);
        }}
        onLongPress={(event) => {
          if (!onDropRacePin) return;
          const [lon, lat] = event.nativeEvent.lngLat;
          onDropRacePin([lon, lat]);
        }}
      >
        <ThemeLayers palette={palette} reducedMotion={reducedMotion} />
        <Camera
          ref={cameraRef}
          initialViewState={{
            center: JAYANAGAR_CENTER,
            zoom: DEFAULT_ZOOM,
            pitch: reducedMotion || economy ? 0 : DEFAULT_PITCH,
            bearing: reducedMotion || economy ? 0 : DEFAULT_BEARING,
          }}

        />

        {/* ── Territory Zone Overlays ─────────────────────────── */}
        {showTerritories && decorated && (
          <GeoJSONSource id="territories" data={decorated} onPress={handleTerritoryPress}>
            {/* Zone color sits below roads so the street network stays legible. */}
            <Layer
              id="territory-vitality"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              filter={hasOwnedAreaGeometry ? ['all', ['!=', ['get', 'kind'], 'park'], ['==', ['get', 'ownership'], 'none']] : ['!=', ['get', 'kind'], 'park']}
              layout={{ visibility: isRunning ? 'none' : 'visible' }}
              paint={{
                'fill-color': territoryFill('terrain_fill'),
              }}
            />

            <Layer
              id="territory-ownership-tint"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              filter={['all', ['!=', ['get', 'kind'], 'park'], ['!=', ['get', 'ownership'], 'none']]}
              layout={{ visibility: isRunning || hasOwnedAreaGeometry ? 'none' : 'visible' }}
              paint={{
                'fill-color': [
                  'match',
                  ['get', 'ownership'],
                  'you',
                  withAlpha(colors.ownedByYou, 0.22),
                  'other',
                  withAlpha(colors.ownedByOther, 0.22),
                  'rgba(0,0,0,0)',
                ],
              }}
            />

            <Layer
              id="territory-name"
              type="symbol"
              beforeId={MAP_ART.firstRoadLayerId}
              layout={{
                'text-field': ['get', 'name'],
                'text-font': ['Noto Sans Regular'],
                'text-size': ['interpolate', ['linear'], ['zoom'], 12, 10, 16, 13],
                'text-max-width': 8,
              }}
              paint={{
                'text-color': palette.label,
                'text-halo-color': palette.halo,
                'text-halo-width': 1.2,
                'text-opacity': 0.82,
              }}
            />

            {/* Parks stay green; ownership is communicated by their border. */}
            <Layer
              id="territory-park-fill"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              filter={['==', ['get', 'kind'], 'park']}
              layout={{ visibility: isRunning ? 'none' : 'visible' }}
              paint={{
                'fill-color': [
                  'match',
                  ['get', 'ownership'],
                  'you',
                  withAlpha(MAP_ART.park.ownedByYou, 0.62),
                  'other',
                  withAlpha(MAP_ART.park.ownedByOther, 0.62),
                  withAlpha(MAP_ART.park.unclaimed, 0.62),
                ],
              }}
            />
            <Layer
              id="territory-park-highlight"
              type="line"
              beforeId={MAP_ART.firstRoadLayerId}
              filter={hasOwnedAreaGeometry
                ? ['all', ['==', ['get', 'kind'], 'park'], ['==', ['get', 'ownership'], 'none']]
                : ['==', ['get', 'kind'], 'park']}
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': MAP_ART.park.highlight,
                'line-opacity': isRunning ? 0 : 0.5,
                'line-width': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  12,
                  1,
                  15,
                  2.5,
                  17,
                  4,
                ],
              }}
            />

            {/* Outer glow border — wider, semi-transparent */}
            <Layer beforeId="hud-base-anchor"
              id="territory-outline-glow"
              type="line"
              filter={hasOwnedAreaGeometry ? ['==', ['get', 'ownership'], 'none'] : undefined}
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': isRunning ? '#DCEFC5' : [
                  'match',
                  ['get', 'ownership'],
                  'you',
                  colors.ownedByYou,
                  'other',
                  colors.ownedByOther,
                  ['get', 'outline_color'],
                ],
                'line-opacity': isRunning ? 0.16 : 0.22,
                'line-width': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  10,
                  2,
                  12,
                  4,
                  14,
                  7,
                  16,
                  10,
                ],
                'line-blur': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  10,
                  1.5,
                  16,
                  3.5,
                ],
              }}
            />

            {/* Inner border — crisp, narrow */}
            <Layer beforeId="hud-base-anchor"
              id="territory-outline"
              type="line"
              filter={hasOwnedAreaGeometry ? ['==', ['get', 'ownership'], 'none'] : undefined}
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': isRunning ? '#F3FFE7' : [
                  'match',
                  ['get', 'ownership'],
                  'you',
                  colors.ownedByYou,
                  'other',
                  colors.ownedByOther,
                  ['get', 'outline_color'],
                ],
                'line-opacity': 0.5,
                'line-width': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  10,
                  1,
                  12,
                  1.8,
                  14,
                  3,
                  16,
                  4,
                ],
              }}
            />
          </GeoJSONSource>
        )}

        {/* Connected fixed territories with the same owner arrive already
            dissolved from PostGIS. This hides internal borders but never joins
            a real gap or territories held by different players. */}
        {showTerritories && ownerColouredAreas?.features.length ? (
          <GeoJSONSource id="owned-territory-areas" data={ownerColouredAreas}>
            <Layer
              id="owned-territory-area-fill"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              paint={{
                'fill-color': territoryFill('owner_fill'),
              }}
            />
            <Layer beforeId="hud-base-anchor"
              id="owned-territory-area-glow"
              type="line"
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': ['get', 'owner_color'],
                'line-opacity': isRunning ? 0.42 : 0.58,
                'line-width': ['interpolate', ['linear'], ['zoom'], 10, 2.5, 14, 6, 16, 10],
                'line-blur': 1.5,
              }}
            />
            <Layer beforeId="hud-base-anchor"
              id="owned-territory-area-outline"
              type="line"
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': ['get', 'owner_color'],
                'line-opacity': 0.92,
                'line-width': ['interpolate', ['linear'], ['zoom'], 10, 1.2, 14, 2.8, 16, 4.5],
              }}
            />
          </GeoJSONSource>
        ) : null}

        {/* Player-created overlays sit above fixed territory state; they never
            modify the fixed polygons or their ownership colours. */}
        {/* Player-created loop captures use a dedicated bright colour chosen
            by the player. A dashed outline and higher saturation make them
            visually pop above the muted territory zone palette. */}
        {showCaptures && !isRunning && styledCapturedAreas?.features.length ? (
          <GeoJSONSource id="captured-areas" data={styledCapturedAreas}>
            <Layer
              id="captured-area-fill"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              paint={{
                'fill-color': territoryFill('capture_fill'),
              }}
            />
            <Layer beforeId="hud-base-anchor"
              id="captured-area-glow"
              type="line"
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': ['get', 'capture_color'],
                'line-width': ['interpolate', ['linear'], ['zoom'], 12, 3, 15, 5, 17, 7],
                'line-opacity': 0.35,
                'line-blur': 4,
              }}
            />
            <Layer beforeId="hud-base-anchor"
              id="captured-area-outline"
              type="line"
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': ['get', 'capture_color'],
                'line-width': 2,
                'line-opacity': 0.9,
                'line-dasharray': [3, 2],
              }}
            />
          </GeoJSONSource>
        ) : null}

        {/* ── Active Territory Pulse (game activation effect) ──── */}
        {/*
         * When the runner enters a territory, it gets an extra vivid cyan fill
         * layered on top of its base color. This communicates "you are activating
         * this territory" without revealing ownership or score.
         * Separate GeoJSONSource so it can be updated without rebuilding decorated.
         */}
        {!isRunning && activePulseCollection && (
          <GeoJSONSource id="territories-active" data={activePulseCollection}>
            {/* Wide ambient glow — territory "warms up" */}
            <Layer
              id="territory-active-glow"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              paint={{
                'fill-color': withAlpha(colors.route, 0.16),
              }}
            />
            {/* Bright border pulse — territory edge lights up */}
            <Layer beforeId="hud-base-anchor"
              id="territory-active-border"
              type="line"
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': colors.route,
                'line-opacity': 0.7,
                'line-width': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  10,
                  1.5,
                  13,
                  3,
                  15,
                  5,
                ],
                'line-blur': 1,
              }}
            />
          </GeoJSONSource>
        )}

        <GroundBorders palette={palette} />
        <WorldStructures details={world.details} palette={palette} facadeTint={world.facadeTint} />
        {showTerritories && <ContestedBorders data={borders} active={presentationActive} reducedMotion={reducedMotion} economy={economy} zoom={zoom} />}
        {recording && (streetTrail ? <StreetTrailLayers {...streetTrail} economy={economy} /> : <TrailLayers data={traversedRoads} economy={economy} />)}
        <CueMapLayers active={presentationActive} reducedMotion={reducedMotion} territories={sourceTerritories} />

        {!isRunning && loopCandidate && (
          <GeoJSONSource id="loop-candidate" data={loopCandidate}>
            <Layer beforeId="hud-base-anchor" id="loop-candidate-fill" type="fill" paint={{ 'fill-color': withAlpha(colors.route, 0.1) }} />
            <Layer beforeId="hud-base-anchor" id="loop-candidate-outline" type="line" layout={{ 'line-join': 'round' }} paint={{ 'line-color': colors.route, 'line-width': 3, 'line-opacity': 0.75, 'line-dasharray': [2, 1] }} />
          </GeoJSONSource>
        )}

        {effectiveFix && presentationActive && (
          <GeoJSONSource id="player-marker" data={{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: effectiveFix.coordinate } }}>
            {/* The hologram is drawn by the map, not by Filament, so it sits on
                the ground plane: it scales with zoom, tilts with pitch and is
                occluded by buildings the way a projection on tarmac would be.
                Three rings rather than one — a soft spill, a filled pad and a
                wider outline — so it reads as light thrown onto the road under
                the character's feet instead of a dot it happens to stand on. */}
            {/* Explicit keys: GeoJSONSource drops falsy children before it
                clones them, so without one a layer appearing or disappearing
                shifts the generated keys and MapLibre is asked to rename a
                live layer, which it refuses. */}
            {avatarDrawn && <Layer key="player-hologram-glow" beforeId="hud-player-anchor" id="player-hologram-glow" type="circle" paint={{ 'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 9, 18, 22], 'circle-color': HOLOGRAM, 'circle-opacity': 0.18, 'circle-blur': 1 }} />}
            {avatarDrawn && <Layer key="player-hologram-ring" beforeId="hud-player-anchor" id="player-hologram-ring" type="circle" paint={{ 'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 8, 18, 19], 'circle-color': HOLOGRAM, 'circle-opacity': 0, 'circle-stroke-width': 1.2, 'circle-stroke-color': HOLOGRAM, 'circle-stroke-opacity': 0.32 }} />}
            {avatarDrawn && <Layer key="player-hologram-pad" beforeId="hud-player-anchor" id="player-hologram-pad" type="circle" paint={{ 'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 6, 18, 13], 'circle-color': HOLOGRAM, 'circle-opacity': 0.3, 'circle-stroke-width': 1.5, 'circle-stroke-color': HOLOGRAM, 'circle-stroke-opacity': 0.85 }} />}
            {/* Whenever the avatar is not actually drawn — the classic marker,
                no fix projected, economy mode, the summary map — the plain dot
                takes over, so the exact spot is never left unmarked. */}
            {!avatarDrawn && <Layer key="player-marker-glow" beforeId="hud-player-anchor" id="player-marker-glow" type="circle" paint={{ 'circle-radius': 18, 'circle-color': activationColor, 'circle-opacity': 0.2, 'circle-blur': 0.55 }} />}
            {!avatarDrawn && <Layer key="player-marker-dot" beforeId="hud-player-anchor" id="player-marker-dot" type="circle" paint={{ 'circle-radius': 7, 'circle-color': activationColor, 'circle-stroke-width': 3, 'circle-stroke-color': colors.surface }} />}
          </GeoJSONSource>
        )}

        <LeaderBanners states={territoryLeaders} capturedAreas={showCaptures ? styledCapturedAreas : null} colors={colorByTerritory} />
        <SocialMapLayers nearbyGhosts={nearbyGhosts} />
      </Map>

      {/* Above the map, never inside it: Filament is a separate native view and
          composites over MapLibre rather than drawing into it. It shares the
          map's camera instead, so the character stays on its own patch of
          ground while the map is panned around it. */}
      <PlayerAvatar
        camera={avatarCamera}
        running={recording && (effectiveFix?.speedMps ?? 0) > RUNNING_SPEED_MPS}
      />

      {recording && <Pressable accessibilityRole="button" accessibilityLabel={`Trail display: ${routeDisplay === 'streets' ? 'light up streets' : 'GPS trail'}. Tap to switch.`} onPress={() => useHudPreferences.getState().setRouteDisplay(routeDisplay === 'streets' ? 'gps' : 'streets')} style={[styles.trailMode, simulation && { left: undefined, right: 66 }, { bottom: bottomInset + 44 }]}>
        <Text style={styles.trailModeLabel}>{routeDisplay === 'streets' ? '▰  LIT STREETS' : '⌁  GPS TRAIL'}</Text>
      </Pressable>}
      {/* Compact, accessible attribution remains available on the map. */}
      <View pointerEvents="box-none" style={[styles.mapFootnote, { bottom: bottomInset }]}>
        <MapAttribution />
      </View>
      <Pressable
        accessibilityLabel={follow.following ? "Recenter on your location" : "Resume following your location"}
        accessibilityRole="button"
        disabled={!effectiveFix}
        style={[styles.recenter, { bottom: bottomInset + 45 }]}
        onPress={follow.recenter}
      >
        <RecenterIcon size={24} />
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  container: { flex: 1 },
  map: { flex: 1 },
  trailMode: { position: 'absolute', left: 14, paddingHorizontal: 14, height: 40, justifyContent: 'center', borderRadius: 20, backgroundColor: '#0E3445F2', borderWidth: 1, borderColor: '#7EC3BB' },
  trailModeLabel: { fontSize: 10, color: '#E9FFF4', fontWeight: '700', letterSpacing: 1 },
  mapFootnote: { position: 'absolute', left: 12, right: 6, alignItems: 'flex-end' },
  environment: { color: '#ECFFF6', backgroundColor: '#0A1929D9', fontSize: 10, padding: 4, borderRadius: 4, marginBottom: 3 },
  attribution: {

    fontSize: 10,
    color: colors.textMuted,
    backgroundColor: 'rgba(255,255,255,0.75)',
    paddingHorizontal: 4,
    borderRadius: 3,
  },
  recenter: { position: 'absolute', right: 14, bottom: 28, width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 5, elevation: 3 },
  recenterText: { fontSize: 24, color: colors.primary },
});
