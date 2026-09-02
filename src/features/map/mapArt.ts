export const MAP_ART = {
  firstRoadLayerId: 'tunnel_motorway_link_casing',
  roadLayerIds: [
    'road_path_pedestrian', 'road_service_track', 'road_link', 'road_minor',
    'road_minor_centerline', 'road_secondary_tertiary',
    'road_secondary_tertiary_centerline', 'road_trunk_primary',
    'road_trunk_primary_centerline',
  ],
  park: {
    unclaimed: '#65BF58',
    ownedByYou: '#58C991',
    ownedByOther: '#79B95B',
    highlight: '#C2EDB2',
  },
} as const;
