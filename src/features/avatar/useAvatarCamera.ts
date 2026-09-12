import { useCallback, useRef, useState } from 'react';
import type { LayoutChangeEvent } from 'react-native';
import { useSharedValue, type ISharedValue } from 'react-native-worklets-core';

import {
  cameraDistance,
  cameraEye,
  cameraUp,
  groundOffset,
  type Float3,
  type MapPose,
} from './mapCamera';

/**
 * The map's camera, handed to Filament without going through React.
 *
 * The avatar has to be re-aimed every time the map moves, and the map moves on
 * the UI thread at the display's refresh rate. Routing that through component
 * state meant a full re-render of the map screen per frame — dozens of layers
 * reconciled to move one character — and on a phone with real work to do the
 * renders coalesce, the events queue behind them, and the avatar stops moving
 * with the ground it is standing on. It looks pinned to the glass.
 *
 * So the pose lands in shared values instead. Handling an event is now three
 * assignments and some trigonometry; the Filament render callback reads the
 * latest values on the render thread every frame, and no React render happens
 * during a pan at all.
 */

export type AvatarCamera = {
  eye: ISharedValue<Float3>;
  target: ISharedValue<Float3>;
  up: ISharedValue<Float3>;
  /** True once a real camera has been seen. Changes once, not per frame. */
  placed: boolean;
  /** Measures the surface the avatar is drawn on. */
  onLayout: (event: LayoutChangeEvent) => void;
  /** Aim at `coordinate` as seen from `pose`. Cheap enough to call per frame. */
  track: (pose: MapPose, coordinate: [number, number] | null) => void;
  /** Forget the camera, so nothing is drawn from a stale one. */
  clear: () => void;
};

export function useAvatarCamera(): AvatarCamera {
  const eye = useSharedValue<Float3>([0, 1, 0]);
  const target = useSharedValue<Float3>([0, 0, 0]);
  const up = useSharedValue<Float3>([0, 0, -1]);
  const height = useRef(0);
  const [placed, setPlaced] = useState(false);

  const onLayout = useCallback((event: LayoutChangeEvent) => {
    height.current = event.nativeEvent.layout.height;
  }, []);

  const track = useCallback(
    (pose: MapPose, coordinate: [number, number] | null) => {
      if (!coordinate || height.current <= 0) return;
      const ground = groundOffset(pose, coordinate);
      const back = cameraEye(pose.pitch, cameraDistance(height.current));
      // The model stays at the origin and the camera moves around it: Filament
      // multiplies transform props onto an entity's existing transform, so a
      // model that moved every frame would compound itself out of the world.
      const at: Float3 = [-ground.x, 0, -ground.z];
      target.value = at;
      eye.value = [at[0] + back[0], at[1] + back[1], at[2] + back[2]];
      up.value = cameraUp(pose.pitch);
      setPlaced(true);
    },
    [eye, target, up],
  );

  const clear = useCallback(() => setPlaced(false), []);

  return { eye, target, up, placed, onLayout, track, clear };
}
