/**
 * The app's own palette, separate from the map's.
 *
 * The map keeps `colors` and the lighting palette; everything around it — tab
 * bar, profile, friends, settings — reads from here. Teal is the athlete's
 * colour: icons carry `icon`, and `accent` is the same hue deepened until white
 * text and small labels stay legible on it.
 */
export const ui = {
  gradientTop: '#ADEBB3',
  gradientBottom: '#FFFFFF',
  surface: '#FFFFFF',
  ink: '#0E1A13',
  ink2: '#4A5750',
  // 4.7:1 on white, so small labels on cards stay legible.
  ink3: '#6B766F',
  line: '#E2E6E0',
  icon: '#1ABC9C',
  accent: '#0E7C66',
  accentPressed: '#0A5F4E',
  accentSoft: '#D4F3EA',
  chartCurrent: '#1ABC9C',
  chartPast: '#A6E3D3',
  segment: 'rgba(14,26,19,0.07)',
  start: '#C5F26A',
  startInk: '#0E1A13',
  danger: '#B42318',
  scrim: 'rgba(14,26,19,0.32)',
} as const;

/** Barlow, loaded once in the root layout. Weight lives in the family name. */
export const fonts = {
  regular: 'Barlow_400Regular',
  medium: 'Barlow_500Medium',
  semibold: 'Barlow_600SemiBold',
  bold: 'Barlow_700Bold',
} as const;

export const typeScale = {
  screenTitle: { fontFamily: fonts.bold, fontSize: 32, letterSpacing: -0.4, color: ui.ink },
  navTitle: { fontFamily: fonts.semibold, fontSize: 17, color: ui.ink },
  sectionLabel: { fontFamily: fonts.semibold, fontSize: 12, letterSpacing: 1, color: ui.ink2 },
  rowTitle: { fontFamily: fonts.semibold, fontSize: 16, color: ui.ink },
  body: { fontFamily: fonts.regular, fontSize: 15, color: ui.ink },
  meta: { fontFamily: fonts.regular, fontSize: 14, color: ui.ink2 },
  small: { fontFamily: fonts.medium, fontSize: 12, color: ui.ink3 },
  figure: { fontFamily: fonts.semibold, fontSize: 22, letterSpacing: -0.2, color: ui.ink },
  hero: { fontFamily: fonts.semibold, fontSize: 40, letterSpacing: -0.8, color: ui.ink },
} as const;
