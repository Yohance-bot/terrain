import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MercatorCoordinate, type CustomLayerInterface, type Map as MapInstance } from "maplibre-gl";

// The same file the phone ships, so the console is testing the real asset and
// not a stand-in that could drift from it.
import runnerUrl from "../../../assets/avatar/runner.glb?url";

/**
 * The player avatar, in the console's map.
 *
 * The phone draws this with Filament in a view over MapLibre; here MapLibre
 * hands out its own projection matrix, so a custom layer can render into the
 * same pass — which means the avatar is depth-tested against the 3D buildings,
 * something the phone cannot do. It is the same model, the same clips and the
 * same on-screen size, so what a tester sees while driving a run is what a
 * player sees while running one.
 */

/** Cyan, matching the run trail: light cast on the road, not a second dot. */
export const HOLOGRAM_COLOR = "#00E5FF";

/** On-screen height in CSS pixels, matched to the phone's avatar. */
const AVATAR_PIXELS = 32;

/** MapLibre's world is `512 * 2^zoom` pixels across, and one mercator unit wide. */
const pixelsToMercator = (zoom: number) => 1 / (512 * Math.pow(2, zoom));

export type AvatarLayer = CustomLayerInterface & {
  /** Where the runner is, or null to draw nothing. */
  setPosition: (position: [number, number] | null) => void;
  /** True plays Run, false plays Idle. */
  setRunning: (running: boolean) => void;
};

export function createAvatarLayer(id = "player-avatar"): AvatarLayer {
  let renderer: THREE.WebGLRenderer | undefined;
  let map: MapInstance | undefined;
  let mixer: THREE.AnimationMixer | undefined;
  let actions: { run?: THREE.AnimationAction; idle?: THREE.AnimationAction } = {};
  let current: THREE.AnimationAction | undefined;
  let position: [number, number] | null = null;
  let running = false;
  let clock = new THREE.Clock();

  const scene = new THREE.Scene();
  const camera = new THREE.Camera();

  // Flat and frontal: the model carries no textures, so it only reads as a
  // character if the light picks out its silhouette rather than its surface.
  scene.add(new THREE.AmbientLight(0xffffff, 2.2));
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.position.set(0.6, 1.4, 1);
  scene.add(key);

  function play(next: THREE.AnimationAction | undefined) {
    if (!next || next === current) return;
    next.reset().play();
    if (current) current.crossFadeTo(next, 0.25, false);
    current = next;
  }

  return {
    id,
    type: "custom",
    // Conformal z, so the avatar shares the depth buffer with the buildings.
    renderingMode: "3d",

    onAdd(added: MapInstance, gl: WebGL2RenderingContext) {
      map = added;
      renderer = new THREE.WebGLRenderer({ canvas: added.getCanvas(), context: gl });
      renderer.autoClear = false;
      clock = new THREE.Clock();

      new GLTFLoader().load(runnerUrl, (gltf) => {
        const model = gltf.scene;
        // Normalised to one unit tall and standing on y = 0, so the scale below
        // is a height in pixels and the feet meet the ground rather than sink.
        const box = new THREE.Box3().setFromObject(model);
        const size = new THREE.Vector3();
        box.getSize(size);
        const unit = 1 / (size.y || 1);
        model.scale.setScalar(unit);
        model.position.set(
          -((box.min.x + box.max.x) / 2) * unit,
          -box.min.y * unit,
          -((box.min.z + box.max.z) / 2) * unit,
        );
        scene.add(model);

        mixer = new THREE.AnimationMixer(model);
        const clip = (name: string) =>
          gltf.animations.find((item) => item.name.toLowerCase() === name);
        const run = clip("run");
        const idle = clip("idle");
        actions = {
          run: run ? mixer.clipAction(run) : undefined,
          idle: idle ? mixer.clipAction(idle) : undefined,
        };
        play(running ? actions.run ?? actions.idle : actions.idle ?? actions.run);
        added.triggerRepaint();
      });
    },

    onRemove() {
      renderer?.dispose();
      renderer = undefined;
      mixer?.stopAllAction();
      mixer = undefined;
      map = undefined;
    },

    setPosition(next) {
      position = next;
      map?.triggerRepaint();
    },

    setRunning(next) {
      if (next === running) return;
      running = next;
      play(next ? actions.run ?? actions.idle : actions.idle ?? actions.run);
    },

    render(_gl, options) {
      if (!renderer || !map || !position) return;
      mixer?.update(clock.getDelta());

      const anchor = MercatorCoordinate.fromLngLat(position, 0);
      const scale = AVATAR_PIXELS * pixelsToMercator(map.getZoom());
      // glTF is Y-up and mercator's Y runs south, hence the quarter turn and
      // the flipped Y scale — the standard MapLibre/three.js placement.
      const model = new THREE.Matrix4()
        .makeTranslation(anchor.x, anchor.y, anchor.z)
        .scale(new THREE.Vector3(scale, -scale, scale))
        .multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2));
      camera.projectionMatrix = new THREE.Matrix4()
        .fromArray(Array.from(options.defaultProjectionData.mainMatrix))
        .multiply(model);

      renderer.resetState();
      renderer.render(scene, camera);
      map.triggerRepaint();
    },
  };
}
