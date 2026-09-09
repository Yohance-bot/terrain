import type { StyleSpecification } from "maplibre-gl";
import baseStyle from "../../../assets/map/liberty-run.json";
import { lightingPalette } from "../../../src/features/hud/lighting";
import { roadPaintColor } from "../../../src/features/map/roadStyle";
export {
  buildRoofDetails,
  BUILDING_HEIGHT,
} from "../../../src/features/map/worldGeometry";
export {
  smoothTrail,
  RUN_TRAIL_COLOR,
} from "../../../src/features/hud/smoothTrail";
export { illuminateStreets } from "../../../src/features/map/streetMatching";
export const EMPTY: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};
export const CENTER: [number, number] = [77.5838, 12.925];
export function ownerColor(id: unknown) {
  const slot = String(id).match(
    /^10000000-0000-4000-8000-00000000000([123])$/,
  )?.[1];
  return slot ? ["#22C55E", "#A855F7", "#F97316"][Number(slot) - 1] : "#F59E0B";
}
export function worldStyle(night = false): StyleSpecification {
  const style = structuredClone(baseStyle) as unknown as StyleSpecification;
  const palette = lightingPalette(new Date(2026, 8, 9, night ? 22 : 12), null);
  for (const layer of style.layers) {
    if (layer.id.startsWith("hud-")) continue;
    if (layer.type === "background")
      layer.paint = { ...layer.paint, "background-color": palette.background };
    if (layer.type === "fill")
      layer.paint = {
        ...layer.paint,
        "fill-color": /water/.test(layer.id)
          ? palette.water
          : /park|wood|grass|cemetery/.test(layer.id)
            ? palette.park
            : palette.land,
      };
    if (layer.type === "line")
      layer.paint = {
        ...layer.paint,
        "line-color": /^(road|bridge|tunnel)_/.test(layer.id)
          ? roadPaintColor(layer.id, palette)
          : palette.casing,
      };
    if (layer.type === "symbol") {
      layer.paint = {
        ...layer.paint,
        "text-color": palette.label,
        "text-halo-color": palette.halo,
      };
      if (/^poi/.test(layer.id))
        layer.layout = { ...layer.layout, visibility: "none" };
    }
  }
  return style;
}
