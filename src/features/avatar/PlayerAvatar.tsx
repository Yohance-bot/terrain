import { useCallback, useState } from 'react';
import { StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import {
  Animator,
  Camera,
  DefaultLight,
  FilamentScene,
  FilamentView,
  Model,
  type AnimationItem,
} from 'react-native-filament';

import {
  cameraDistance,
  cameraEye,
  cameraUp,
  FAR_PLANE,
  FOCAL_LENGTH_MM,
  groundOffset,
  NEAR_PLANE,
  type Float3,
  type MapPose,
} from './mapCamera';

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
  /** The map's current camera. Null hides the avatar: without it there is no
   *  honest place to put the character. */
  pose: MapPose | null;
  /** Where the player is. */
  coordinate: [number, number] | null;
  /** Drives the clip: true plays Run, false plays Idle. */
  running: boolean;
};

export function PlayerAvatar({ pose, coordinate, running }: Props) {
  const [clips, setClips] = useState<{ run: number; idle: number } | null>(null);
  const [viewport, setViewport] = useState<{ width: number; height: number } | null>(null);

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

  const onLayout = useCallback((event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setViewport((current) =>
      current?.width === width && current?.height === height ? current : { width, height },
    );
  }, []);

  const ready = pose !== null && coordinate !== null && viewport !== null && viewport.height > 0;
  const ground = ready ? groundOffset(pose, coordinate) : null;
  const distance = ready ? cameraDistance(viewport.height) : 0;

  /**
   * The avatar stays at the origin and the camera moves around it.
   *
   * This is the same scene shifted, but it is the only safe way to animate it:
   * Filament's transform props multiply onto the entity's current transform by
   * default, so a translate that changes every frame compounds and throws the
   * model out of the world within a second. Camera props go through lookAt,
   * which is absolute and cannot accumulate.
   */
  const target: Float3 = ground ? [-ground.x, 0, -ground.z] : [0, 0, 0];
  const eye = cameraEye(pose?.pitch ?? 0, distance);
  const cameraPosition: Float3 = [target[0] + eye[0], target[1] + eye[1], target[2] + eye[2]];

  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill} onLayout={onLayout}>
      {ready && ground && (
        <FilamentScene>
          <FilamentView style={StyleSheet.absoluteFill} enableTransparentRendering>
            <Camera
              // Filament takes a focal length rather than an angle; 36mm is
              // MapLibre's 36.87 degree vertical field of view on a 35mm frame.
              focalLengthInMillimeters={FOCAL_LENGTH_MM}
              cameraPosition={cameraPosition}
              cameraTarget={target}
              cameraUp={cameraUp(pose.pitch)}
              // World units are map pixels, so the camera sits over a thousand
              // of them away. Filament's 0.1/100 defaults would clip everything.
              near={NEAR_PLANE}
              far={FAR_PLANE}
            />
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
      )}
    </View>
  );
}
