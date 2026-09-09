import { Feather } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useShallow } from 'zustand/react/shallow';
import { TelemetryPill } from '@/features/hud/TelemetryPill';
import { CueOverlay } from '@/features/hud/CueOverlay';
import { useCheckpoints, useRunCues } from '@/features/hud/useRunCues';
import { usePresentation, useHudPreferences } from '@/features/hud/usePresentation';
import { useVisualRun } from '@/features/hud/useVisualRun';
import { confirmedClaimCue } from '@/features/hud/claims';
import { buildTrail } from '@/features/hud/trail';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  Pressable,
  PanResponder,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { TerritoryMap } from '@/features/map/TerritoryMap';
import { ENABLE_SIMULATION, JAYANAGAR_CENTER } from '@/constants/config';
import { recoverRecorderOnce, resetRecorderStats, useRecorder } from '@/features/recorder/useRecorder';
import { getDeviceId, setDevRunnerId } from '@/lib/device';
import { formatDistance } from '@/lib/geo';
import { findActiveTerritoryId, findLoopCandidateTerritoryIds } from '@/lib/pointInPolygon';
import { detectLoopCandidate } from '@/lib/runCapture';
import { runEventCopy, type RunEvent } from '@/lib/runEvents';
import { ApiRequestError, logApiRequestErrorInDev, queuedRunNotice } from '@/services/api/errors';
import { fetchAccount, fetchCapturedAreas, fetchOwnedTerritoryAreas, fetchRun, fetchTerritoryDetails, getCachedAccount, resetDeveloperTerritory, submitRun } from '@/services/api/client';
import type { AccountSummary, RunResult, TerritoryDetails } from '@/services/api/types';
import { loadOwnership, loadTerritories } from '@/services/territories';
import {
  getLocalRun,
  listQueuedRuns,
  loadSamples,
  markRejected,
  markSubmissionFailed,
  markSubmissionStarted,
  markSynced,
  getMeta,
  setMeta,
} from '@/lib/db';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';
import { getCaptureColorIndex } from '@/lib/preferences';

// Bundled territories used for point-in-polygon during a live run.
// Same source as TerritoryMap — always available offline.
const LOCAL_TERRITORY_FEATURES = (
  require('@/assets/map/gameplay_territories.json') as GeoJSON.FeatureCollection
).features;
const SIMULATION_TICK_MS = 500;
const DEVELOPER_ACTIVATION_COLORS = ['#22C55E', '#A855F7', '#F97316'] as const;

export default function MapScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ autoStart?: string; runnerId?: string }>();

  const [territories, setTerritories] = useState<GeoJSON.FeatureCollection | null>(null);
  const [capturedAreas, setCapturedAreas] = useState<GeoJSON.FeatureCollection | null>(null);
  const [ownedTerritoryAreas, setOwnedTerritoryAreas] = useState<GeoJSON.FeatureCollection | null>(null);
  const [ownedByYou, setOwnedByYou] = useState<Set<string>>(new Set());
  const [ownedByOthers, setOwnedByOthers] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeTerritoryIds, setActiveTerritoryIds] = useState<Set<string>>(new Set());
  const [runEvent, setRunEvent] = useState<RunEvent | null>(null);
  const [selectedTerritory, setSelectedTerritory] = useState<TerritoryDetails | null>(null);
  const [territoryBusy, setTerritoryBusy] = useState(false);
  const territoryRequest = useRef(0);
  const flushingQueue = useRef(false);
  const autoStartHandled = useRef(false);
  const announcedLoopKey = useRef<string | null>(null);
  const simulatedPosition = useRef<[number, number] | null>(null);
  const joystickVector = useRef({ x: 0, y: 0 });
  const [joystickOffset, setJoystickOffset] = useState({ x: 0, y: 0 });
  const [account, setAccount] = useState<AccountSummary | null>(() => getCachedAccount());
  const [accountChecked, setAccountChecked] = useState(() => Boolean(getCachedAccount()));
  const [layerMode, setLayerMode] = useState<'all' | 'territories' | 'captures'>('all');
  const [layersPanelOpen, setLayersPanelOpen] = useState(false);
  const [captureColorIndex, setCaptureColorIndex] = useState(0);

  const { status, error, isSimulation, start, startSimulation, addSimulatedPoint, stop } =
    useRecorder(useShallow(s => ({ status: s.status, error: s.error, isSimulation: s.isSimulation, start: s.start, startSimulation: s.startSimulation, addSimulatedPoint: s.addSimulatedPoint, stop: s.stop })));
  const presentation = usePresentation();
  const { cleanPath, fix, segmentStarts } = useVisualRun(presentation.active, presentation.economy);
  useCheckpoints(presentation.active);
  const presentationActive = useRef(presentation.active);
  presentationActive.current = presentation.active;
  const recording = status === 'recording';
  const developerMode = account?.role === 'developer';
  const territoryFeatures = territories?.features?.length ? territories.features : LOCAL_TERRITORY_FEATURES;
  const traversedRoads = useMemo(() => buildTrail(cleanPath, segmentStarts, presentation.economy), [cleanPath, segmentStarts, presentation.economy]);
  const loopCandidate = useMemo(() => detectLoopCandidate(segmentStarts.length ? [] : cleanPath), [cleanPath, segmentStarts]);
  const activationColor = account?.developer_slot
    ? DEVELOPER_ACTIVATION_COLORS[account.developer_slot - 1] ?? colors.route
    : colors.route;

  const celebrateClaim = useCallback(async (result: RunResult): Promise<boolean> => {
    if (!presentationActive.current || AppState.currentState !== 'active' || useRecorder.getState().status !== 'idle') return false;
    if (!confirmedClaimCue(result, [0, 0])) return false;
    const key = `hud.claim-played.${result.run_id}`;
    if (await getMeta(key).catch(() => null)) return false;
    const samples = await loadSamples(result.run_id);
    const last = samples.at(-1);
    if (!last || !Number.isFinite(last.lon) || !Number.isFinite(last.lat) || Math.abs(last.lon) > 180 || Math.abs(last.lat) > 90) return false;
    if (!presentationActive.current || useRecorder.getState().status !== 'idle') return false;
    const cue = confirmedClaimCue(result, [last.lon, last.lat])!;
    await setMeta(key, 'true').catch(() => undefined);
    useRunCues.getState().emit(cue);
    return true;
  }, []);

  useEffect(() => {
    void fetchAccount()
      .then((next) => {
        setAccount(next);
        if (!next) router.replace('/sign-in');
      })
      .catch(() => {
        if (!getCachedAccount()) {
          router.replace('/sign-in');
        }
      })
      .finally(() => setAccountChecked(true));

    void getCaptureColorIndex().then(setCaptureColorIndex);
  }, [router]);

  const onSimulationMove = useCallback(([lon, lat]: [number, number]) => {
    simulatedPosition.current = [lon, lat];
    void addSimulatedPoint(lon, lat);
  }, [addSimulatedPoint]);

  const joystickResponder = useMemo(
    () => PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderMove: (_, gesture) => {
        const limit = 38;
        const x = Math.max(-limit, Math.min(limit, gesture.dx));
        const y = Math.max(-limit, Math.min(limit, gesture.dy));
        setJoystickOffset({ x, y });
        joystickVector.current = { x, y };
      },
      onPanResponderRelease: () => {
        joystickVector.current = { x: 0, y: 0 };
        setJoystickOffset({ x: 0, y: 0 });
      },
      onPanResponderTerminate: () => {
        joystickVector.current = { x: 0, y: 0 };
        setJoystickOffset({ x: 0, y: 0 });
      },
    }),
    [],
  );

  // A real virtual thumbstick continues to move while held; it does not need
  // the finger to keep wiggling. Movement is capped at 6 m/s for controlled
  // loop drawing and is fed through the normal simulated GPS pipeline.
  useEffect(() => {
    if (!isSimulation) return;
    const timer = setInterval(() => {
      const { x, y } = joystickVector.current;
      const current = simulatedPosition.current;
      const magnitude = Math.min(1, Math.hypot(x, y) / 38);
      if (!current || magnitude < 0.08) return;
      const [lon, lat] = current;
      // Two controlled samples a second are plenty for a test runner and cut
      // the SQLite/clean-path/map work in half. Keep its top speed unchanged.
      const metres = 6 * (SIMULATION_TICK_MS / 1_000) * magnitude;
      const directionX = x / Math.hypot(x, y);
      const directionY = y / Math.hypot(x, y);
      const nextLat = lat - (directionY * metres) / 111_320;
      const nextLon = lon + (directionX * metres) / (111_320 * Math.cos((lat * Math.PI) / 180));
      simulatedPosition.current = [nextLon, nextLat];
      void addSimulatedPoint(nextLon, nextLat);
    }, SIMULATION_TICK_MS);
    return () => clearInterval(timer);
  }, [addSimulatedPoint, isSimulation]);

  const refresh = useCallback(async (forceRefresh = false) => {
    try {
      // Device identity does not depend on the territory download, so overlap
      // it with the cache/network lookup rather than making startup serial.
      const [territoryResult, deviceId] = await Promise.all([
        loadTerritories({ forceRefresh }),
        getDeviceId(),
      ]);
      const { collection, fromCache } = territoryResult;
      void fetchAccount().then(setAccount).catch(() => undefined);
      setTerritories(collection);
      const ownership = await loadOwnership(deviceId);
      setOwnedByYou(ownership.ownedByYou);
      setOwnedByOthers(ownership.ownedByOthers);
      // Loop areas are decorative public overlays. A failed refresh must never
      // prevent the fixed territory/influence layer from using its cache.
      void fetchCapturedAreas().then(setCapturedAreas).catch(() => undefined);
      // The server dissolves same-owner polygons using exact topology. The
      // phone only draws that authoritative representation.
      void fetchOwnedTerritoryAreas().then(setOwnedTerritoryAreas).catch(() => undefined);
      setNotice(
        fromCache
          ? 'Offline — showing cached boundaries.'
          : ownership.fromCache
            ? 'Offline — showing last known territory state.'
          : forceRefresh
            ? `Loaded ${collection.features.length} territories.`
            : null
      );
    } catch {
      setNotice('Could not reach the server. Territories unavailable.');
    }
  }, []);

  const submitQueuedRun = useCallback(async (runId: string): Promise<RunResult | null> => {
    let run = await getLocalRun(runId);
    if (!run?.endedAt) return null;

    if (run.status === 'synced') {
      try {
        return await fetchRun(runId);
      } catch {
        return null;
      }
    }

    if (run.status === 'rejected') {
      return null;
    }

    let leased = await markSubmissionStarted(runId);
    if (!leased) {
      // Another queue worker (e.g. background queue flush) may have leased this run.
      // Cooperate instead of racing: observe the in-flight submission.
      for (let attempt = 0; attempt < 10; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        run = await getLocalRun(runId);
        if (!run) return null;
        if (run.status === 'synced') {
          try {
            return await fetchRun(runId);
          } catch {
            return null;
          }
        }
        if (run.status === 'rejected') {
          return null;
        }
        if (run.status === 'queued') {
          leased = await markSubmissionStarted(runId);
          if (leased) break;
        }
      }

      if (!leased) {
        // Still couldn't acquire lease or still in 'submitting'. Check if the server already processed it.
        try {
          const serverRun = await fetchRun(runId);
          if (serverRun && serverRun.status !== 'rejected') {
            await markSynced(runId);
            return serverRun;
          }
        } catch {
          // Server reconciliation 404 or request failed
        }
        return null;
      }
    }

    const samples = await loadSamples(runId);
    if (samples.length < 2) {
      console.warn(`[RunSubmission] Discarding run ${runId}: only ${samples.length} sample(s), at least 2 required to form a route.`);
      await markRejected(runId, 'insufficient_samples');
      return null;
    }

    const finalRun = await getLocalRun(runId);
    if (!finalRun?.endedAt) return null;

    try {
      const result = await submitRun({
        run_id: runId,
        started_at: finalRun.startedAt.toISOString(),
        ended_at: finalRun.endedAt.toISOString(),
        samples,
      });
      await markSynced(runId);
      return result;
    } catch (submissionError) {
      logApiRequestErrorInDev(submissionError, `POST /v1/runs run_id=${runId}`);
      if (submissionError instanceof ApiRequestError) {
        const is422 = submissionError.status === 422;
        const isNonRetryable4xx =
          submissionError.status >= 400 &&
          submissionError.status < 500 &&
          submissionError.status !== 408 &&
          submissionError.status !== 429;

        if (is422 || isNonRetryable4xx) {
          let reason = submissionError.bodyText || `HTTP ${submissionError.status}`;
          if (
            typeof submissionError.body === 'object' &&
            submissionError.body !== null &&
            'detail' in submissionError.body
          ) {
            const detail = (submissionError.body as { detail: unknown }).detail;
            reason = typeof detail === 'string' ? detail : JSON.stringify(detail);
          }
          console.warn(
            `[RunSubmission] Run ${runId} permanently rejected by server (${submissionError.status}): ${reason}`
          );
          await markRejected(runId, `server_rejection_${submissionError.status}: ${reason}`);
          return null;
        }
      }

      // If submission timed out, disconnected, or returned 5xx, the server may have completed
      // spatial processing and committed the run. Check the server by run_id before failing.
      try {
        const reconciled = await fetchRun(runId);
        if (reconciled && reconciled.status !== 'rejected') {
          console.log(`[RunSubmission] Reconciled run ${runId} via GET /v1/runs: server status=${reconciled.status}`);
          await markSynced(runId);
          return reconciled;
        } else if (reconciled?.status === 'rejected') {
          console.warn(`[RunSubmission] Run ${runId} reconciled but rejected by server.`);
          await markRejected(runId, 'server_rejection: rejected');
          return null;
        }
      } catch {
        // Server check didn't find the run or network remains unreachable
      }

      await markSubmissionFailed(runId, submissionError);
      throw submissionError;
    }
  }, []);

  const flushQueuedRuns = useCallback(async () => {
    if (flushingQueue.current) return 0;
    flushingQueue.current = true;
    let submittedCount = 0;
    try {
      const queued = await listQueuedRuns();
      for (const run of queued) {
        try {
          const result = await submitQueuedRun(run.id);
          if (result) {
            submittedCount++;
            await celebrateClaim(result).catch(() => false);
          }
        } catch (queueError) {
          logApiRequestErrorInDev(queueError, `queued run flush run_id=${run.id}`);
          // Keep the run queued; a later launch or manual refresh retries it.
          break;
        }
      }
      return submittedCount;
    } finally {
      flushingQueue.current = false;
    }
  }, [submitQueuedRun, celebrateClaim]);

  // A queued run is idempotent on its device-generated ID. Retry whenever the
  // app returns to the foreground and periodically while it remains open, so a
  // runner who regains cellular service does not need to restart the app.
  useEffect(() => {
    let retryTimer: ReturnType<typeof setInterval> | null = null;

    const retryQueuedRuns = () => {
      if (AppState.currentState !== 'active' || useRecorder.getState().status !== 'idle') return;
      void (async () => {
        try {
          const submittedCount = await flushQueuedRuns();
          if (submittedCount > 0) {
            setNotice(
              `${submittedCount} queued ${submittedCount === 1 ? 'run was' : 'runs were'} submitted.`
            );
            await refresh();
          }
        } catch (queueError) {
          logApiRequestErrorInDev(queueError, 'automatic queued run retry');
        }
      })();
    };

    retryTimer = setInterval(retryQueuedRuns, 30_000);
    const appStateSubscription = AppState.addEventListener('change', (nextState) => {
      if (nextState === 'active') retryQueuedRuns();
    });

    return () => {
      if (retryTimer) clearInterval(retryTimer);
      appStateSubscription.remove();
    };
  }, [flushQueuedRuns, refresh]);

  useEffect(() => {
    void (async () => {
      const queuedBeforeRecovery = await listQueuedRuns();
      await recoverRecorderOnce();
      const queuedAfterRecovery = await listQueuedRuns();
      const recoveredCount = Math.max(0, queuedAfterRecovery.length - queuedBeforeRecovery.length);
      const queuedBeforeFlush = queuedAfterRecovery.length;
      // Territory UI must not wait for a possibly-offline run submission. The
      // queue continues in the background and remains idempotent.
      void flushQueuedRuns().then(async () => {
        const stillQueued = (await listQueuedRuns()).length;
        const submittedCount = Math.max(0, queuedBeforeFlush - stillQueued);
        if (submittedCount > 0) {
          setNotice(`${submittedCount} queued ${submittedCount === 1 ? 'run was' : 'runs were'} submitted.`);
          await refresh();
        }
      }).catch((queueError) => logApiRequestErrorInDev(queueError, 'launch queued run retry'));
      if (recoveredCount > 0) {
        setNotice(
          `${recoveredCount} interrupted ${
            recoveredCount === 1 ? 'run was' : 'runs were'
          } saved and queued.`
        );
      }
      void refresh();
    })().catch(() => { setNotice('Could not recover saved runs. Please try again.'); void refresh(); });
  }, [flushQueuedRuns, refresh]);

  // Point-in-polygon: update activeTerritoryIds whenever the clean path grows.
  // Only runs while recording; uses the last added clean point for efficiency.
  useEffect(() => {
    if (!recording || cleanPath.length === 0) return;
    const lastPoint = cleanPath[cleanPath.length - 1];
    if (!lastPoint) return;
    const [lon, lat] = lastPoint;
    if (lon == null || lat == null) return;
    const territoryId = findActiveTerritoryId(lon, lat, territoryFeatures);
    if (!territoryId) return;
    setActiveTerritoryIds(prev => prev.has(territoryId) ? prev : new Set([...prev, territoryId]));
  }, [cleanPath, recording, territoryFeatures, territories]);

  useEffect(() => {
    if (!recording || !presentation.active || !loopCandidate.closed || !loopCandidate.polygon || announcedLoopKey.current) return;
    const ids = findLoopCandidateTerritoryIds(loopCandidate.polygon.geometry, territoryFeatures);
    announcedLoopKey.current = useRecorder.getState().runId;
    setRunEvent({ type: 'LOOP_DETECTED', areaM2: loopCandidate.areaM2, territoryIds: ids });
    useRunCues.getState().emit({ id: `${announcedLoopKey.current}:closure`, kind: 'closure', title: 'LOOP CLOSED', detail: 'Pending validation · finish to claim', coordinate: cleanPath.at(-1)!, polygon: loopCandidate.polygon, createdAt: Date.now() });
  }, [loopCandidate, recording, territoryFeatures, cleanPath, presentation.active]);

  useEffect(() => {
    if (!runEvent) return;
    const timeout = setTimeout(() => setRunEvent(null), 3500);
    return () => clearTimeout(timeout);
  }, [runEvent]);

  const onStartSimulation = useCallback(async () => {
    resetRecorderStats();
    useRunCues.getState().clear();
    setActiveTerritoryIds(new Set());
    setRunEvent(null);
    announcedLoopKey.current = null;
    try {
      await startSimulation();
      // Start at the map center so the virtual runner and joystick are usable
      // immediately. A map tap can still reposition the runner at any time.
      simulatedPosition.current = JAYANAGAR_CENTER;
      await addSimulatedPoint(JAYANAGAR_CENTER[0], JAYANAGAR_CENTER[1]);
      setNotice('Simulation active — use the joystick to move the runner.');
    } catch (simulationError) {
      logApiRequestErrorInDev(simulationError, 'start virtual run');
      setNotice('Could not start the virtual run. Try again.');
    }
  }, [startSimulation, addSimulatedPoint]);

  const onStart = useCallback(async (isVirtual: boolean = false) => {
    if (busy || useRecorder.getState().status !== 'idle') return;
    resetRecorderStats();
    useRunCues.getState().clear();
    setActiveTerritoryIds(new Set());
    setRunEvent(null);
    announcedLoopKey.current = null;
    if (developerMode && isVirtual) {
      await onStartSimulation();
      return;
    }
    await start();
  }, [busy, developerMode, onStartSimulation, start]);

  useEffect(() => {
    if (!accountChecked || !account || recording) return;

    if (params.autoStart === 'real') {
      if (autoStartHandled.current) return;
      autoStartHandled.current = true;
      router.setParams({ autoStart: undefined, runnerId: undefined });
      void onStart(false);
    } else if (params.autoStart === 'simulation') {
      if (autoStartHandled.current) return;
      autoStartHandled.current = true;
      const runnerId = params.runnerId;
      router.setParams({ autoStart: undefined, runnerId: undefined });
      if (runnerId) {
        setDevRunnerId(runnerId);
      }
      void onStart(true);
    } else {
      autoStartHandled.current = false;
    }
  }, [params.autoStart, params.runnerId, accountChecked, account, recording, router, onStart]);

  const onTerritoryPress = useCallback(async (territoryId: string) => {
    if (recording) return;
    const requestId = territoryRequest.current + 1;
    territoryRequest.current = requestId;
    setSelectedTerritory(null);
    setTerritoryBusy(true);
    try {
      const details = await fetchTerritoryDetails(territoryId);
      if (territoryRequest.current === requestId) setSelectedTerritory(details);
    } catch {
      if (territoryRequest.current === requestId) setNotice('Territory details are unavailable offline.');
    } finally {
      if (territoryRequest.current === requestId) setTerritoryBusy(false);
    }
  }, [recording]);

  const onStop = async () => {
    const finished = await stop();
    if (!finished) return;

    setBusy(true);
    try {
      const result = await submitQueuedRun(finished.runId);
      if (result) {
        const celebration = celebrateClaim(result).catch(() => false).then(played => played ? new Promise(resolve => setTimeout(resolve, 3200)) : undefined);
        await Promise.all([refresh(), celebration]);
        router.push(`/run/${result.run_id}`);
        return;
      }

      // If result is null, inspect the local run state to determine the accurate reason
      const localRun = await getLocalRun(finished.runId);
      if (localRun?.status === 'synced') {
        await refresh();
        router.push(`/run/${finished.runId}`);
        return;
      }

      if (localRun?.status === 'rejected') {
        const err = localRun.lastSubmissionError ?? '';
        if (err.includes('insufficient_samples')) {
          setNotice('Run ended. Routes require at least two distinct GPS points to claim territory.');
        } else {
          setNotice(`Run rejected: ${err.replace(/^server_rejection_\d+:\s*/, '')}`);
        }
        return;
      }

      if (localRun?.status === 'submitting') {
        setNotice('Run saved. Submission in progress…');
        return;
      }

      setNotice('Run saved on device and queued for submission.');
    } catch (submissionError) {
      logApiRequestErrorInDev(submissionError, `finish run run_id=${finished.runId}`);
      setNotice(queuedRunNotice(submissionError));
    } finally {
      setBusy(false);
    }
  };

  if (!accountChecked || !account) {
    return <View style={styles.loadingScreen}><ActivityIndicator color={colors.primary} /></View>;
  }

  return (
    <View style={styles.container}>
      <TerritoryMap
        fix={fix}
        presentationActive={presentation.active}
        reducedMotion={presentation.reducedMotion}
        economy={presentation.economy}
        simulation={isSimulation}
        bottomInset={insets.bottom + (recording ? 112 : 72)}
        territories={territories}
        capturedAreas={capturedAreas}
        ownedTerritoryAreas={ownedTerritoryAreas}
        ownedByYou={ownedByYou}
        ownedByOthers={ownedByOthers}
        traversedRoads={traversedRoads}
        loopCandidate={loopCandidate.polygon}
        activeTerritoryIds={activeTerritoryIds}
        recording={recording}
        isRunning={recording}
        onTerritoryPress={onTerritoryPress}
        onSimulationMove={developerMode && ENABLE_SIMULATION && isSimulation ? onSimulationMove : undefined}
        activationColor={activationColor}
        visibleLayers={layerMode}
        captureColorIndex={captureColorIndex}
      />

      <View pointerEvents="none" style={{ position: 'absolute', top: 0, left: 0, right: 0, height: insets.top, backgroundColor: '#081D354D' }} />
      {recording && <TelemetryPill active={presentation.active} />}
      <CueOverlay {...presentation} />
      {recording && <Pressable accessibilityRole="button" accessibilityLabel="Toggle battery saver" accessibilityState={{ selected: presentation.economy }} style={[styles.economy, { bottom: insets.bottom + 115 }]} onPress={() => useHudPreferences.getState().setEconomy(!presentation.economy)}><Text style={styles.economyText}>{presentation.economy ? '◐ BATTERY SAVER' : '◉ FULL EFFECTS'}</Text></Pressable>}
      {!recording && error && <View style={[styles.notice, { top: insets.top + 76 }]}><Text style={styles.noticeText}>{error}</Text></View>}

      {!recording && runEvent && (
        <View style={styles.runEvent} pointerEvents="none">
          <Text style={styles.runEventText}>{runEventCopy(runEvent)}</Text>
        </View>
      )}

      {developerMode && ENABLE_SIMULATION && isSimulation && (
        <View style={styles.joystickWrap}>
          <Text style={styles.joystickHint}>VIRTUAL RUNNER</Text>
          <View style={styles.joystickBase} {...joystickResponder.panHandlers}>
            <View style={[styles.joystickThumb, { transform: [{ translateX: joystickOffset.x }, { translateY: joystickOffset.y }] }]} />
          </View>
        </View>
      )}

      {(selectedTerritory || territoryBusy) && !recording && (
        <View style={styles.sheetBackdrop}>
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={() => {
              territoryRequest.current += 1;
              setSelectedTerritory(null);
              setTerritoryBusy(false);
            }}
          />
          <View style={[styles.territoryCard, { paddingBottom: insets.bottom + spacing.lg }]}> 
            <View style={styles.sheetHandle} />
            <Pressable
              onPress={() => {
                territoryRequest.current += 1;
                setSelectedTerritory(null);
                setTerritoryBusy(false);
              }}
              style={styles.closeButton}
            >
              <Text style={styles.closeText}>Close</Text>
            </Pressable>
            {territoryBusy && !selectedTerritory ? <>
              <Text style={styles.territoryTitle}>Loading territory…</Text>
              <Text style={styles.territorySubtitle}>Fetching the live leaderboard</Text>
              <ActivityIndicator color={colors.primary} />
            </> : selectedTerritory ? <>
              <Text style={styles.vitality}>● {selectedTerritory.owner_device_id ? 'THRIVING' : 'WAITING TO GROW'}</Text>
              <Text style={styles.territoryTitle}>{selectedTerritory.name}</Text>
              <Text style={styles.territorySubtitle}>{selectedTerritory.kind}{selectedTerritory.kind === 'park' || selectedTerritory.kind === 'landmark' ? ' · PROTECTED PLACE' : ''}</Text>
              {selectedTerritory.standings.length === 0 ? (
                <Text style={styles.emptyStanding}>No one has built a presence here yet. Be the runner who brings it to life.</Text>
              ) : <>
                {selectedTerritory.standings.slice(0, 1).map((leader) => <View key={leader.device_id} style={styles.leaderHero}>
                  <Text style={styles.leaderLabel}>CURRENT LEADER</Text><Text style={styles.leaderName}>{leader.is_you ? 'You' : leader.display_name}</Text>
                  <Text style={styles.leaderMeta}>{formatDistance(leader.total_distance_m)} contributed · {leader.share.toFixed(0)}%</Text>
                  <View style={styles.progressTrack}><View style={[styles.progressBar, { width: `${Math.max(8, leader.share)}%` }]} /></View>
                </View>)}
                {selectedTerritory.standings.slice(1, 5).map((standing) => <View key={standing.device_id} style={styles.standingRow}>
                  <View style={styles.standingMain}><Text style={styles.runnerName}>{standing.is_you ? 'You' : standing.display_name}</Text><View style={styles.secondaryTrack}><View style={[styles.secondaryBar, { width: `${Math.max(4, standing.share)}%` }]} /></View></View>
                  <Text style={styles.influence}>{standing.share.toFixed(0)}%</Text>
                </View>)}
              </>}
              {developerMode && <Pressable style={styles.devReset} onPress={() => Alert.alert(
                'Reset this territory?',
                'This clears only its derived standings and owner for local testing. The activity ledger stays intact.',
                [
                  { text: 'Cancel', style: 'cancel' },
                  { text: 'Reset', style: 'destructive', onPress: () => {
                    const territoryId = selectedTerritory.territory_id;
                    void resetDeveloperTerritory(territoryId).then(async () => {
                      setSelectedTerritory(null);
                      await refresh(true);
                      setNotice('Developer reset complete.');
                    }).catch(() => setNotice('Developer reset failed.'));
                  } },
                ],
              )}><Text style={styles.devResetText}>Developer: reset territory standing</Text></Pressable>}
            </> : null}
          </View>
        </View>
      )}

      {notice && (
        <Pressable
          onPress={() => void refresh(true)}
          style={[styles.notice, { top: insets.top + (recording ? 240 : 76) }]}
        >
          <Text style={styles.noticeText}>{notice}</Text>
        </Pressable>
      )}

      {/* ── Top Bar ─────────────────────────────────────── */}
      {!recording && !busy && (
        <View style={[styles.topBar, { top: insets.top + spacing.sm }]}>
          <Pressable onPress={() => router.push('/profile')} style={styles.topBarLeft}>
            <View style={styles.avatarCircle}>
              <Text style={styles.avatarText}>{account?.display_name?.slice(0, 2).toUpperCase() ?? 'AR'}</Text>
            </View>
            <View style={styles.topBarInfo}>
              <Text style={styles.topBarName} numberOfLines={1}>{account?.display_name ?? 'Runner'}</Text>
              <View style={styles.topBarStats}>
                <Text style={styles.topBarStatText}>{formatDistance(account?.total_distance_m ?? 0)}</Text>
                <Text style={styles.topBarStatDivider}>·</Text>
                <Text style={styles.topBarStatText}>{account?.territories_led ?? 0} led</Text>
              </View>
            </View>
          </Pressable>
          <Pressable accessibilityLabel="Settings" style={styles.notifBtn} onPress={() => router.push('/settings')}>
            <Feather name="sliders" size={21} color="#DBF6DE"/>
          </Pressable>
        </View>
      )}

      {/* ── Right Side Buttons ────────────────────────────── */}
      {!recording && !busy && (
        <View style={[styles.sideButtons, { top: insets.top + 72 }]}>
          <Pressable accessibilityLabel="Explore play modes" style={styles.sideBtn} onPress={() => router.push('/play')}>
            <Feather name="compass" size={22} color="#315C49"/><Text style={styles.sideBtnLabel}>Explore</Text>
          </Pressable>
          <Pressable style={[styles.sideBtn, layersPanelOpen && styles.sideBtnActive]} onPress={() => setLayersPanelOpen((v) => !v)}>
            <Feather name="layers" size={22} color="#315C49"/>
            <Text style={styles.sideBtnLabel}>Layers</Text>
          </Pressable>
          <Pressable style={styles.sideBtn} onPress={() => void refresh(true)}>
            <Feather name="refresh-cw" size={21} color="#315C49"/><Text style={styles.sideBtnLabel}>Refresh</Text>
          </Pressable>
        </View>
      )}

      {/* ── Layers Panel ──────────────────────────────────── */}
      {!recording && layersPanelOpen && (
        <View style={[styles.layersPanel, { top: insets.top + 72 }]}>
          <Pressable style={[styles.layerOption, layerMode === 'all' && styles.layerOptionActive]} onPress={() => { setLayerMode('all'); setLayersPanelOpen(false); }}>
            <View style={[styles.layerDot, { backgroundColor: colors.tabActive }]} />
            <Text style={[styles.layerText, layerMode === 'all' && styles.layerTextActive]}>All layers</Text>
          </Pressable>
          <Pressable style={[styles.layerOption, layerMode === 'territories' && styles.layerOptionActive]} onPress={() => { setLayerMode('territories'); setLayersPanelOpen(false); }}>
            <View style={[styles.layerDot, { backgroundColor: colors.ownedByOther }]} />
            <Text style={[styles.layerText, layerMode === 'territories' && styles.layerTextActive]}>Territories only</Text>
          </Pressable>
          <Pressable style={[styles.layerOption, layerMode === 'captures' && styles.layerOptionActive]} onPress={() => { setLayerMode('captures'); setLayersPanelOpen(false); }}>
            <View style={[styles.layerDot, { backgroundColor: colors.startGreen }]} />
            <Text style={[styles.layerText, layerMode === 'captures' && styles.layerTextActive]}>Captures only</Text>
          </Pressable>
        </View>
      )}

      {busy && !recording && <View style={[styles.runPanel, { paddingBottom: insets.bottom + spacing.md }]}><ActivityIndicator color="#80FFDD" /><Text style={styles.savingText}>Saving your run…</Text></View>}
      {recording && (
        <View style={[styles.runPanel, { paddingBottom: insets.bottom + spacing.md }]}>
          {error && <Text style={styles.error}>{error}</Text>}
          <Pressable onPress={onStop} disabled={busy} style={({ pressed }) => [styles.finishButton, (pressed || busy) && styles.buttonPressed]}>
            {busy ? <ActivityIndicator color={colors.surface} /> : <Text style={styles.finishButtonText}>Finish run</Text>}
          </Pressable>
        </View>
      )}

      {/* ── Tab Bar ─────────────────────────────────────── */}
      {!recording && !busy && (
        <View style={[styles.tabBar, { paddingBottom: insets.bottom }]}>
          <Pressable style={styles.tab}>
            <Feather name="map" size={23} color="#A5EDBF"/>
            <Text style={[styles.tabLabel, styles.tabLabelActive]}>Map</Text>
          </Pressable>
          <Pressable style={styles.tab} onPress={() => router.push('/play')}>
            <View style={{backgroundColor:"#BBF37E",borderRadius:22,paddingHorizontal:22,paddingVertical:10,marginTop:-18,marginBottom:4}}><Feather name="navigation" size={24} color="#1B4434"/></View>
            <Text style={styles.tabLabel}>Play</Text>
          </Pressable>
          <Pressable style={styles.tab} onPress={() => router.push('/profile')}>
            <Feather name="user" size={23} color="#94AD9F"/>
            <Text style={styles.tabLabel}>Profile</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  savingText: { color: '#DBFFF3', textAlign: 'center', paddingTop: 10 },
  economy: { position: 'absolute', left: 16, padding: 12, backgroundColor: '#0A1929EF', borderRadius: 18 },
  economyText: { color: '#B6E9D9', fontSize: 10, fontWeight: '700', letterSpacing: 0.6 },
  container: { flex: 1, backgroundColor: colors.background },
  loadingScreen: { flex: 1, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center' },
  notice: { position: 'absolute', zIndex: 10, alignSelf: 'center', backgroundColor: colors.text, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.pill },
  noticeText: { color: colors.surface, fontSize: fontSize.xs },

  // ── Top Bar ─────────────────────────────────────────
  topBar: { position: 'absolute', left: spacing.md, right: spacing.md, zIndex: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  topBarLeft: { flexDirection: 'row', alignItems: 'center', backgroundColor: 'rgba(15, 23, 35, 0.88)', borderRadius: radius.pill, paddingRight: spacing.md, paddingVertical: 6, paddingLeft: 6 },
  avatarCircle: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#1E293B', borderWidth: 2, borderColor: colors.tabActive, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: colors.surface, fontSize: 13, fontWeight: fontWeight.bold },
  topBarInfo: { marginLeft: spacing.sm },
  topBarName: { color: colors.surface, fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  topBarStats: { flexDirection: 'row', alignItems: 'center', marginTop: 1 },
  topBarStatText: { color: colors.tabActive, fontSize: 11 },
  topBarStatDivider: { color: '#475569', marginHorizontal: 4, fontSize: 11 },
  notifBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(15, 23, 35, 0.88)', alignItems: 'center', justifyContent: 'center' },
  notifIcon: { color: colors.surface, fontSize: 18 },

  // ── Right Side Buttons ──────────────────────────────
  sideButtons: { position: 'absolute', right: spacing.md, zIndex: 7, gap: spacing.sm },
  sideBtn: { width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(255, 255, 255, 0.92)', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 6, elevation: 4 },
  sideBtnActive: { backgroundColor: colors.tabActive },
  sideBtnIcon: { fontSize: 20, color: '#334155' },
  sideBtnLabel: { fontSize: 8, fontWeight: fontWeight.bold, color: '#334155', marginTop: 1 },

  // ── Layers Panel ────────────────────────────────────
  layersPanel: { position: 'absolute', right: 68, zIndex: 9, backgroundColor: 'rgba(15, 23, 35, 0.92)', borderRadius: radius.lg, padding: spacing.sm, gap: 2 },
  layerOption: { flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.md },
  layerOptionActive: { backgroundColor: 'rgba(45, 212, 191, 0.15)' },
  layerDot: { width: 10, height: 10, borderRadius: 5, marginRight: spacing.sm },
  layerText: { color: '#94A3B8', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  layerTextActive: { color: colors.tabActive },

  // ── Legend ──────────────────────────────────────────
  legend: { position: 'absolute', left: spacing.md, zIndex: 6, backgroundColor: 'rgba(15, 23, 35, 0.88)', borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  legendItem: { flexDirection: 'row', alignItems: 'center' },
  legendDot: { width: 10, height: 10, borderRadius: 5, marginRight: spacing.sm },
  legendText: { color: colors.surface, fontSize: fontSize.xs },

  // ── Capture HUD / Run Events ────────────────────────
  captureHud: { position: 'absolute', zIndex: 2, left: spacing.md, backgroundColor: 'rgba(17, 24, 39, 0.9)', borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  captureHudText: { color: colors.surface, fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  captureHudSub: { color: colors.route, fontSize: fontSize.xs, marginTop: 2 },
  runEvent: { position: 'absolute', zIndex: 4, top: '35%', alignSelf: 'center', backgroundColor: 'rgba(10, 20, 30, 0.92)', paddingHorizontal: spacing.xl, paddingVertical: spacing.lg, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.route },
  runEventText: { color: colors.surface, fontSize: fontSize.md, fontWeight: fontWeight.bold, textAlign: 'center', lineHeight: 24 },

  // ── Territory Detail Sheet ──────────────────────────
  sheetBackdrop: { ...StyleSheet.absoluteFillObject, zIndex: 12, backgroundColor: 'rgba(8, 24, 22, 0.42)', justifyContent: 'flex-end' },
  territoryCard: { backgroundColor: '#F8FFF1', borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, shadowColor: '#000', shadowOpacity: 0.22, shadowRadius: 18, elevation: 9 },
  sheetHandle: { alignSelf: 'center', width: 44, height: 5, borderRadius: 4, backgroundColor: '#B8C7AA', marginBottom: spacing.xs },
  closeButton: { alignSelf: 'flex-end', padding: spacing.xs },
  closeText: { color: colors.primary, fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  territoryTitle: { color: colors.text, fontSize: fontSize.lg, fontWeight: fontWeight.semibold },
  vitality: { color: '#4A9B52', fontSize: 11, fontWeight: fontWeight.bold, letterSpacing: 1, marginBottom: 4 },
  territorySubtitle: { color: colors.textMuted, fontSize: fontSize.xs, marginTop: 2, marginBottom: spacing.sm },
  emptyStanding: { color: colors.textMuted, fontSize: fontSize.sm, paddingVertical: spacing.sm },
  leaderHero: { backgroundColor: '#E3F4D8', padding: spacing.md, borderRadius: radius.md, marginTop: spacing.sm, marginBottom: spacing.sm },
  leaderLabel: { color: '#56804A', fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 1 },
  leaderName: { color: '#193424', fontSize: fontSize.lg, fontWeight: fontWeight.bold, marginTop: 2 },
  leaderMeta: { color: '#55705C', fontSize: fontSize.xs, marginTop: 3 },
  progressTrack: { height: 7, backgroundColor: '#C7DFC0', borderRadius: 6, overflow: 'hidden', marginTop: spacing.sm },
  progressBar: { height: '100%', backgroundColor: '#4DAA57', borderRadius: 6 },
  standingRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.xs, borderTopWidth: 1, borderTopColor: colors.border },
  rank: { width: 24, color: colors.textMuted, fontWeight: fontWeight.semibold },
  standingMain: { flex: 1 },
  runnerName: { color: colors.text, fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  runnerMeta: { color: colors.textMuted, fontSize: fontSize.xs, marginTop: 2 },
  influence: { color: colors.primary, fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  secondaryTrack: { height: 4, backgroundColor: '#E0E8D8', borderRadius: 4, overflow: 'hidden', marginTop: 5 },
  secondaryBar: { height: '100%', backgroundColor: '#8DBB76', borderRadius: 4 },
  devReset: { marginTop: spacing.md, borderWidth: 1, borderColor: '#D92D20', borderRadius: radius.md, padding: spacing.sm, alignItems: 'center' },
  devResetText: { color: '#B42318', fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  // ── Run Panel (recording state) ─────────────────────
  runPanel: { position: 'absolute', bottom: 0, left: 0, right: 0, backgroundColor: '#0A1929F5', paddingHorizontal: spacing.lg, paddingTop: spacing.md, borderTopLeftRadius: 24, borderTopRightRadius: 24 },
  stats: { flexDirection: 'row', justifyContent: 'space-around', marginBottom: spacing.md },
  runStats: { marginTop: spacing.lg, marginBottom: spacing.xl },
  stat: { alignItems: 'center' },
  statValue: { fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: colors.text },
  runStatValue: { fontSize: 27, letterSpacing: -0.8, fontWeight: fontWeight.bold },
  statLabel: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 2 },
  error: { color: colors.danger, fontSize: fontSize.sm, marginBottom: spacing.sm, paddingHorizontal: spacing.lg },
  finishButton: { backgroundColor: colors.danger, paddingVertical: spacing.md, borderRadius: radius.md, alignItems: 'center' },
  finishButtonText: { color: colors.surface, fontSize: fontSize.md, fontWeight: fontWeight.semibold },
  buttonPressed: { opacity: 0.7 },

  // ── Bottom Action Bar ───────────────────────────────
  bottomBar: { position: 'absolute', left: spacing.md, right: spacing.md, zIndex: 6 },
  bottomBarCard: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: 'rgba(15, 23, 35, 0.92)', borderRadius: 20, paddingLeft: spacing.md, paddingRight: 6, paddingVertical: 10, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 12, elevation: 8 },
  bottomBarLeft: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  runnerIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(45, 212, 191, 0.15)', alignItems: 'center', justifyContent: 'center', marginRight: spacing.sm },
  runnerIconText: { color: colors.tabActive, fontSize: 18 },
  bottomBarTitle: { color: colors.surface, fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  bottomBarSub: { color: '#94A3B8', fontSize: 11, lineHeight: 14, marginTop: 1 },
  startBtn: { backgroundColor: colors.tabActive, paddingHorizontal: 20, paddingVertical: 12, borderRadius: radius.pill },
  startBtnText: { color: '#042F2E', fontSize: 13, fontWeight: fontWeight.bold, letterSpacing: 1.2 },

  // ── Dev Simulation Controls ─────────────────────────
  devControls: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.sm, flexWrap: 'wrap' },
  simPill: { paddingHorizontal: spacing.md, paddingVertical: 5, borderRadius: radius.pill, borderWidth: 1, borderColor: 'rgba(255,255,255,0.2)', backgroundColor: 'rgba(15,23,35,0.8)' },
  simPillActive: { borderColor: colors.route, backgroundColor: '#071923' },
  simPillText: { color: '#94A3B8', fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  simPillTextActive: { color: colors.route },
  devRunnerChip: { paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.pill, borderWidth: 1, borderColor: 'rgba(255,255,255,0.15)', backgroundColor: 'rgba(15,23,35,0.8)' },
  devRunnerChipActive: { backgroundColor: '#E2F5DD', borderColor: '#55A85E' },
  devRunnerChipText: { color: '#94A3B8', fontSize: 10, fontWeight: fontWeight.semibold },
  devRunnerChipTextActive: { color: '#276936' },

  // ── Tab Bar ─────────────────────────────────────────
  tabBar: { position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 5, flexDirection: 'row', backgroundColor: 'rgba(15, 23, 35, 0.95)', borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.08)', paddingTop: spacing.sm },
  tab: { flex: 1, alignItems: 'center', paddingVertical: spacing.xs },
  tabIcon: { fontSize: 20, color: '#64748B', marginBottom: 2 },
  tabIconActive: { color: colors.tabActive },
  tabLabel: { fontSize: 10, fontWeight: fontWeight.semibold, color: '#64748B' },
  tabLabelActive: { color: colors.tabActive },

  // ── Joystick ────────────────────────────────────────
  joystickWrap: { position: 'absolute', left: spacing.lg, bottom: 200, zIndex: 9, alignItems: 'center' },
  joystickHint: { color: colors.surface, fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 0.8, marginBottom: 6, textShadowColor: '#000', textShadowRadius: 4 },
  joystickBase: { width: 104, height: 104, borderRadius: 52, backgroundColor: 'rgba(7, 25, 35, 0.72)', borderWidth: 1, borderColor: 'rgba(0, 229, 255, 0.65)', alignItems: 'center', justifyContent: 'center' },
  joystickThumb: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.route, borderWidth: 3, borderColor: colors.surface, shadowColor: colors.route, shadowOpacity: 0.8, shadowRadius: 8, elevation: 4 },
});


