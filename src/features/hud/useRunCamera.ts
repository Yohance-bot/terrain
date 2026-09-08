import { DEFAULT_BEARING, DEFAULT_PITCH, DEFAULT_ZOOM } from '@/constants/config';
import type { CameraRef, ViewStateChangeEvent } from '@maplibre/maplibre-react-native';
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { useRunCues } from './useRunCues';
import { followPose, type FollowPose } from './camera';
import type { RunFix } from './telemetry';

/** One writer for camera movement. Gestures always win over follow and celebrations. */
export function useRunCamera(camera: RefObject<CameraRef | null>, fix: RunFix | null, recording: boolean, active: boolean, reducedMotion: boolean, economy: boolean, ready: boolean) {
  const [following, setFollowing] = useState(true);
  const [restoration, setRestoration] = useState(0);
  const pose = useRef<FollowPose>({ bearing: DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: DEFAULT_PITCH });
  const latestFix = useRef(fix); latestFix.current = fix;
  const lastMove = useRef<{ ts: number; coordinate: [number, number] } | null>(null);
  const holdUntil = useRef(0);
  const cue = useRunCues(s => s.cue);
  const played = useRef<string | null>(null);
  useEffect(() => { if (recording) { setFollowing(true); lastMove.current = null; pose.current = { bearing: DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: DEFAULT_PITCH }; } }, [recording]);
  useEffect(() => {
    if (!active || !ready || !following || !fix || Date.now() - fix.ts > 10_000 || Date.now() < holdUntil.current) return;
    const previous = lastMove.current;
    const stationary = previous && fix.speedMps < 0.6 && Math.hypot((fix.coordinate[0] - previous.coordinate[0]) * Math.cos(fix.coordinate[1] * Math.PI / 180), fix.coordinate[1] - previous.coordinate[1]) * 111_320 < 3;
    if (stationary && previous && Date.now() - previous.ts < 5000) return;
    pose.current = recording ? followPose(pose.current, fix, reducedMotion || economy) : { bearing: reducedMotion || economy ? 0 : DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: reducedMotion || economy ? 0 : DEFAULT_PITCH };
    camera.current?.easeTo({ center: fix.coordinate, ...pose.current, duration: reducedMotion ? 0 : economy ? 500 : 850 });
    lastMove.current = { ts: Date.now(), coordinate: fix.coordinate };
  }, [camera, fix, recording, active, reducedMotion, economy, following, ready, restoration]);
  useEffect(() => {
    if (!cue || cue.kind === 'checkpoint' || played.current === cue.id || Date.now() - cue.createdAt > 3500 || !ready || !active || !following || reducedMotion || economy) return;
    played.current = cue.id;
    holdUntil.current = Date.now() + 2600;
    camera.current?.easeTo({ center: cue.coordinate, zoom: pose.current.zoom - 0.65, pitch: 12, bearing: pose.current.bearing, duration: 750 });
    const timer = setTimeout(() => {
      holdUntil.current = 0;
      const current = latestFix.current;
      if (current) camera.current?.easeTo({ center: current.coordinate, ...pose.current, duration: 750 });
      setRestoration(n => n + 1);
    }, 2600);
    return () => { clearTimeout(timer); holdUntil.current = 0; };
  }, [cue, active, following, reducedMotion, economy, ready, camera]);
  const onGesture = useCallback((event: ViewStateChangeEvent) => {
    if (event.userInteraction) { setFollowing(false); holdUntil.current = 0; }
  }, []);
  const recenter = useCallback(() => {
    const current = latestFix.current;
    if (!current || !ready) return;
    holdUntil.current = 0; lastMove.current = null;
    pose.current = { bearing: reducedMotion || economy ? 0 : DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: reducedMotion || economy ? 0 : DEFAULT_PITCH };
    setFollowing(true);
    camera.current?.easeTo({ center: current.coordinate, ...pose.current, duration: reducedMotion ? 0 : 500 });
  }, [camera, ready, reducedMotion, economy]);
  return { following, onGesture, recenter };
}
