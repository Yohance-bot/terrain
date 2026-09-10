import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { memo, useMemo } from 'react';

import { colors } from '@/theme';
import type { GhostSummary } from '@/services/api/types';

import { useGhostRace } from './useGhostRace';
import { useSocial } from './useSocial';

/**
 * Everything social that appears on the map.
 *
 * Broadcast ghosts are deliberately not drawn unless the player turns their
 * layer on: the map's job is to show the world and your own run, and covering
 * it in other people's benchmarks buries that.
 */

type Props = {
  /** Public ghosts, only supplied when the player has enabled that layer. */
  nearbyGhosts?: GhostSummary[];
};

const FRIEND_COLOR = '#F5A524';
const FRIEND_RUNNING_COLOR = '#4ADE80';
const RACE_PIN_COLOR = '#FF4081';
const GHOST_COLOR = '#A5B4FC';

function pointFeature(
  coordinate: [number, number],
  properties: Record<string, unknown>
): GeoJSON.Feature<GeoJSON.Point> {
  return { type: 'Feature', properties, geometry: { type: 'Point', coordinates: coordinate } };
}

export const SocialMapLayers = memo(function SocialMapLayers({ nearbyGhosts }: Props) {
  const friends = useSocial((state) => state.friends);
  const races = useSocial((state) => state.races);
  const ghost = useGhostRace((state) => state.ghost);
  const ghostState = useGhostRace((state) => state.ghostState);

  const friendPoints = useMemo<GeoJSON.FeatureCollection<GeoJSON.Point>>(
    () => ({
      type: 'FeatureCollection',
      features: friends.map((friend) =>
        pointFeature([friend.lon, friend.lat], {
          name: friend.account.display_name,
          running: friend.is_running,
        })
      ),
    }),
    [friends]
  );

  const racePins = useMemo<GeoJSON.FeatureCollection<GeoJSON.Point>>(
    () => ({
      type: 'FeatureCollection',
      features: races
        .filter((race) => race.status === 'running')
        .map((race) =>
          pointFeature([race.pin_lon, race.pin_lat], { label: race.pin_label ?? 'Race' })
        ),
    }),
    [races]
  );

  const ghostPoints = useMemo<GeoJSON.FeatureCollection<GeoJSON.Point>>(
    () => ({
      type: 'FeatureCollection',
      features: (nearbyGhosts ?? []).map((available) =>
        pointFeature([available.start_lon, available.start_lat], { name: available.name })
      ),
    }),
    [nearbyGhosts]
  );

  const ghostRoute = useMemo<GeoJSON.Feature<GeoJSON.LineString> | null>(() => {
    if (!ghost || ghost.path.length < 2) return null;
    return {
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'LineString',
        coordinates: ghost.path.map((point) => [point[0], point[1]]),
      },
    };
  }, [ghost]);

  return (
    <>
      {/* The route being raced, under everything else that moves. */}
      {ghostRoute && (
        <GeoJSONSource id="ghost-route" data={ghostRoute}>
          <Layer
            beforeId="hud-base-anchor"
            id="ghost-route-line"
            type="line"
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
            paint={{
              'line-color': GHOST_COLOR,
              'line-width': 4,
              'line-opacity': 0.7,
              'line-dasharray': [3, 2],
            }}
          />
        </GeoJSONSource>
      )}

      {ghostState && (
        <GeoJSONSource
          id="ghost-runner"
          data={pointFeature(ghostState.coordinate, { progress: ghostState.progress })}>
          <Layer
            beforeId="hud-player-anchor"
            id="ghost-runner-glow"
            type="circle"
            paint={{
              'circle-radius': 15,
              'circle-color': GHOST_COLOR,
              'circle-opacity': 0.25,
              'circle-blur': 0.6,
            }}
          />
          <Layer
            beforeId="hud-player-anchor"
            id="ghost-runner-dot"
            type="circle"
            paint={{
              'circle-radius': 6,
              'circle-color': GHOST_COLOR,
              'circle-stroke-width': 2,
              'circle-stroke-color': colors.surface,
            }}
          />
        </GeoJSONSource>
      )}

      {/* Available public ghosts. Only present when the layer is switched on. */}
      {ghostPoints.features.length > 0 && (
        <GeoJSONSource id="ghosts-nearby" data={ghostPoints}>
          <Layer
            beforeId="hud-base-anchor"
            id="ghosts-nearby-dot"
            type="circle"
            paint={{
              'circle-radius': 6,
              'circle-color': GHOST_COLOR,
              'circle-opacity': 0.85,
              'circle-stroke-width': 2,
              'circle-stroke-color': '#1E293B',
            }}
          />
        </GeoJSONSource>
      )}

      {racePins.features.length > 0 && (
        <GeoJSONSource id="race-pins" data={racePins}>
          {/* The arrival radius is drawn, so "close enough" is visible rather
              than something a runner has to guess at. */}
          <Layer
            beforeId="hud-base-anchor"
            id="race-pin-radius"
            type="circle"
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 6, 18, 40],
              'circle-color': RACE_PIN_COLOR,
              'circle-opacity': 0.18,
            }}
          />
          <Layer
            beforeId="hud-player-anchor"
            id="race-pin-dot"
            type="circle"
            paint={{
              'circle-radius': 8,
              'circle-color': RACE_PIN_COLOR,
              'circle-stroke-width': 3,
              'circle-stroke-color': colors.surface,
            }}
          />
        </GeoJSONSource>
      )}

      {friendPoints.features.length > 0 && (
        <GeoJSONSource id="friend-positions" data={friendPoints}>
          <Layer
            beforeId="hud-player-anchor"
            id="friend-position-dot"
            type="circle"
            paint={{
              // Running friends read differently from friends simply out and
              // sharing, which is the distinction that matters on a glance.
              'circle-color': ['case', ['get', 'running'], FRIEND_RUNNING_COLOR, FRIEND_COLOR],
              'circle-radius': 7,
              'circle-stroke-width': 3,
              'circle-stroke-color': colors.surface,
            }}
          />
          <Layer
            beforeId="hud-player-anchor"
            id="friend-position-label"
            type="symbol"
            layout={{
              'text-field': ['get', 'name'],
              'text-size': 11,
              'text-offset': [0, 1.4],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#E2E8F0',
              'text-halo-color': '#0F172A',
              'text-halo-width': 1.5,
            }}
          />
        </GeoJSONSource>
      )}
    </>
  );
});
