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
 * is its height in points. Close to the scale a person reads at on a map,
 * rather than the exaggerated size map avatars are often drawn at.
 */
const AVATAR_HEIGHT = 84;

/** Blend between Run and Idle rather than snapping between poses. */
const TRANSITION_SECONDS = 0.25;

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

  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill} onLayout={onLayout}>
      {ready && ground && (
        <FilamentScene>
          <FilamentView style={StyleSheet.absoluteFill} enableTransparentRendering>
            <Camera
              // Filament takes a focal length rather than an angle; 36mm is
              // MapLibre's 36.87 degree vertical field of view on a 35mm frame.
              focalLengthInMillimeters={FOCAL_LENGTH_MM}
              cameraPosition={cameraEye(pose.pitch, distance)}
              cameraTarget={[0, 0, 0]}
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
              transformToUnitCube
              scale={[AVATAR_HEIGHT, AVATAR_HEIGHT, AVATAR_HEIGHT]}
              translate={[ground.x, AVATAR_HEIGHT / 2, ground.z]}
              // Facing the camera when still, away from it when running, so a
              // moving player reads as heading into the map.
              rotate={[0, running ? Math.PI : 0, 0]}
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
