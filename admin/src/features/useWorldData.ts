import { assignTerritoryColors } from '../../../src/lib/territoryColors';
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../lib/api";
import { ownerColor } from "./world";
export function useWorldData() {
  const territories = useQuery({
    queryKey: ["territories"],
    queryFn: api.getTerritories,
    staleTime: 60000,
  });
  const states = useQuery({
    queryKey: ["territory_states"],
    queryFn: api.getTerritoryState,
    refetchInterval: 15000,
  });
  const captures = useQuery({
    queryKey: ["captures"],
    queryFn: api.getCapturedAreas,
    refetchInterval: 15000,
  });
  const zoneColors = useMemo(() => assignTerritoryColors(territories.data?.features ?? []), [territories.data]);
  const data = useMemo(() => {
    if (!territories.data || !states.data) return undefined;
    const byId = new Map<string, any>(
      states.data.map((s: any) => [s.territory_id, s]),
    );
    return {
      ...territories.data,
      features: territories.data.features.map((f: GeoJSON.Feature) => {
        const state = byId.get(String(f.properties?.territory_id));
        return {
          ...f,
          properties: {
            ...f.properties,
            ...state,
            color: state?.owner_device_id
              ? ownerColor(state.owner_device_id)
              : zoneColors.get(String(f.properties?.territory_id)) ?? "#6B9584",
          },
        };
      }),
    };
  }, [territories.data, states.data, zoneColors]);
  const coloredCaptures = useMemo(
    () =>
      captures.data
        ? {
            ...captures.data,
            features: captures.data.features.map((f: GeoJSON.Feature) => ({
              ...f,
              properties: {
                ...f.properties,
                color: ownerColor(f.properties?.owner_device_id),
              },
            })),
          }
        : undefined,
    [captures.data],
  );
  return {
    territories: data,
    captures: coloredCaptures,
    error: territories.error ?? states.error ?? captures.error,
    loading: territories.isPending || states.isPending,
    updatedAt: states.dataUpdatedAt,
  };
}
