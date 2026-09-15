#!/usr/bin/env node
/**
 * Every `accessibilityRole` in the app must be one Android accepts.
 *
 * This exists because `accessibilityRole="tabbar"` shipped in an APK. It is a
 * real role on iOS, so nothing complained there, and Android does not degrade
 * gracefully for roles it does not recognise: `AccessibilityRole.fromValue`
 * throws `IllegalArgumentException` from inside the view manager, on the main
 * thread, while the view is being created. The app died the instant the tab bar
 * mounted — which is just after signing in, so it looked like a login bug.
 *
 * The list of valid roles is read from React Native's own enum rather than
 * copied, so it follows the installed version instead of drifting from it.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const ENUM_SOURCE = join(
  ROOT,
  'node_modules/react-native/ReactAndroid/src/main/java/com/facebook/react/uimanager/ReactAccessibilityDelegate.java',
);

function androidRoles() {
  const java = readFileSync(ENUM_SOURCE, 'utf8');
  // The enum body runs from `enum AccessibilityRole {` to its first `;`, which
  // closes the constant list. Matching names anywhere in the file would also
  // pick up the switch statements that follow.
  const start = java.indexOf('enum AccessibilityRole {');
  if (start < 0) throw new Error(`No AccessibilityRole enum in ${ENUM_SOURCE}`);
  const body = java.slice(start, java.indexOf(';', start));
  const names = body.match(/^\s+([A-Z_]+),$/gm);
  if (!names) throw new Error('Found the AccessibilityRole enum but no constants in it');
  return new Set(names.map(n => n.trim().replace(/,$/, '').toLowerCase()));
}

function sources(dir, found = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry.startsWith('.')) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) sources(path, found);
    else if (/\.(tsx?|jsx?)$/.test(entry)) found.push(path);
  }
  return found;
}

const valid = androidRoles();
const offences = [];
for (const file of [...sources(join(ROOT, 'src')), ...sources(join(ROOT, 'app'))]) {
  const text = readFileSync(file, 'utf8');
  // Only string literals are checked. A role built at runtime is not something
  // this can see, and there are none.
  for (const match of text.matchAll(/accessibilityRole=["']([^"']+)["']/g)) {
    if (!valid.has(match[1].toLowerCase())) {
      const line = text.slice(0, match.index).split('\n').length;
      offences.push(`${file.replace(ROOT, '')}:${line}  ${match[1]}`);
    }
  }
}

if (offences.length > 0) {
  console.error('Accessibility roles Android will throw on:\n');
  for (const o of offences) console.error(`  ${o}`);
  console.error(`\nValid: ${[...valid].sort().join(', ')}`);
  process.exit(1);
}

console.log(`Accessibility roles: every literal is one of Android's ${valid.size} valid roles.`);
