/**
 * One categorical ramp reused everywhere, so a gas keeps its colour across
 * every chart in the app.
 *
 * Kept apart from `Charts.tsx` so the PDF builder can print a gas in its screen
 * colour without importing recharts into the export chunk.
 */
export const GAS_COLORS: Record<string, string> = {
  H2: '#1E72BC',
  CH4: '#E8833A',
  CO: '#2E9E6B',
  CO2: '#C0504D',
  C2H4: '#8064A2',
  C2H6: '#9C6B4E',
  C2H2: '#D64545',
  O2: '#7F8C99',
  N2: '#B0A63C',
}
