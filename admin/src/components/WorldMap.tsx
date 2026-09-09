import { useEffect, useRef, useState } from "react";
import {
  type GeoJSONSource,
  type Map as MapInstance,
  type ExpressionSpecification,
} from "maplibre-gl";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import {
  BUILDING_HEIGHT,
  buildRoofDetails,
  CENTER,
  EMPTY,
  RUN_TRAIL_COLOR,
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
    m.addControl(new maplibregl.NavigationControl(), "bottom-right");
    let ready = false,
      lastRoofs = 0;
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
      if (p.position) {
        marker.setLngLat(p.position).addTo(m);
        if (p.follow) m.easeTo({ center: p.position, duration: 500 });
      } else marker.remove();
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
      const data = buildRoofDetails(buildingFeatures, [c.lng, c.lat], false, [
        b.getWest(),
        b.getSouth(),
        b.getEast(),
        b.getNorth(),
      ]);
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
            "fill-extrusion-opacity": 0.96,
          },
        },
        anchor,
      );
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
            "fill-extrusion-color": [
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
            ],
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
            "fill-opacity": 0.17,
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
          paint: { "fill-color": ["get", "color"], "fill-opacity": 0.3 },
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
      m.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": RUN_TRAIL_COLOR, "line-width": 5 },
      });
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
