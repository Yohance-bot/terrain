/** Warm surfaces, ink labels and honey-to-bumblebee accents. */
export const ui = {
  gradientTop: '#FFF5CC',
  gradientBottom: '#FFFFFF',
  surface: '#FFFFFF',
  ink: '#0E1A13',
  ink2: '#4A5750',
  // 4.7:1 on white, so small labels on cards stay legible.
  ink3: '#6B766F',
  line: '#E2E6E0',
  icon: '#C88900',
  iconGradient: ['#A96B00', '#F0B900', '#FFD83D'] as const,
  accent: '#765000',
  accentPressed: '#593C00',
  accentSoft: '#FFF1B8',
  chartCurrent: '#C88900',
  chartPast: '#F5D77E',
  segment: 'rgba(14,26,19,0.07)',
  start: '#FFD42A',
  startInk: '#0E1A13',
  danger: '#B42318',
  scrim: 'rgba(14,26,19,0.32)',
} as const;

/** Manrope, loaded once in the root layout. Weight lives in the family name. */
export const fonts = {
  regular: 'Manrope_400Regular',
  medium: 'Manrope_500Medium',
  semibold: 'Manrope_600SemiBold',
  bold: 'Manrope_700Bold',
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
