/**
 * Ephemeral game events emitted while a run is being recorded. These are UI
 * hints only: they never alter ownership and the server remains the authority
 * when the completed raw run is submitted.
 */
export type RunEvent =
  | { type: 'TERRITORY_ENTERED'; territoryId: string; territoryName: string }
  | { type: 'LOOP_DETECTED'; areaM2: number; territoryIds: string[] }
  | { type: 'CAPTURE_CONFIRMED'; territoryIds: string[] }
  | { type: 'RUN_SAVED_WAITING_FOR_SERVER' }
  | { type: 'RUN_COMPLETE' };

export function runEventCopy(event: RunEvent): string {
  switch (event.type) {
    case 'TERRITORY_ENTERED':
      return `⚡ TERRITORY ENTERED\n${event.territoryName}`;
    case 'LOOP_DETECTED':
      return `LOOP COMPLETE\n+${event.territoryIds.length} ${event.territoryIds.length === 1 ? 'TERRITORY' : 'TERRITORIES'}`;
    case 'CAPTURE_CONFIRMED':
      return `CAPTURE CONFIRMED\n+${event.territoryIds.length} ${event.territoryIds.length === 1 ? 'TERRITORY' : 'TERRITORIES'}`;
    case 'RUN_SAVED_WAITING_FOR_SERVER':
      return 'RUN SAVED\nWAITING FOR SERVER';
    case 'RUN_COMPLETE':
      return 'RUN COMPLETE';
  }
}
