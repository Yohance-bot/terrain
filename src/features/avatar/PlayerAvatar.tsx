import { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import {
  Animator,
  Camera,
  DefaultLight,
  FilamentScene,
  FilamentView,
  Model,
  type AnimationItem,
} from 'react-native-filament';

/**
 * The player's 3D avatar, drawn above the map.
 *
 * MapLibre cannot render glTF, so this is a second renderer composited over it.
 * That imposes two rules the rest of the design follows:
 *
 * 1. It always draws in front of the map. There is no shared depth buffer
 *    between the two engines, so it cannot be occluded by buildings. A floating
 *    character is the one case where that reads as intended rather than broken —
 *    which is why the thing that must sit *on* the ground (the hologram) is
 *    drawn by MapLibre instead.
 * 2. Its position is screen-space, so the map has to be asked where the fix
 *    landed. Measured on device that costs ~2ms and stays within a pixel in
 *    normal use; the 43px drift seen in the spike was a camera flying across
 *    the city under script, not a person looking at a map.
 */

// Metro resolves binary assets through require(); a static import does not
// produce an asset reference the native side can load.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const RUNNER = require('../../../assets/avatar/runner.glb');

/** Stage size in points. The Filament camera frames the unit cube to fit, so
 *  this is what actually controls how big the avatar reads on screen. */
const STAGE_WIDTH = 132;
const STAGE_HEIGHT = 164;

/** Blend between Run and Idle rather than snapping between poses. */
const TRANSITION_SECONDS = 0.25;

type Props = {
  /** Where the player's fix currently sits on screen, in points. Null hides the
   *  avatar: it must never be drawn somewhere the player is not. */
  anchor: { x: number; y: number } | null;
  /** Drives the clip: true plays Run, false plays Idle. */
  running: boolean;
};

export function PlayerAvatar({ anchor, running }: Props) {
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

  if (!anchor) return null;

  return (
    <View pointerEvents="none" style={styles.layer}>
      <View
        style={[
          styles.stage,
          // Bottom-centre of the stage sits on the fix, so the avatar stands on
          // the hologram rather than being centred over it.
          { left: anchor.x - STAGE_WIDTH / 2, top: anchor.y - STAGE_HEIGHT },
        ]}
      >
        <FilamentScene>
          <FilamentView style={StyleSheet.absoluteFill} enableTransparentRendering>
            <Camera />
            <DefaultLight />
            <Model
              source={RUNNER}
              // Sized from the stage rather than guessed in world units, then
              // lifted so the feet sit on the stage's bottom edge — which the
              // layout places exactly on the hologram at screen centre.
              transformToUnitCube
              translate={[0, 0.5, 0]}
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
    </View>
  );
}

const styles = StyleSheet.create({
  layer: StyleSheet.absoluteFillObject,
  stage: {
    position: 'absolute',
    width: STAGE_WIDTH,
    height: STAGE_HEIGHT,
  },
});
