import { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import {
  Animator,
  DefaultLight,
  FilamentScene,
  FilamentView,
  Model,
  RenderCallbackContext,
  useFilamentContext,
  type AnimationItem,
} from 'react-native-filament';
import { useSharedValue } from 'react-native-worklets-core';

import type { AvatarCamera } from './useAvatarCamera';
import { FAR_PLANE, FOCAL_LENGTH_MM, NEAR_PLANE, type Float3 } from './mapCamera';

/**
 * The player's 3D avatar, standing in the map rather than on top of it.
 *
 * Filament renders into its own view over MapLibre, so the two share no depth
 * buffer and the avatar can never be occluded by buildings. What they *can*
 * share is the camera: `mapCamera` rebuilds MapLibre's view from centre, zoom,
 * bearing and pitch, and this drives Filament with the result. That is the
 * difference between an object standing in the world — leaning as it moves off
 * centre, foreshortening as the map tilts, swinging round as the map turns —
 * and a sprite sliding across the screen.
 *
 * The ground contact is left to the map: the hologram is a MapLibre layer, so
 * it tilts and is occluded correctly, which is exactly what this layer cannot do.
 */

// Metro resolves binary assets through require(); a static import does not
// produce an asset reference the native side can load.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const RUNNER = require('../../../assets/avatar/runner.glb');

/**
 * How tall the avatar stands, in map pixels — which at the centre of a flat map
 * is its height in points.
 *
 * Calibrated against the screen rather than derived: `transformToUnitCube` does
 * not normalise to exactly one unit, so this renders about 1.6x taller than the
 * number says. 20 puts the character at roughly 32 points, which is the width
 * of the marker it replaced — small enough to read as something standing on the
 * map rather than something sitting on top of it.
 */
const AVATAR_HEIGHT = 20;

/** Blend between Run and Idle rather than snapping between poses. */
const TRANSITION_SECONDS = 0.25;

/**
 * Stable identities, and that is the whole point of hoisting them.
 *
 * Filament re-applies an entity's transforms whenever these props change by
 * reference, and re-applying `transformToUnitCube` resets the entity to one
 * unit while the scale and translate are skipped as "unchanged". Array literals
 * in JSX are new objects on every render, so the model ends up one unit tall —
 * a dot — and never lifted onto its feet.
 */
const AVATAR_SCALE: Float3 = [AVATAR_HEIGHT, AVATAR_HEIGHT, AVATAR_HEIGHT];
const AVATAR_LIFT: Float3 = [0, AVATAR_HEIGHT / 2, 0];

type Props = {
  /** The map's camera, as shared values the render thread can read. */
  camera: AvatarCamera;
  /** Drives the clip: true plays Run, false plays Idle. */
  running: boolean;
};

/**
 * Aims Filament's camera from the shared values, once per rendered frame.
 *
 * Deliberately not `<Camera>`: that component takes its numbers as props, so
 * every pose change re-registers its render callback and the camera can only
 * move as often as React re-renders. Reading shared values inside the callback
 * registers once, and then a pan costs no React work at all.
 */
function CameraRig({ rig }: { rig: AvatarCamera }) {
  const { camera, view } = useFilamentContext();
  const lastAspect = useSharedValue(0);
  const { eye, target, up } = rig;

  RenderCallbackContext.useRenderCallback(() => {
    'worklet';
    const aspect = view.getAspectRatio();
    if (lastAspect.value !== aspect) {
      lastAspect.value = aspect;
      // Filament takes a focal length rather than an angle; 36mm is MapLibre's
      // 36.87 degree vertical field of view on a 35mm frame. World units are
      // map pixels, so the camera sits over a thousand of them from its target
      // and Filament's 0.1/100 planes would clip the scene away entirely.
      camera.setLensProjection(FOCAL_LENGTH_MM, aspect, NEAR_PLANE, FAR_PLANE);
    }
    // Rebuilt element by element: a shared value holding an array arrives on
    // the render thread as a plain object, which Filament rejects outright.
    const e = eye.value;
    const t = target.value;
    const u = up.value;
    camera.lookAt([e[0], e[1], e[2]], [t[0], t[1], t[2]], [u[0], u[1], u[2]]);
  }, [camera, view, lastAspect, eye, target, up]);

  return null;
}

export function PlayerAvatar({ camera, running }: Props) {
  const [clips, setClips] = useState<{ run: number; idle: number } | null>(null);

  // Clips are matched by name. Indices depend on export order, and silently
  // playing the wrong one is the kind of bug that survives a long time.
  const onAnimationsLoaded = useCallback((animations: AnimationItem[]) => {
    const find = (name: string) =>
      animations.find((item) => item.name.toLowerCase() === name)?.index;
    const run = find('run');
    const idle = find('idle');
    if (run === undefined || idle === undefined) {
      console.warn(
        `[avatar] expected Run and Idle clips, got: ${animations.map((a) => a.name).join(', ')}`,
      );
    }
    setClips({ run: run ?? 0, idle: idle ?? 0 });
  }, []);

  // Nothing is drawn until a real camera has been read: a guessed one would put
  // the character somewhere the player is not.
  if (!camera.placed) return null;

  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <FilamentScene>
        <FilamentView style={StyleSheet.absoluteFill} enableTransparentRendering>
          <CameraRig rig={camera} />
          <DefaultLight />
          <Model
            source={RUNNER}
            // Sized in map pixels, then lifted by half its height so the feet
            // rest on the ground plane rather than the model's centre.
            // Every one of these is constant, and deliberately so: Filament
            // multiplies transform props onto the entity's existing transform,
            // so anything that changes here compounds instead of replacing.
            transformToUnitCube
            scale={AVATAR_SCALE}
            translate={AVATAR_LIFT}
          >
            <Animator
              animationIndex={clips ? (running ? clips.run : clips.idle) : 0}
              transitionDuration={TRANSITION_SECONDS}
              onAnimationsLoaded={onAnimationsLoaded}
            />
          </Model>
        </FilamentView>
      </FilamentScene>
    </View>
  );
}
