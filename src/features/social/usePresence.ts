import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';

import { useRecorder } from '@/features/recorder/useRecorder';
import { fetchSharing } from '@/services/api/client';

import { linkRecorderFixes, useSocial } from './useSocial';

/**
 * Decides when the app reports position at all.
 *
 * Presence is never a background default. It runs while the player is
 * recording, while a race is live, or while they have chosen to share with at
 * least one friend — and stops as soon as none of those is true.
 */
export function usePresence(): { sharingWithCount: number; refreshSharing: () => void } {
  const status = useRecorder((state) => state.status);
  const races = useSocial((state) => state.races);
  const [sharingWithCount, setSharingWithCount] = useState(0);

  const refreshSharing = useCallback(() => {
    void fetchSharing()
      .then((overview) =>
        setSharingWithCount(
          overview.sharing_with.filter((entry) => entry.share_location).length
        )
      )
      .catch(() => setSharingWithCount(0));
  }, []);

  useFocusEffect(
    useCallback(() => {
      refreshSharing();
      void useSocial.getState().refreshLive();
    }, [refreshSharing])
  );

  const recording = status === 'recording';
  const racing = races.some((race) => race.status === 'running');
  const shouldReport = recording || racing || sharingWithCount > 0;

  useEffect(() => {
    const social = useSocial.getState();
    if (shouldReport) {
      // While recording, the recorder's own GPS watch feeds the store; outside
      // a run there is nothing watching, so presence starts its own.
      void social.startPresence({ ownWatch: !recording });
    } else {
      void social.stopPresence();
    }
  }, [shouldReport, recording]);

  // The recorder is already watching GPS during a run; forward its fixes rather
  // than opening a second subscription on the same hardware.
  useEffect(() => linkRecorderFixes(), []);

  useEffect(() => () => void useSocial.getState().stopPresence(), []);

  return { sharingWithCount, refreshSharing };
}
