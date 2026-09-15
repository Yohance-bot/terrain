# The 3D avatar crashed the app on launch

The app died every time it was opened on an iPhone 16 (iOS 27.0, `TerraRun`
release build). It looked like a launch crash, but the cause was on the opening
screen: the map mounts `PlayerAvatar`, and Filament was killed within a second of
its first frame.

Two independent faults, both fixed. The second one was ours.

## How to reproduce and observe it

The device console is enough; no Xcode session is needed.

```sh
xcrun devicectl device process launch --device NOVA --console --terminate-existing com.runprototype.app
```

The signal is printed as the last line when the app dies. For the exception type
and a backtrace, the `.ips` crash report has to come off the device, and that
needs USB — `devicectl` cannot fetch crash reports, `log stream` on this macOS
cannot read a device, and `idevicecrashreport` reports `No device found` over
Wi-Fi. With a cable:

```sh
brew install libimobiledevice
idevicecrashreport -e -k /tmp/nova-crashes
```

Each `.ips` is two JSON documents, a metadata line then the payload. `exception`,
`termination` and the `faultingThread` index into `threads` are what matter.

## Fault 1 — the Metal surface was created at 0x0, then resized under the render loop

Fixed in `patches/react-native-filament+1.11.0.patch`.

`FilamentMetalView` reported itself ready from `didMoveToWindow`, which UIKit
calls *before* the first layout pass. The view's bounds are zero at that point, so
the `CAMetalLayer`'s `drawableSize` was `0x0` and both the Filament surface and
the swapchain built from it were created against a zero-sized drawable. The real
size arrived later, from `layoutSubviews`, as a resize.

Whether that resize landed before or after the render loop started was a race,
and the orderings behaved differently — which is why the crash looked
intermittent:

| Ordering | Result |
| --- | --- |
| `Starting choreographer` then `Surface resized` | `signal 11` (SIGSEGV) |
| `Surface resized` then `Starting choreographer` | survives the resize |

The library knows about the hazard — `EngineImpl::synchronizePendingFrames` exists
to "avoid a race between the surface being resized before pending frames are
rendered into it" — but the fence it waits on does not prevent the crash.

The patch reports readiness only once the view is both in a window and has a
non-zero `drawableSize`, and is called from `layoutSubviews` as well as
`didMoveToWindow` since either can come first. The swapchain is then created once,
at the size it keeps, and the KVO observer that reports resizes is installed after
that size is set — so the startup resize no longer exists, rather than being
better synchronised. A genuine later resize still takes the old path; the view is
full-screen in a portrait-locked app, so there isn't one.

Confirmed by the console: `Ignoring invalid surface size: 0 x 0` and
`Surface resized to 1179 x 2556` are both gone, and so is the SIGSEGV.

## Fault 2 — reading a shared array past its end

Fixed in `PlayerAvatar.tsx`, with a second guard in
`patches/react-native-worklets-core+1.6.3.patch`.

With fault 1 out of the way the app was killed at the first rendered frame
instead. Three crash reports told the story, because all three had the same
backtrace on the `filament.render.queue` thread and three *different* symptoms:

| Report | Exception |
| --- | --- |
| `122222` | `SIGSEGV`, corrupted frames above `ShadowNode::replaceChild` |
| `123733` | `SIGBUS`, `EXC_ARM_DA_ALIGN at 0x67756f720000000f` |
| `124243` | `SIGKILL`, `CODESIGNING` / `Invalid Page`, `KERN_PROTECTION_FAILURE at 0x0` |

One faulting address, `0x67756f72...`, is ASCII — `g`, `u`, `o`, `r`. A pointer
made of text means a value that was never a pointer was dereferenced as one, and
three unrelated symptoms from one code path mean memory corruption rather than a
logic error. The shared frames name the culprit:

```
RNWorklet::WorkletInvoker::call          our render callback, entering the worklet
  ... Hermes interpreting it ...
  hermes::vm::JSProxy::getComputed        indexing something
    RNWorklet::JsiArrayWrapper::get       ← faults here
```

`JsiArrayWrapper` is the host object that carries a shared value's array between
the two runtimes, and its indexed read was:

```cpp
auto index = std::stoi(nameStr.c_str());
auto prop = _array[index];
return JsiWrapper::unwrap(runtime, prop);
```

`_array` is a `std::vector`. Reading past the end of one is undefined behaviour,
not `undefined` — it returns whatever follows the buffer as a `shared_ptr`, and
unwrapping dereferences it.

Our render callback did exactly that, every frame:

```js
const list = sharedActors.value;
for (let i = 0; i < roots.length; i++) {   // roots.length is MAX_MAP_ACTORS, 8
  const actor = list[i];                    // list holds 1 when running alone
```

Eight model instances are allocated up front, but `mapActors` returns only the
actors that exist — usually just `self`. Written against a real Javascript array
the loop is correct, since `list[1]` would be `undefined`. Across the worklet
boundary it read seven entries past the end of a one-element vector. Before the
first assignment it read past the end of an *empty* one, which is why the kill
landed on the very first frame.

The fix bounds the loop by `list.length`, which the wrapper does expose. The patch
additionally makes the wrapper return `undefined` out of bounds, matching
Javascript, so the next caller to make this mistake gets the semantics they
expect instead of corrupted memory.

## Android

Fault 1 cannot occur there. `FilamentView.java` uses a `TextureView` and creates
the surface from `onSurfaceTextureAvailable(surfaceTexture, width, height)`, which
Android only calls once the texture exists at a real size, and
`onSurfaceTextureSizeChanged` then fires only on genuine changes. There is no
zero-sized window to race with.

Fault 2 was platform-independent — the same worklet, the same vector — so the APK
was affected and is fixed by the same two changes. That is reasoning, not
evidence: there is no Android device or emulator image on this machine, so the APK
builds and is signed but "runs" is still unverified on hardware.
