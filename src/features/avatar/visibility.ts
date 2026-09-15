import { create } from 'zustand';
/** IDs enter this set only after the shared GLB has loaded. */
export const useAvatarVisibility = create<{ ids: string[] }>(() => ({ ids: [] }));
