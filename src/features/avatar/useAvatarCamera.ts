import { useCallback, useMemo, useRef, useState } from 'react';
import type { LayoutChangeEvent } from 'react-native';
import { useSharedValue, type ISharedValue } from 'react-native-worklets-core';
import { cameraDistance, cameraEye, cameraUp, groundOffset, avatarYaw, type Float3, type MapPose } from './mapCamera';

export type AvatarFrame = { eye: Float3; target: Float3; up: Float3; yaw: number; pose: MapPose; origin: [number, number] };
export type AvatarCamera = {
  frame: ISharedValue<AvatarFrame>;
  placed: boolean;
  onLayout: (event: LayoutChangeEvent) => void;
  track: (pose: MapPose, coordinate: [number, number] | null, heading: number) => void;
  clear: () => void;
};

/** Publish an entire camera atomically. Separate eye/target writes can tear a frame. */
export function useAvatarCamera(): AvatarCamera {
  const frame = useSharedValue<AvatarFrame>({ eye: [0, 1, 0], target: [0, 0, 0], up: [0, 0, -1], yaw: Math.PI, pose: { center: [0, 0], zoom: 0, bearing: 0, pitch: 0 }, origin: [0, 0] });
  const height = useRef(0);
  const last = useRef<{ pose: MapPose; coordinate: [number, number]; heading: number } | null>(null);
  const placedRef = useRef(false);
  const [placed, setPlaced] = useState(false);
  const track = useCallback((pose: MapPose, coordinate: [number, number] | null, heading: number) => {
    if (!coordinate) return;
    last.current = { pose, coordinate, heading };
    if (height.current <= 0) return;
    const ground = groundOffset(pose, coordinate);
    const back = cameraEye(pose.pitch, cameraDistance(height.current));
    const target: Float3 = [-ground.x, 0, -ground.z];
    frame.value = { target, eye: [target[0] + back[0], back[1], target[2] + back[2]], up: cameraUp(pose.pitch), yaw: avatarYaw(heading, pose.bearing), pose, origin: coordinate };
    if (!placedRef.current) { placedRef.current = true; setPlaced(true); }
  }, [frame]);
  const onLayout = useCallback((event: LayoutChangeEvent) => {
    height.current = event.nativeEvent.layout.height;
    if (last.current) track(last.current.pose, last.current.coordinate, last.current.heading);
  }, [track]);
  const clear = useCallback(() => {
    last.current = null;
    if (placedRef.current) { placedRef.current = false; setPlaced(false); }
  }, []);
  return useMemo(() => ({ frame, placed, onLayout, track, clear }), [frame, placed, onLayout, track, clear]);
}
