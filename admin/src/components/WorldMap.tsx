import { buildingTerritoryPaint } from '../../../src/features/map/territoryAppearance';
import { useEffect, useRef, useState } from "react";
import {
  type GeoJSONSource,
  type Map as MapInstance,
  type ExpressionSpecification,
} from "maplibre-gl";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { createAvatarLayer, HOLOGRAM_COLOR, type AvatarLayer } from "../features/avatar";
import {
  BUILDING_HEIGHT,
  buildRoofDetails,
  CENTER,
  EMPTY,
  groundBorderLayers,
  RUN_TRAIL_COLOR,
  STRUCTURE_OPACITY,
  worldPalette,
  smoothTrail,
  worldStyle,
  illuminateStreets,
} from "../features/world";
maplibregl.setWorkerUrl(workerUrl);

type Props = {
  territories?: GeoJSON.FeatureCollection;
  captures?: GeoJSON.FeatureCollection;
  route?: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  position?: [number, number];
  /** Other runners and pins the lab is showing alongside the driven runner. */
  markers?: { lon: number; lat: number; label: string; color: string }[];
  /** How the driven runner is drawn, mirroring the phone's setting. */
  playerMarker?: "avatar" | "classic";
  /** Drives the avatar's clip, the way speed does on the phone. */
  running?: boolean;
  night?: boolean;
  streetMode?: boolean;
  follow?: boolean;
  onSelect?: (feature: GeoJSON.Feature) => void;
  onMap?: (map: MapInstance) => void;
};
export default function WorldMap(props: Props) {
  const element = useRef<HTMLDivElement>(null),
    map = useRef<MapInstance | null>(null),
    latest = useRef(props);
  latest.current = props;
  const [error, setError] = useState("");
  useEffect(() => {
    if (!element.current) return;
    const m = new maplibregl.Map({
      container: element.current,
      style: worldStyle(props.night),
      center: props.position ?? CENTER,
      zoom: 17.2,
      pitch: 55,
      bearing: -18,
      maxPitch: 65,
      attributionControl: { compact: true },
    });
    map.current = m;
    const marker = new maplibregl.Marker({ color: RUN_TRAIL_COLOR });
    // Extra markers are recreated whenever the set changes. There are only ever
    // a handful in the lab, so pooling them would cost more than it saves.
    let extras: maplibregl.Marker[] = [];
    m.addControl(new maplibregl.NavigationControl(), "bottom-right");
    let ready = false,
      lastRoofs = 0;
    let avatar: AvatarLayer | undefined;
    const sent = new Map<string, unknown>();
    function update() {
      if (!ready) return;
      const p = latest.current;
      for (const [id, data] of [
        ["territories", p.territories ?? EMPTY],
        ["captures", p.captures ?? EMPTY],
      ] as const) {
        if (sent.get(id) !== data) {
          (m.getSource(id) as GeoJSONSource).setData(data);
          sent.set(id, data);
        }
      }
      let route = p.route ?? {
        type: "FeatureCollection" as const,
        features: [],
      };
      if (p.streetMode && route.features.length) {
        const layers = m
          .getStyle()
          .layers.filter(
            (l) =>
              l.type === "line" &&
              /^(road|bridge|tunnel)_/.test(l.id) &&
              !/casing|centerline|rail|hatching|arrow/.test(l.id),
          )
          .map((l) => l.id);
        const streets = illuminateStreets(
          route,
          m.queryRenderedFeatures({ layers }),
        );
        route = {
          type: "FeatureCollection",
          features: [
            ...streets.streets.features,
            ...streets.unmatched.features,
          ],
        };
      }
      if (
        sent.get("route") !== p.route ||
        sent.get("street") !== p.streetMode
      ) {
        (m.getSource("route") as GeoJSONSource).setData(smoothTrail(route));
        sent.set("route", p.route);
        sent.set("street", p.streetMode);
      }
      const asAvatar = p.playerMarker !== "classic";
      if (p.position && !asAvatar) marker.setLngLat(p.position).addTo(m);
      else marker.remove();
      if (p.position && p.follow) m.easeTo({ center: p.position, duration: 500 });

      // The hologram is a map layer here too, so it lies on the road, tilts
      // with the camera and is drawn under the character rather than around it.
      const feet: GeoJSON.FeatureCollection =
        p.position && asAvatar
          ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p.position } }] }
          : EMPTY;
      if (sent.get("feet") !== p.position || sent.get("feet-mode") !== asAvatar) {
        sent.set("feet", p.position);
        sent.set("feet-mode", asAvatar);
        (m.getSource("player") as GeoJSONSource).setData(feet);
      }
      avatar?.setPosition(p.position && asAvatar ? p.position : null);
      avatar?.setRunning(Boolean(p.running));

      const wanted = p.markers ?? [];
      const signature = JSON.stringify(wanted);
      if (sent.get("markers") !== signature) {
        sent.set("markers", signature);
        for (const extra of extras) extra.remove();
        extras = wanted.map((entry) => {
          const element = document.createElement("div");
          element.className = "map-pin";
          element.style.background = entry.color;
          element.title = entry.label;
          return new maplibregl.Marker({ element })
            .setLngLat([entry.lon, entry.lat])
            .setPopup(new maplibregl.Popup({ offset: 12 }).setText(entry.label))
            .addTo(m);
        });
      }
    }
    function roofs() {
      if (
        !ready ||
        m.getZoom() < 16 ||
        Date.now() - lastRoofs < 2500 ||
        document.hidden
      )
        return;
      lastRoofs = Date.now();
      const c = m.getCenter(),
        b = m.getBounds();
      const buildingFeatures = m.queryRenderedFeatures({
        layers: ["world-buildings"],
      });
      const zones = [...(latest.current.captures?.features ?? []), ...(latest.current.territories?.features ?? [])];
      m.setPaintProperty("world-buildings", "fill-extrusion-color", buildingTerritoryPaint(buildingFeatures, zones, "#C6DEDC"));
      const data = buildRoofDetails(buildingFeatures, [c.lng, c.lat], false, [
        b.getWest(),
        b.getSouth(),
        b.getEast(),
        b.getNorth(),
      ], zones);
      (m.getSource("roofs") as GeoJSONSource).setData(data);
    }
    m.on("load", () => {
      const anchor = m.getLayer("hud-base-anchor")
        ? "hud-base-anchor"
        : undefined;
      m.addLayer(
        {
          id: "world-buildings",
          type: "fill-extrusion",
          source: "openmaptiles",
          "source-layer": "building",
          minzoom: 16,
          paint: {
            "fill-extrusion-color": "#C6DEDC",
            "fill-extrusion-height": BUILDING_HEIGHT as ExpressionSpecification,
            "fill-extrusion-opacity": STRUCTURE_OPACITY,
          },
        },
        anchor,
      );
      // Kerbs and building borders, built by the same code as the phone's so the
      // two maps cannot drift apart.
      const borders = groundBorderLayers(m.getStyle().layers, worldPalette(latest.current.night));
      m.addLayer(borders.building.layer, borders.building.beforeId);
      for (const { layer, beforeId } of borders.kerbs) m.addLayer(layer, beforeId);
      m.addSource("roofs", { type: "geojson", data: EMPTY });
      m.addLayer(
        {
          id: "roof-details",
          type: "fill-extrusion",
          source: "roofs",
          minzoom: 16,
          paint: {
            "fill-extrusion-base": ["get", "base"],
            "fill-extrusion-height": ["get", "height"],
            "fill-extrusion-color": ["coalesce", ["get", "color"], [
              "match",
              ["get", "tone"],
              "aqua",
              "#7EBCBD",
              "garden",
              "#80C89B",
              "clay",
              "#D6A68B",
              "slate",
              "#5C948B",
              "#E4F0ED",
            ]],
          },
        },
        anchor,
      );
      for (const id of ["territories", "captures", "route"])
        m.addSource(id, { type: "geojson", data: EMPTY });
      m.addLayer(
        {
          id: "territory-fill",
          type: "fill",
          source: "territories",
          paint: {
            "fill-color": ["coalesce", ["get", "color"], "#90ACA1"],
            "fill-opacity": ["interpolate", ["linear"], ["zoom"], 12, .58, 16, .38, 18, .22],
          },
        },
        anchor,
      );
      m.addLayer(
        {
          id: "territory-border",
          type: "line",
          source: "territories",
          paint: {
            "line-color": ["coalesce", ["get", "color"], "#668A7F"],
            "line-width": 2.2,
          },
        },
        anchor,
      );
      m.addLayer(
        {
          id: "capture-fill",
          type: "fill",
          source: "captures",
          paint: { "fill-color": ["get", "color"], "fill-opacity": ["interpolate", ["linear"], ["zoom"], 12, .62, 16, .44, 18, .3] },
        },
        anchor,
      );
      m.addLayer(
        {
          id: "capture-border",
          type: "line",
          source: "captures",
          paint: { "line-color": ["get", "color"], "line-width": 3 },
        },
        anchor,
      );
      m.addLayer({
        id: "route-glow",
        type: "line",
        source: "route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": RUN_TRAIL_COLOR,
          "line-width": 16,
          "line-blur": 7,
          "line-opacity": 0.55,
        },
      });
      m.addSource("player", { type: "geojson", data: EMPTY });
      // Same three rings as the phone: a soft spill, a wide outline and a lit
      // pad, so the character reads as standing in light rather than on a dot.
      m.addLayer({
        id: "player-hologram-glow",
        type: "circle",
        source: "player",
        paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 9, 18, 22], "circle-color": HOLOGRAM_COLOR, "circle-opacity": 0.18, "circle-blur": 1 },
      });
      m.addLayer({
        id: "player-hologram-ring",
        type: "circle",
        source: "player",
        paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 8, 18, 19], "circle-color": HOLOGRAM_COLOR, "circle-opacity": 0, "circle-stroke-width": 1.2, "circle-stroke-color": HOLOGRAM_COLOR, "circle-stroke-opacity": 0.32 },
      });
      m.addLayer({
        id: "player-hologram-pad",
        type: "circle",
        source: "player",
        paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 6, 18, 13], "circle-color": HOLOGRAM_COLOR, "circle-opacity": 0.3, "circle-stroke-width": 1.5, "circle-stroke-color": HOLOGRAM_COLOR, "circle-stroke-opacity": 0.85 },
      });
      m.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": RUN_TRAIL_COLOR, "line-width": 5 },
      });
      avatar = createAvatarLayer();
      m.addLayer(avatar);
      ready = true;
      update();
      roofs();
      latest.current.onMap?.(m);
    });
    m.on("click", "territory-fill", (e) => {
      const feature = e.features?.[0];
      if (feature) latest.current.onSelect?.(feature);
    });
    m.on("mouseenter", "territory-fill", () => {
      m.getCanvas().style.cursor = "pointer";
    });
    m.on("mouseleave", "territory-fill", () => {
      m.getCanvas().style.cursor = "";
    });
    m.on("idle", roofs);
    m.on("error", (e) => {
      if (!m.isStyleLoaded()) setError(e.error.message);
    });
    const timer = setInterval(() => {
      if (!document.hidden) {
        update();
        roofs();
      }
    }, 1000);
    const resize = new ResizeObserver(() => m.resize());
    resize.observe(element.current);
    return () => {
      clearInterval(timer);
      resize.disconnect();
      marker.remove();
      m.remove();
      map.current = null;
    };
    // Style toggles intentionally rebuild the scene; data changes update sources.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.night]);
  return (
    <div className="world-canvas">
      <div ref={element} className="map-surface" />
      {error && <div className="map-error">Map unavailable: {error}</div>}
    </div>
  );
}
