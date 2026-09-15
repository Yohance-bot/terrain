# The 3D avatar crashes the app on iOS

The app died on every launch on an iPhone 16 (iOS 26.5, `TerraRun` release build).
It looked like a launch crash, but the cause is on the opening screen: the map
mounts `PlayerAvatar`, and Filament is killed within a second of its first frame.

Two separate faults were found. The first is fixed. The second is why the
character is opt-in — see `DEFAULT_PLAYER_MARKER` in `src/features/hud/preferences.ts`.

## How to reproduce and observe it

The device console is enough; no Xcode session is needed.

```sh
xcrun devicectl device process launch --device NOVA --console --terminate-existing com.runprototype.app
```

The app is killed a few seconds in and the signal is printed as the last line.
Adding `--environment-variables '{"MTL_DEBUG_LAYER":"1"}'` turns on Metal API
validation, which reported only benign warnings (`unused vertex binding in render
encoder`) — so neither fault is an outright Metal API misuse.

## Fault 1 — the surface was created at 0x0, then resized under the render loop

**Fixed** in `patches/react-native-filament+1.11.0.patch`.

`FilamentMetalView` reported itself ready from `didMoveToWindow`, which UIKit
calls *before* the first layout pass. At that moment the view's bounds are zero,
so the `CAMetalLayer`'s `drawableSize` is `0x0`, and the Filament surface and the
swapchain built from it were both created against a zero-sized drawable. The real
size arrived later from `layoutSubviews`, as a resize.

Whether that resize landed before or after the render loop started was a race,
and the two orderings gave two different outcomes:

| Ordering | Result |
| --- | --- |
| `Starting choreographer` then `Surface resized` | `signal 11` (SIGSEGV) |
| `Surface resized` then `Starting choreographer` | survives the resize |

The library is aware of the hazard — `EngineImpl::synchronizePendingFrames` exists
to "avoid a race between the surface being resized before pending frames are
rendered into it" — but the fence it waits on does not prevent the crash.

The patch reports readiness only once the view is both in a window and has a
non-zero `drawableSize`, calling the check from `layoutSubviews` as well as
`didMoveToWindow`. The swapchain is then created once, at the size it keeps, and
the KVO observer that reports resizes is installed *after* that size is set — so
the startup resize no longer exists rather than merely being better synchronised.
A genuine later resize still takes the old path; the view is full-screen in a
portrait-locked app, so there isn't one.

Confirmed by the console: `Ignoring invalid surface size: 0 x 0` and
`Surface resized to 1179 x 2556` are both gone, and so is the SIGSEGV.

## Fault 2 — killed on the first rendered frame

**Open.** With fault 1 fixed, the app gets one step further and is then killed
with `signal 9` immediately after `Starting choreographer`, with no further log
output:

```
[RNF/EngineImpl]: Setting swapchain...
[RNF/ChoreographerWrapper]: Adding frame callback listener
Starting choreographer
App terminated due to signal 9.
```

`signal 9` is the system killing the process rather than the process faulting, so
it is a different class of problem from fault 1 — a watchdog, jetsam, or a GPU
fault, and the console does not say which. Distinguishing them needs the `.ips`
crash report from the device, which requires a USB connection: `devicectl` cannot
fetch crash reports, `log stream` on this macOS cannot read a device, and
`idevicecrashreport` from libimobiledevice needs USB (`No device found` over Wi-Fi).

The prime suspect is the instancing introduced in `c151e7b`, which rewrote
`PlayerAvatar` from a single `<Model>` to `useModel(RUNNER, { instanceCount: 8 })`
with a `ModelRenderer` and eight `ModelInstance` slots, so that friends and the
active ghost could share the scene. The single-avatar version that preceded it ran
on this phone. That has not been bisected yet, so it remains a suspicion.

Note the crash is *not* in the per-frame transform work: the model was still
loading when the kill arrived, so `base` was null and the callback returned early.

## Android is not affected by fault 1

`FilamentView.java` uses a `TextureView` and creates the surface from
`onSurfaceTextureAvailable(surfaceTexture, width, height)`, which Android only
calls once the texture exists with a real size. `onSurfaceTextureSizeChanged`
then fires only on genuine size changes. There is no zero-sized window to race
with, so the ordering that segfaults on iOS cannot arise.

Fault 2 has not been tested on Android hardware — there is no Android device or
emulator image on this machine. The APK builds and is signed, but "runs" is
unverified.
