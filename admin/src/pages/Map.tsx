// @ts-nocheck
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import ReactMap, { Source, Layer, FillLayer, LineLayer } from 'react-map-gl/maplibre';
import { api } from '../lib/api';
import 'maplibre-gl/dist/maplibre-gl.css';

// For MVP without an explicit key, we can use a free basemap or a simple generic style.
// Since we don't have a key provided in the prompt, let's use a standard OSM Carto or CartoDB Dark Matter.

const CARTO_DARK = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const territoryFill: FillLayer = {
  id: 'territory-fill',
  type: 'fill',
  paint: {
    'fill-color': [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      '#39FF14', // Neon green on hover
      ['!=', ['get', 'owner_device_id'], null],
      '#00F0FF', // Owned (Neon blue)
      '#2a2a2a'  // Unowned (Dark gray)
    ],
    'fill-opacity': 0.4
  }
};

const territoryLine: LineLayer = {
  id: 'territory-line',
  type: 'line',
  paint: {
    'line-color': '#39FF14',
    'line-width': 1.5,
    'line-opacity': 0.8
  }
};

export default function TerritoryMap() {
  const [hoverInfo, setHoverInfo] = useState<any>(null);

  const { data: territories } = useQuery({
    queryKey: ['territories'],
    queryFn: api.getTerritories,
  });

  const { data: states } = useQuery({
    queryKey: ['territory_states'],
    queryFn: api.getTerritoryState,
    refetchInterval: 10000,
  });

  // Merge state into geojson properties
  const geojsonData = useMemo(() => {
    if (!territories || !states) return null;
    const stateMap = new globalThis.Map(states.map((s: any) => [s.territory_id, s]));
    
    return {
      ...territories,
      features: territories.features.map((f: any) => ({
        ...f,
        properties: {
          ...f.properties,
          owner_device_id: stateMap.get(f.properties.territory_id)?.owner_device_id || null,
        }
      }))
    };
  }, [territories, states]);

  return (
    <div className="h-full w-full relative flex flex-col">
      <div className="absolute top-4 left-4 z-10 bg-card/90 backdrop-blur border border-border p-4 rounded-lg shadow-lg w-80">
        <h2 className="text-xl font-bold text-foreground">Bengaluru MVP</h2>
        <p className="text-sm text-muted-foreground mt-1">
          {territories?.features?.length || 0} Territories Loaded
        </p>
        
        {hoverInfo && (
          <div className="mt-4 pt-4 border-t border-border space-y-2">
            <div>
              <span className="text-xs text-muted-foreground uppercase">Name</span>
              <p className="font-medium text-foreground">{hoverInfo.properties.name}</p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground uppercase">ID</span>
              <p className="font-mono text-xs text-muted-foreground truncate">{hoverInfo.properties.territory_id}</p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground uppercase">Owner</span>
              <p className="font-mono text-xs text-primary truncate">
                {hoverInfo.properties.owner_device_id || 'Unowned'}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground uppercase">Version</span>
              <p className="font-medium text-foreground">v{hoverInfo.properties.version}</p>
            </div>
          </div>
        )}
      </div>

      <ReactMap
        initialViewState={{
          longitude: 77.5946,
          latitude: 12.9716,
          zoom: 11
        }}
        mapStyle={CARTO_DARK}
        interactiveLayerIds={['territory-fill']}
        onMouseMove={(e: any) => {
          if (e.features && e.features.length > 0) {
            setHoverInfo(e.features[0]);
          } else {
            setHoverInfo(null);
          }
        }}
        onMouseLeave={() => setHoverInfo(null)}
      >
        {geojsonData && (
          <Source id="territories" type="geojson" data={geojsonData}>
            <Layer {...territoryFill} />
            <Layer {...territoryLine} />
          </Source>
        )}
      </ReactMap>
    </div>
  );
}
