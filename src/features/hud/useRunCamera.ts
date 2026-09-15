import { DEFAULT_BEARING, DEFAULT_PITCH, DEFAULT_ZOOM } from '@/constants/config';
import type { CameraRef, ViewStateChangeEvent } from '@maplibre/maplibre-react-native';
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { useRunCues } from './useRunCues';
import { followPose, type FollowPose } from './camera';
import { followDurationMs, metresApart, shouldFollowFix, SNAP_IF_FARTHER_M } from './cameraFollow';
import type { RunFix } from './telemetry';

/** One writer for camera movement. Gestures always win over follow and celebrations. */
export function useRunCamera(camera: RefObject<CameraRef | null>, fix: RunFix | null, recording: boolean, active: boolean, reducedMotion: boolean, economy: boolean, ready: boolean) {
  const [following, setFollowing] = useState(true);
  const [restoration, setRestoration] = useState(0);
  const pose = useRef<FollowPose>({ bearing: DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: DEFAULT_PITCH });
  const latestFix = useRef(fix); latestFix.current = fix;
  const lastMove = useRef<{ ts: number; coordinate: [number, number] } | null>(null);
  const holdUntil = useRef(0);
  const snapped = useRef(false);
  const cue = useRunCues(s => s.cue);
  const played = useRef<string | null>(null);
  useEffect(() => { if (recording) { setFollowing(true); lastMove.current = null; pose.current = { bearing: DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: DEFAULT_PITCH }; } }, [recording]);
  useEffect(() => {
    if (!active || !ready || !following || !fix || !shouldFollowFix(Date.now(), fix, snapped.current, holdUntil.current)) return;
    const previous = lastMove.current;
    const stationary = previous && fix.speedMps < 0.6 && Math.hypot((fix.coordinate[0] - previous.coordinate[0]) * Math.cos(fix.coordinate[1] * Math.PI / 180), fix.coordinate[1] - previous.coordinate[1]) * 111_320 < 3;
    if (stationary && previous && Date.now() - previous.ts < 5000) return;
    pose.current = recording ? followPose(pose.current, fix, reducedMotion || economy) : { bearing: reducedMotion || economy ? 0 : DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: reducedMotion || economy ? 0 : DEFAULT_PITCH };
    const far = !previous || metresApart(previous.coordinate, fix.coordinate) > SNAP_IF_FARTHER_M;
    const duration = followDurationMs(snapped.current, far, reducedMotion, economy);
    const next = { center: fix.coordinate, ...pose.current };
    if (duration === 0) camera.current?.jumpTo(next);
    else camera.current?.easeTo({ ...next, duration });
    snapped.current = true;
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
    // Android fires a "user" region change while the map is still loading and
    // while we jump to GPS. Treating that as a pan left the camera in Jayanagar
    // with the avatar standing on the player.
    if (!snapped.current) return;
    if (event.userInteraction) { setFollowing(false); holdUntil.current = 0; }
  }, []);
  const recenter = useCallback(() => {
    const current = latestFix.current;
    if (!current || !ready) return;
    holdUntil.current = 0; lastMove.current = null;
    pose.current = { bearing: reducedMotion || economy ? 0 : DEFAULT_BEARING, zoom: DEFAULT_ZOOM, pitch: reducedMotion || economy ? 0 : DEFAULT_PITCH };
    setFollowing(true);
    camera.current?.jumpTo({ center: current.coordinate, ...pose.current });
    snapped.current = true;
  }, [camera, ready, reducedMotion, economy]);
  return { following, onGesture, recenter };
}
