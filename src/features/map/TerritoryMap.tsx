import {
  Camera,
  type CameraRef,
  GeoJSONSource,
  Layer,
  Map,
  type MapRef,
  UserLocation,
} from '@maplibre/maplibre-react-native';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import {
  DEFAULT_BEARING,
  DEFAULT_PITCH,
  DEFAULT_ZOOM,
  JAYANAGAR_CENTER,
  MAP_ATTRIBUTION,
  MAP_STYLE,
} from '@/constants/config';
import { MAP_ART } from '@/features/map/mapArt';
import { assignTerritoryColors } from '@/lib/territoryColors';
import { colors, CAPTURE_COLOR_PALETTE, DEFAULT_CAPTURE_COLOR_INDEX } from '@/theme';

// Keep the offline geometry referentially stable. Requiring it during every
// ownership update used to repeat the costly territory colour calculation.
const OFFLINE_TERRITORIES = require('@/assets/map/gameplay_territories.json') as GeoJSON.FeatureCollection;

const withAlpha = (hex: string, alpha: number) => {
  const value = hex.replace('#', '');
  if (value.length !== 6) return hex;
  const red = Number.parseInt(value.slice(0, 2), 16);
  const green = Number.parseInt(value.slice(2, 4), 16);
  const blue = Number.parseInt(value.slice(4, 6), 16);
  const clampedAlpha = Math.max(0, Math.min(1, alpha));
  return `rgba(${red},${green},${blue},${clampedAlpha})`;
};

type Props = {
  territories: GeoJSON.FeatureCollection | null;
  capturedAreas?: GeoJSON.FeatureCollection | null;
  /** Server-dissolved fixed territory geometry grouped by owner. */
  ownedTerritoryAreas?: GeoJSON.FeatureCollection | null;
  /** Ownership, used only to choose a fill colour. */
  ownedByYou: Set<string>;
  ownedByOthers: Set<string>;
  /**
   * Cleaned GPS route while recording.
   * This is the authoritative path for rendering — never raw GPS noise.
   * Accuracy-filtered, spike-rejected, EMA-smoothed during the run;
   * RDP + turn-smoothed on run completion.
   */
  traversedRoads: GeoJSON.Feature<GeoJSON.MultiLineString> | null;
  loopCandidate: GeoJSON.Feature<GeoJSON.Polygon> | null;
  /**
   * Territory IDs visited in the current run (populated via point-in-polygon
   * against the clean path in the parent screen).
   * These territories receive an extra visual pulse to communicate activation.
   */
  activeTerritoryIds: Set<string>;
  /** Server-confirmed captures only. Pulsed briefly before settling to ownership colour. */
  justCapturedTerritoryIds?: Set<string>;
  recording: boolean;
  isRunning?: boolean;
  onTerritoryPress?: (territoryId: string) => void;
  onSimulationMove?: (coordinate: [number, number]) => void;
  simulationPosition?: [number, number];
  activationColor?: string;
  /** Index into CAPTURE_COLOR_PALETTE for the player's chosen capture color. */
  captureColorIndex?: number;
  /** Controls which overlay layers are visible: territories, captures, or both. */
  visibleLayers?: 'all' | 'territories' | 'captures';
};

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
        owner_fill: withAlpha(colourForOwner(feature.properties?.owner_device_id), 0.18),
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
 *   cleanPath → glowing road-hugging highlight (NOT a raw GPS polyline)
 *   activeTerritoryIds → territory fill pulses cyan as the runner enters it
 */
export function TerritoryMap({
  territories,
  capturedAreas,
  ownedTerritoryAreas,
  ownedByYou,
  ownedByOthers,
  traversedRoads,
  loopCandidate,
  activeTerritoryIds,
  justCapturedTerritoryIds,
  recording,
  isRunning = false,
  onTerritoryPress,
  onSimulationMove,
  simulationPosition,
  activationColor = colors.route,
  captureColorIndex = DEFAULT_CAPTURE_COLOR_INDEX,
  visibleLayers = 'all',
}: Props) {
  const showTerritories = visibleLayers === 'all' || visibleLayers === 'territories';
  const showCaptures = visibleLayers === 'all' || visibleLayers === 'captures';
  const mapRef = useRef<MapRef>(null);
  const cameraRef = useRef<CameraRef>(null);
  const [capturePulseOpacity, setCapturePulseOpacity] = useState(0);
  const capturedKey = [...(justCapturedTerritoryIds ?? [])].sort().join(',');
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
          capture_fill: withAlpha(captureColor, 0.28),
        },
      })),
    } as GeoJSON.FeatureCollection;
  }, [capturedAreas, captureColor]);

  // A deliberately short, state-driven pulse. MapLibre receives only a few
  // layer updates, then the territory settles into its ordinary owner colour.
  useEffect(() => {
    if (!capturedKey) return;
    setCapturePulseOpacity(0.64);
    let phase = false;
    const timer = setInterval(() => {
      phase = !phase;
      setCapturePulseOpacity(phase ? 0.26 : 0.7);
    }, 360);
    const finish = setTimeout(() => {
      clearInterval(timer);
      setCapturePulseOpacity(0);
    }, 2_400);
    return () => {
      clearInterval(timer);
      clearTimeout(finish);
    };
  }, [capturedKey]);

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
            terrain_fill: withAlpha(zoneColor, 0.74),
            fill_color: zoneColor,
            outline_color: zoneColor,
          },
        };
      }),
    };
  }, [colorByTerritory, ownedByYou, ownedByOthers, sourceTerritories]);

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

  const capturedPulseCollection = useMemo((): GeoJSON.FeatureCollection | null => {
    if (!decorated || !justCapturedTerritoryIds?.size) return null;
    const features = decorated.features.filter((feature) =>
      justCapturedTerritoryIds.has(String(feature.properties?.territory_id ?? '')),
    );
    return features.length ? { type: 'FeatureCollection', features } : null;
  }, [decorated, justCapturedTerritoryIds]);

  /**
   * Mute the base map layers so territory zones pop visually.
   * Applied once after the style finishes loading — uses runtime property
   * overrides, so no forked style JSON to maintain.
   */
  const muteBaseMap = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;

    // Mute POI labels — they clutter the game aesthetic.
    void map.setSourceVisibility(false, 'openmaptiles', 'poi');
  }, []);

  const handleTerritoryPress = useCallback(
    (event: { nativeEvent?: { features?: GeoJSON.Feature[] } }) => {
      const feature = event.nativeEvent?.features?.[0];
      const id = feature?.properties?.territory_id ?? feature?.id;
      if (id != null) onTerritoryPress?.(String(id));
    },
    [onTerritoryPress]
  );

  return (
    <View style={styles.container}>
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
        onDidFinishLoadingMap={muteBaseMap}
        onPress={(event) => {
          if (!onSimulationMove) return;
          const [lon, lat] = event.nativeEvent.lngLat;
          onSimulationMove([lon, lat]);
        }}
      >
        <Camera
          ref={cameraRef}
          initialViewState={{
            center: JAYANAGAR_CENTER,
            zoom: DEFAULT_ZOOM,
            pitch: DEFAULT_PITCH,
            bearing: DEFAULT_BEARING,
          }}
          // North-up follows the player without making the whole game world spin.
          trackUserLocation={recording ? 'default' : undefined}
        />

        {/* Real OSM building footprints, rendered as restrained toy-world massing. */}
        <Layer
          id="toy-buildings"
          type="fill-extrusion"
          source="openmaptiles"
          source-layer="building"
          beforeId={MAP_ART.firstRoadLayerId}
          minzoom={14}
          layout={{ visibility: isRunning ? 'none' : 'visible' }}
          paint={{
            'fill-extrusion-color': ['match', ['%', ['to-number', ['coalesce', ['get', 'id'], 0]], 3], 0, '#D6C6A8', 1, '#BDD4B2', '#C8B6D9'],
            'fill-extrusion-height': ['interpolate', ['linear'], ['to-number', ['coalesce', ['get', 'render_height'], ['get', 'height'], 5]], 0, 2, 40, 16],
            'fill-extrusion-base': 0,
            'fill-extrusion-opacity': isRunning ? 0.52 : 0.66,
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
              filter={['!=', ['get', 'kind'], 'park']}
              layout={{ visibility: isRunning ? 'none' : 'visible' }}
              paint={{
                'fill-color': ['get', 'terrain_fill'],
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
                'text-color': isRunning ? '#274B2A' : '#35563B',
                'text-halo-color': '#E7F6D7',
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
            <Layer
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
                'line-opacity': isRunning ? 0.46 : 0.52,
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
            <Layer
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
                'line-opacity': 0.9,
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
        {ownerColouredAreas?.features.length ? (
          <GeoJSONSource id="owned-territory-areas" data={ownerColouredAreas}>
            <Layer
              id="owned-territory-area-fill"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              paint={{
                'fill-color': ['get', 'owner_fill'],
              }}
            />
            <Layer
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
            <Layer
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
                'fill-color': ['get', 'capture_fill'],
              }}
            />
            <Layer
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
            <Layer
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
            <Layer
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

        {/* Server-confirmed capture reveal: flash, then settle to player ownership. */}
        {capturedPulseCollection && capturePulseOpacity > 0 && (
          <GeoJSONSource id="territories-captured" data={capturedPulseCollection}>
            <Layer
              id="territory-captured-flash"
              type="fill"
              beforeId={MAP_ART.firstRoadLayerId}
              paint={{
                'fill-color': withAlpha(colors.route, capturePulseOpacity * 0.42),
              }}
            />
            <Layer
              id="territory-captured-flash-outline"
              type="line"
              layout={{ 'line-join': 'round', 'line-cap': 'round' }}
              paint={{
                'line-color': '#FFFFFF',
                'line-width': 5,
                'line-opacity': capturePulseOpacity,
                'line-blur': 1.5,
              }}
            />
          </GeoJSONSource>
        )}

        {/* ── Live Route — Road Glow Effect ───────────────────── */}
        {/*
         * The clean path (not raw GPS) is rendered as a wide glowing highlight.
         * At zoom 14-16 the glow width is enough to visually fill the road corridor,
         * giving the appearance of the street itself lighting up rather than an
         * arbitrary line drawn on top of the map.
         *
         * Map-matching to exact OSM road centre-lines is a future milestone.
         * The EMA + RDP cleaning means the line hugs roads naturally.
         */}
        {/* Live-only activation. A completed run should persist territory state,
            not leave its GPS-derived corridor network over the home map. */}
        {recording && traversedRoads && (
          <GeoJSONSource id="traversed-roads" data={traversedRoads}>
            {/* Layer 1: Wide ambient atmosphere — the road "corridor" glows */}
            <Layer
              id="traversed-roads-glow-outer"
              type="line"
              paint={{
                'line-color': activationColor,
                'line-width': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  12, 18,
                  15, 28,
                  17, 35,
                ],
                'line-opacity': 0.08,
                'line-blur': 14,
              }}
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            />
            {/* Layer 2: Road-fill glow — vivid, fills the street width */}
            <Layer
              id="traversed-roads-activation"
              type="line"
              paint={{
                'line-color': activationColor,
                'line-width': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  12, 9,
                  15, 14,
                  17, 18,
                ],
                'line-opacity': 0.32,
                'line-blur': 5,
              }}
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            />
          </GeoJSONSource>
        )}

        {!isRunning && loopCandidate && (
          <GeoJSONSource id="loop-candidate" data={loopCandidate}>
            <Layer id="loop-candidate-fill" type="fill" paint={{ 'fill-color': withAlpha(colors.route, 0.1) }} />
            <Layer id="loop-candidate-outline" type="line" layout={{ 'line-join': 'round' }} paint={{ 'line-color': colors.route, 'line-width': 3, 'line-opacity': 0.75, 'line-dasharray': [2, 1] }} />
          </GeoJSONSource>
        )}

        {simulationPosition && (
          <GeoJSONSource id="simulation-runner" data={{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: simulationPosition } }}>
            <Layer id="simulation-runner-glow" type="circle" paint={{ 'circle-radius': 18, 'circle-color': activationColor, 'circle-opacity': 0.2, 'circle-blur': 0.55 }} />
            <Layer id="simulation-runner-dot" type="circle" paint={{ 'circle-radius': 7, 'circle-color': activationColor, 'circle-stroke-width': 3, 'circle-stroke-color': colors.surface }} />
          </GeoJSONSource>
        )}

        {/* ── Custom User Location ───────────────────────────── */}
        <UserLocation animated heading>
          {/* Pulsing outer glow ring */}
          <Layer
            id="user-location-glow"
            type="circle"
            paint={{
              'circle-radius': 24,
              'circle-color': colors.userGlow,
              'circle-opacity': 0.15,
              'circle-blur': 0.7,
            }}
          />
          {/* Middle ring */}
          <Layer
            id="user-location-ring"
            type="circle"
            paint={{
              'circle-radius': 12,
              'circle-color': colors.userGlow,
              'circle-opacity': 0.25,
              'circle-blur': 0.4,
            }}
          />
          {/* Border ring */}
          <Layer
            id="user-location-border"
            type="circle"
            paint={{
              'circle-radius': 7,
              'circle-color': colors.userDotBorder,
              'circle-opacity': 0.9,
            }}
          />
          {/* White center dot */}
          <Layer
            id="user-location-dot"
            type="circle"
            paint={{
              'circle-radius': 4.5,
              'circle-color': colors.userDot,
              'circle-opacity': 1,
            }}
          />
        </UserLocation>
      </Map>

      {/* Required by ODbL at all times, no exceptions. Do not remove. */}
      <Text style={styles.attribution}>{MAP_ATTRIBUTION}</Text>
      <Pressable
        accessibilityLabel="Recenter on your location"
        style={styles.recenter}
        onPress={() => void cameraRef.current?.easeTo({ center: JAYANAGAR_CENTER, zoom: DEFAULT_ZOOM, duration: 350 })}
      >
        <Text style={styles.recenterText}>◎</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  map: { flex: 1 },
  attribution: {
    position: 'absolute',
    bottom: 4,
    right: 6,
    fontSize: 10,
    color: colors.textMuted,
    backgroundColor: 'rgba(255,255,255,0.75)',
    paddingHorizontal: 4,
    borderRadius: 3,
  },
  recenter: { position: 'absolute', right: 14, bottom: 28, width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 5, elevation: 3 },
  recenterText: { fontSize: 24, color: colors.primary },
});
