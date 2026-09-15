import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { execFileSync } from 'node:child_process';

// Compile the installed production Java scheduler. Only JNI and Android API
// boundaries are stubbed, so callback identity/epoch behavior is exercised.
const root = mkdtempSync(join(tmpdir(), 'terrarun-choreographer-test-'));
function file(name, body) { const path = join(root, name); mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, body); return path; }
try {
  const source = readFileSync('node_modules/react-native-filament/android/src/main/java/com/margelo/filament/FilamentChoreographer.java', 'utf8')
    .replace('private native HybridData initHybrid();', 'private HybridData initHybrid() { return new HybridData(); }')
    .replace('private native void onFrame(long timestamp);', 'private void onFrame(long timestamp) { if (timestamp == 1) stop(); if (timestamp == 2) { stop(); start(); } }');
  const files = [file('com/margelo/filament/FilamentChoreographer.java', source)];
  for (const [pkg, name] of [['androidx.annotation', 'Keep'], ['com.facebook.proguard.annotations', 'DoNotStrip'], ['dalvik.annotation.optimization', 'FastNative']]) files.push(file(`${pkg.replaceAll('.', '/')}/${name}.java`, `package ${pkg}; public @interface ${name} {}`));
  files.push(file('com/facebook/jni/HybridData.java', 'package com.facebook.jni; public class HybridData {}'));
  files.push(file('android/util/Log.java', 'package android.util; public class Log { public static int d(String tag, String text) { return 0; } }'));
  files.push(file('android/view/Choreographer.java', `package android.view;
    import java.util.ArrayList;
    public class Choreographer {
      public interface FrameCallback { void doFrame(long timestamp); }
      private static final Choreographer instance = new Choreographer();
      public final ArrayList<FrameCallback> queue = new ArrayList<>();
      public static Choreographer getInstance() { return instance; }
      public void postFrameCallback(FrameCallback cb) { queue.add(cb); }
      public void removeFrameCallback(FrameCallback cb) { queue.removeIf(item -> item == cb); }
      public FrameCallback take() { return queue.remove(0); }
    }`));
  files.push(file('TestScheduler.java', `import android.view.Choreographer;
    import com.margelo.filament.FilamentChoreographer;
    public class TestScheduler {
      static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
      public static void main(String[] args) throws Exception {
        var scheduler = new FilamentChoreographer(); var queue = Choreographer.getInstance();
        var start = FilamentChoreographer.class.getDeclaredMethod("start"); start.setAccessible(true);
        var stop = FilamentChoreographer.class.getDeclaredMethod("stop"); stop.setAccessible(true);
        for (int i=0; i<100; i++) {
          start.invoke(scheduler); start.invoke(scheduler);
          check(queue.queue.size()==1, "start must be idempotent");
          stop.invoke(scheduler); check(queue.queue.isEmpty(), "stop must remove the exact posted callback");
        }
        start.invoke(scheduler); var oldFrame = queue.take();
        stop.invoke(scheduler); start.invoke(scheduler); oldFrame.doFrame(0);
        check(queue.queue.size()==1, "stale epoch must not post another frame");
        queue.take().doFrame(2); // Simulate pause/resume inside native rendering.
        check(queue.queue.size()==1, "in-flight frame must not duplicate resumed callback");
        queue.take().doFrame(1); // Simulate hiding the map inside native rendering.
        check(queue.queue.isEmpty(), "paused frame must not repost itself");
        start.invoke(scheduler); queue.take().doFrame(0);
        check(queue.queue.size()==1, "active frame must continue normally");
        stop.invoke(scheduler);
        System.out.println("Android scheduler: 100 pause/resume cycles, callback identity, stale/in-flight epochs and normal rendering pass.");
      }
    }`));
  execFileSync('javac', ['-d', root, ...files], { stdio: 'pipe' });
  const output = execFileSync('java', ['-cp', root, 'TestScheduler'], { encoding: 'utf8' });
  assert.match(output, /pass/); process.stdout.write(output);
} finally { rmSync(root, { recursive: true, force: true }); }
