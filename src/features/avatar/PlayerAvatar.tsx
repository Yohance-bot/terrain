import { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Animator, DefaultLight, FilamentScene, FilamentView, ModelInstance, ModelRenderer, RenderCallbackContext, useFilamentContext, useModel, type AnimationItem } from 'react-native-filament';
import { useSharedValue } from 'react-native-worklets-core';
import { useSocial } from '@/features/social/useSocial';
import { useGhostRace } from '@/features/social/useGhostRace';
import { mapActors, MAX_MAP_ACTORS, type MapActor } from './actors';
import { useAvatarVisibility } from './visibility';
import type { AvatarCamera } from './useAvatarCamera';
import { FAR_PLANE, FOCAL_LENGTH_MM, NEAR_PLANE } from './mapCamera';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const RUNNER = require('../../../assets/avatar/runner.glb');
const SLOTS = Array.from({ length: MAX_MAP_ACTORS }, (_, i) => i);

/**
 * How tall a runner stands, in map pixels — at the centre of a flat map, that is
 * its height in points.
 *
 * Judged against the screen, because that is the only place it means anything.
 * The version of this component that came before reached its size the roundabout
 * way, through `transformToUnitCube` and a scale of 20, and guessed in a comment
 * that the result was about 32 points. It was taller than that: the unit cube
 * spans -1 to 1, so the model came out around 40. Normalising the model's own
 * height says the same thing directly, and keeps saying it if the runner is ever
 * re-exported at a different scale.
 */
const AVATAR_HEIGHT_PX = 40;
type Props = { camera: AvatarCamera; running: boolean };

/** One scene/asset shared by the player, nearby sharing friends and active ghost.
 * MapLibre and Filament do not share depth: buildings cannot occlude these models.
 */
function Runners({ camera: rig, running }: Props) {
  const { camera, view, transformManager } = useFilamentContext();
  const friends = useSocial(s => s.friends);
  const ghost = useGhostRace(s => s.ghostState);
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(timer); }, []);
  const actors = mapActors(rig.frame.value.origin, running, friends, ghost, now);
  const sharedActors = useSharedValue<MapActor[]>([]);
  useEffect(() => { sharedActors.value = actors; });
  const model = useModel(RUNNER, { instanceCount: MAX_MAP_ACTORS });
  const asset = model.state === 'loaded' ? model.asset : null;
  const instances = useMemo(() => asset?.getAssetInstances() ?? [], [asset]);
  const roots = useMemo(() => instances.map(instance => instance.getRoot()), [instances]);
  const box = model.state === 'loaded' ? model.boundingBox : null;
  // Absolute transforms start from this immutable normalization every frame.
  // Applying React transform props repeatedly compounds the scale/rotation.
  const base = useMemo(() => {
    if (!box) return null;
    const scale = AVATAR_HEIGHT_PX / Math.max(.001, box.max[1] - box.min[1]);
    return transformManager.createIdentityMatrix().translate([-box.center[0], -box.min[1], -box.center[2]]).scaling([scale, scale, scale]);
  }, [box, transformManager]);
  const hidden = useMemo(() => transformManager.createIdentityMatrix().scaling([0, 0, 0]), [transformManager]);
  const signature = actors.map(a => a.id).join('|');
  useEffect(() => {
    useAvatarVisibility.setState({ ids: asset ? signature.split('|') : [] });
    return () => { useAvatarVisibility.setState({ ids: [] }); };
  }, [asset, signature]);
  const [clips, setClips] = useState({ run: 0, idle: 0 });
  const onAnimationsLoaded = useCallback((animations: AnimationItem[]) => {
    setClips({ run: animations.find(a => a.name.toLowerCase() === 'run')?.index ?? 0, idle: animations.find(a => a.name.toLowerCase() === 'idle')?.index ?? 0 });
  }, []);
  const lastAspect = useSharedValue(0);
  const { frame } = rig;
  RenderCallbackContext.useRenderCallback(() => {
    'worklet';
    const aspect = view.getAspectRatio();
    if (aspect > 0 && lastAspect.value !== aspect) {
      lastAspect.value = aspect;
      camera.setLensProjection(FOCAL_LENGTH_MM, aspect, NEAR_PLANE, FAR_PLANE);
    }
    const f = frame.value, e = f.eye, t = f.target, u = f.up;
    camera.lookAt([e[0], e[1], e[2]], [t[0], t[1], t[2]], [u[0], u[1], u[2]]);
    if (!base) return;
    const list = sharedActors.value;
    const bearing = f.pose.bearing * Math.PI / 180;
    const size = 512 * Math.pow(2, f.pose.zoom);
    const lat0 = f.origin[1] * Math.PI / 180;
    const y0 = Math.log(Math.tan(lat0) + 1 / Math.cos(lat0));
    const cos = Math.cos(bearing), sin = Math.sin(bearing);
    const nowMs = Date.now();
    // `list` is a host object bridging two runtimes, not a JS array, and reading
    // past its end reads past the backing vector instead of returning undefined.
    // There are almost always fewer actors than instances — usually just this
    // runner — so the length is a hard bound, not a formality.
    const count = list.length;
    for (let i = 0; i < roots.length; i++) {
      const actor = i < count ? list[i] : undefined;
      if (!actor || nowMs >= actor.expiresAt) { transformManager.setTransform(roots[i]!, hidden); continue; }
      const self = actor.id === 'self';
      const lat = (self ? f.origin[1] : actor.coordinate[1]) * Math.PI / 180;
      const east = self ? 0 : (actor.coordinate[0] - f.origin[0]) / 360 * size;
      const south = self ? 0 : (y0 - Math.log(Math.tan(lat) + 1 / Math.cos(lat))) / (2 * Math.PI) * size;
      const x = east * cos + south * sin, z = south * cos - east * sin;
      const yaw = self ? f.yaw : Math.PI - (actor.heading - f.pose.bearing) * Math.PI / 180;
      transformManager.setTransform(roots[i]!, base.rotate(yaw, [0, 1, 0]).translate([x, 0, z]));
    }
  }, [camera, view, lastAspect, frame, base, roots, sharedActors, transformManager, hidden]);
  return <ModelRenderer model={model}>
    {SLOTS.map(index => <ModelInstance key={index} index={index}>
      {actors[index] && <Animator animationIndex={actors[index]!.running ? clips.run : clips.idle} transitionDuration={.25} onAnimationsLoaded={index === 0 ? onAnimationsLoaded : undefined} />}
    </ModelInstance>)}
  </ModelRenderer>;
}
export function PlayerAvatar(props: Props) {
  if (!props.camera.placed) return null;
  return <View pointerEvents="none" style={StyleSheet.absoluteFill}>
    <FilamentScene><FilamentView style={StyleSheet.absoluteFill} enableTransparentRendering>
      <DefaultLight /><Runners {...props} />
    </FilamentView></FilamentScene>
  </View>;
}
