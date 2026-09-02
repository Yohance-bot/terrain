export const colors = {
  background: '#FFFFFF',
  surface: '#FFFFFF',
  text: '#000000',
  textMuted: '#6B7280',
  border: '#E5E7EB',
  primary: '#000000',
  danger: '#DC2626',

  // Territory rendering. Three states only, because ownership in this milestone
  // has three states only: yours, someone else's, nobody's.
  ownedByYou: '#38BDF8',    // bright cyan-blue — matches the highlighted zone glow
  ownedByOther: '#F59E0B',  // warm amber
  unclaimed: '#B8BFC9',
  territoryOutline: '#1F2937',

  // Route and user location
  route: '#00E5FF',          // vivid cyan for the glowing route line
  routeGlow: '#00B8D4',      // slightly deeper cyan for the outer glow
  userDot: '#FFFFFF',        // white center dot
  userDotBorder: '#38BDF8',  // cyan border ring
  userGlow: '#38BDF8',       // pulsing glow color

  // Tab bar
  tabActive: '#2DD4BF',     // teal-green for active tab
  tabInactive: '#9CA3AF',   // muted grey for inactive tabs

  // Start button
  startGreen: '#4ADE80',        // bright green for the start CTA
  startGreenDark: '#16A34A',    // darker green for depth / pressed state
  startGlow: '#22C55E',         // glow ring color

  // Post-run reveal
  revealBg: '#0A0F14',          // deep near-black for the reveal card bg
  revealAccent: '#2DD4BF',      // teal accent for headings
  revealGold: '#FBBF24',        // gold for capture celebration
  revealCardBg: '#111827',      // dark card backgrounds
  revealCardBorder: '#1F2937',  // subtle card borders
} as const;

/**
 * Selectable capture-area colours. Designed to be bright, saturated, and high
 * contrast against the territory zone palette (which is muted/pastel at ~74%
 * opacity). Each user picks one; developers pick independently.
 */
export const CAPTURE_COLOR_PALETTE = [
  '#00E676', // electric green
  '#FF4081', // hot pink
  '#FF6D00', // vivid orange
  '#00E5FF', // cyan (matches route)
  '#D500F9', // bright purple
  '#FFEA00', // electric yellow
  '#1DE9B6', // mint teal
  '#FF3D00', // deep red-orange
] as const;

/** Default capture colour index (electric green). */
export const DEFAULT_CAPTURE_COLOR_INDEX = 0;

export type ColorName = keyof typeof colors;

