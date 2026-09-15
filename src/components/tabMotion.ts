import { create } from 'zustand';
export type TabAnimation = 'slide_from_left' | 'slide_from_right';
const order = ['map', 'friends', 'profile'];
/** Pop reverses the departing screen's animation; replacement does not. */
export function tabAnimation(from: string, to: string): TabAnimation {
  if (to === 'map') return 'slide_from_right';
  return order.indexOf(to) < order.indexOf(from) ? 'slide_from_left' : 'slide_from_right';
}
export const useTabMotion = create<{ animation: TabAnimation }>(() => ({ animation: 'slide_from_right' }));
