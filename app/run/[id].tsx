import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { TerritoryMap } from '@/features/map/TerritoryMap';
import { loadSamples } from '@/lib/db';
import { formatDistance, formatDuration } from '@/lib/geo';
import { cleanGps, type GeoCoord } from '@/lib/gpsClean';
import { buildTraversedRoads, detectLoopCandidate } from '@/lib/runCapture';
import { fetchRun } from '@/services/api/client';
import type { RunResult } from '@/services/api/types';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

/**
 * The post-run reveal. The only place in the app where territory information
 * appears, per `01_CORE_MECHANICS` Chapter 10.
 *
 * Everything shown here is computed on the server. The screen renders a result;
 * it does not decide one.
 */
export default function RunSummaryScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [completedPath, setCompletedPath] = useState<GeoCoord[]>([]);

  // Entrance animation
  const heroFade = useRef(new Animated.Value(0)).current;
  const heroSlide = useRef(new Animated.Value(30)).current;
  const statsFade = useRef(new Animated.Value(0)).current;
  const captureScale = useRef(new Animated.Value(0.8)).current;
  const captureFade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!id) return;
    fetchRun(id)
      .then(setResult)
      .catch(() => setError('Could not load this run.'));
    loadSamples(id)
      .then((samples) => setCompletedPath(cleanGps(samples.map((sample) => ({
        lat: sample.lat,
        lon: sample.lon,
        accuracy: sample.accuracy_m ?? undefined,
      }))).cleanedPath))
      // The authoritative result is still useful if local history was cleared.
      .catch(() => setCompletedPath([]));
  }, [id]);

  // Staggered entrance when result loads
  useEffect(() => {
    if (!result) return;
    Animated.stagger(150, [
      Animated.parallel([
        Animated.timing(heroFade, { toValue: 1, duration: 500, useNativeDriver: true }),
        Animated.timing(heroSlide, { toValue: 0, duration: 500, useNativeDriver: true }),
      ]),
      Animated.timing(statsFade, { toValue: 1, duration: 400, useNativeDriver: true }),
      Animated.parallel([
        Animated.spring(captureScale, { toValue: 1, friction: 6, useNativeDriver: true }),
        Animated.timing(captureFade, { toValue: 1, duration: 350, useNativeDriver: true }),
      ]),
    ]).start();
  }, [result, heroFade, heroSlide, statsFade, captureScale, captureFade]);

  if (error) {
    return (
      <View style={styles.centered}>
        <Text style={styles.error}>{error}</Text>
      </View>
    );
  }

  if (!result) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.revealAccent} />
      </View>
    );
  }

  const isApplied = result.status === 'applied';
  const newlyYours = result.segments.filter(
    (segment) => segment.ownership_changed && segment.is_owned_by_you
  );
  const otherOwnershipChanges = result.segments.filter(
    (segment) => segment.ownership_changed && !segment.is_owned_by_you
  );
  const outcome = getOutcome({
    status: result.status,
    newlyYours,
    otherOwnershipChanges,
    hasSegments: result.segments.length > 0,
  });
  const confirmedLoopCaptures = result.segments.filter(
    (segment) => segment.capture_method === 'loop' && segment.is_owned_by_you,
  );
  const defended = confirmedLoopCaptures.filter((segment) => !segment.ownership_changed);
  const captureCount = confirmedLoopCaptures.length;
  const traversedRoads = buildTraversedRoads(completedPath);
  const loopCandidate = detectLoopCandidate(completedPath);
  const hasCaptured = captureCount > 0;
  const ctaText = hasCaptured ? 'Claim your territory' : 'Keep running';

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>

        {/* ── Hero Section ─────────────────────────── */}
        <Animated.View style={{ opacity: heroFade, transform: [{ translateY: heroSlide }] }}>
          <Text style={styles.eyebrow}>{outcome.eyebrow}</Text>
          <Text style={styles.heading}>{outcome.title}</Text>
          <Text style={styles.outcomeDetail}>{outcome.detail}</Text>
        </Animated.View>

        {/* ── Stats Card ──────────────────────────── */}
        <Animated.View style={[styles.statsCard, { opacity: statsFade }]}>
          <RevealStat label="Distance" value={formatDistance(result.distance_m)} accent />
          <View style={styles.statDivider} />
          <RevealStat label="Time" value={formatDuration(result.duration_s)} />
          <View style={styles.statDivider} />
          <RevealStat label="Pace" value={result.distance_m > 0 ? `${formatDuration((result.duration_s * 1000) / result.distance_m)}/km` : '—'} />
        </Animated.View>

        {/* ── Capture Hero ────────────────────────── */}
        <Animated.View style={[styles.captureHero, { opacity: captureFade, transform: [{ scale: captureScale }] }]}>
          <View style={styles.captureGlowBorder}>
            <Text style={styles.captureCount}>{captureCount}</Text>
            <Text style={styles.captureLabel}>
              {captureCount === 1 ? 'TERRITORY CAPTURED' : 'TERRITORIES CAPTURED'}
            </Text>
            {captureCount > 0 && (
              <Text style={styles.captureMeta}>
                {captureCount - defended.length} new · {defended.length} defended
              </Text>
            )}
          </View>
          {/* List each captured territory */}
          {confirmedLoopCaptures.map((seg) => (
            <View key={seg.territory_id} style={styles.captureItem}>
              <View style={styles.captureCheck} />
              <Text style={styles.captureItemName}>{seg.name}</Text>
              <Text style={styles.captureItemBadge}>
                {seg.ownership_changed ? 'NEW' : 'HELD'}
              </Text>
            </View>
          ))}
        </Animated.View>

        {/* ── Map ─────────────────────────────────── */}
        {completedPath.length > 1 && (
          <View style={styles.mapFrame}>
            <TerritoryMap
              territories={null}
              capturedAreas={null}
              ownedByYou={new Set(result.segments.filter((segment) => segment.is_owned_by_you).map((segment) => segment.territory_id))}
              ownedByOthers={new Set()}
              traversedRoads={traversedRoads}
              loopCandidate={loopCandidate.polygon}
              activeTerritoryIds={new Set(result.segments.map((segment) => segment.territory_id))}
              justCapturedTerritoryIds={new Set(confirmedLoopCaptures.map((segment) => segment.territory_id))}
              recording={false}
            />
          </View>
        )}

        {/* ── Territory Segments ──────────────────── */}
        <Text style={styles.sectionTitle}>
          {isApplied ? 'Territory breakdown' : 'Detected segments'}
        </Text>

        {result.segments.length === 0 ? (
          <Text style={styles.empty}>
            {isApplied
              ? 'No qualifying territory segments were recorded for this run.'
              : 'No territory segments are available while this run is processing.'}
          </Text>
        ) : (
          result.segments.map((segment) => {
            const badgeInfo = isApplied
              ? getSegmentBadge(segment)
              : { label: 'Processing', color: colors.textMuted };
            const maxInfluence = Math.max(...result.segments.map((s) => s.influence_granted), 1);
            const influencePercent = Math.max(8, (segment.influence_granted / maxInfluence) * 100);

            return (
              <View key={segment.territory_id} style={styles.segmentCard}>
                <View style={[styles.segmentAccent, { backgroundColor: badgeInfo.color }]} />
                <View style={styles.segmentContent}>
                  <View style={styles.segmentHeader}>
                    <Text style={styles.segmentName}>{segment.name}</Text>
                    <View style={[styles.segmentBadge, { backgroundColor: badgeInfo.color }]}>
                      <Text style={styles.segmentBadgeText}>{badgeInfo.label}</Text>
                    </View>
                  </View>
                  <Text style={styles.segmentMeta}>
                    {formatDistance(segment.distance_m)} in {formatDuration(segment.seconds_in)}
                  </Text>
                  <View style={styles.influenceRow}>
                    <Text style={styles.influenceLabel}>
                      +{Math.round(segment.influence_granted)} influence
                    </Text>
                    <Text style={styles.legacyLabel}>
                      {Math.round(segment.legacy_influence)} legacy
                    </Text>
                  </View>
                  <View style={styles.influenceTrack}>
                    <View style={[styles.influenceBar, { width: `${influencePercent}%`, backgroundColor: badgeInfo.color }]} />
                  </View>
                </View>
              </View>
            );
          })
        )}

        {result.samples_dropped > 0 && (
          <Text style={styles.footnote}>
            {result.samples_dropped} GPS fixes were too inaccurate to use.
          </Text>
        )}
      </ScrollView>

      {/* ── Footer CTA ────────────────────────────── */}
      <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        <Pressable
          onPress={() => router.replace('/')}
          style={({ pressed }) => [
            styles.ctaButton,
            hasCaptured && styles.ctaButtonCapture,
            pressed && styles.ctaButtonPressed,
          ]}
        >
          <Text style={[styles.ctaButtonText, hasCaptured && styles.ctaButtonTextCapture]}>
            {ctaText}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

function getOutcome({
  status,
  newlyYours,
  otherOwnershipChanges,
  hasSegments,
}: {
  status: RunResult['status'];
  newlyYours: RunResult['segments'];
  otherOwnershipChanges: RunResult['segments'];
  hasSegments: boolean;
}) {
  if (status === 'rejected') {
    return {
      eyebrow: 'RUN REVIEWED',
      title: 'This run could not be applied',
      detail: 'It did not change territory standings or personal progression.',
    };
  }

  if (status === 'provisional' || status === 'challenged') {
    return {
      eyebrow: 'UNDER REVIEW',
      title: 'Territory changes are being verified',
      detail: 'Your personal run record is saved. Territory influence will wait for review.',
    };
  }

  if (status === 'reversed') {
    return {
      eyebrow: 'CORRECTED',
      title: 'Territory standings were adjusted',
      detail: 'This run no longer contributes influence to territory standings.',
    };
  }

  if (status !== 'applied') {
    return {
      eyebrow: 'PROCESSING',
      title: 'Your run is being processed',
      detail: 'Segment details are shown below. Ownership is not final until processing completes.',
    };
  }

  if (newlyYours.length > 0) {
    const names = newlyYours.map((s) => s.name);
    const count = names.length;
    return {
      eyebrow: 'TERRITORY CLAIMED',
      title: count === 1
        ? `You now own ${names[0]}`
        : `You dominated ${count} territories`,
      detail: count === 1
        ? 'Your presence changed the map. Keep it up.'
        : `${names.join(', ')} — all yours now.`,
    };
  }

  if (otherOwnershipChanges.length > 0) {
    return {
      eyebrow: 'OWNERSHIP SHIFTED',
      title: 'The map changed around you',
      detail: `${otherOwnershipChanges.map((s) => s.name).join(', ')} changed hands this run.`,
    };
  }

  return {
    eyebrow: hasSegments ? 'CONTRIBUTION LOGGED' : 'RUN COMPLETE',
    title: hasSegments ? 'Your presence is growing' : 'Good run, keep going',
    detail: hasSegments
      ? 'Every metre counts. Your influence has been added to the territories you crossed.'
      : 'This run didn\'t cross a qualifying territory segment, but you\'re still building momentum.',
  };
}

function getSegmentBadge(segment: RunResult['segments'][number]) {
  if (segment.ownership_changed && segment.is_owned_by_you) {
    return { label: 'Claimed', color: colors.revealAccent };
  }
  if (segment.ownership_changed) {
    return { label: 'Changed', color: colors.revealGold };
  }
  if (segment.is_owned_by_you) {
    return { label: 'Yours', color: colors.ownedByYou };
  }
  return segment.owner_device_id
    ? { label: 'Rival', color: colors.ownedByOther }
    : { label: 'Unclaimed', color: colors.unclaimed };
}

function RevealStat({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <View style={styles.revealStat}>
      <Text style={[styles.revealStatValue, accent && styles.revealStatValueAccent]}>{value}</Text>
      <Text style={styles.revealStatLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.revealBg },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.revealBg },
  content: { padding: spacing.lg, paddingBottom: spacing.xxl },
  error: { color: colors.danger, fontSize: fontSize.sm },

  // Hero
  eyebrow: {
    fontSize: 11,
    fontWeight: fontWeight.bold,
    color: colors.revealAccent,
    letterSpacing: 2,
    marginBottom: spacing.xs,
  },
  heading: {
    fontSize: 28,
    fontWeight: fontWeight.bold,
    color: colors.surface,
    lineHeight: 34,
  },
  outcomeDetail: {
    fontSize: fontSize.sm,
    color: '#94A3B8',
    marginTop: spacing.sm,
    marginBottom: spacing.lg,
    lineHeight: 20,
  },

  // Stats card
  statsCard: {
    flexDirection: 'row',
    backgroundColor: colors.revealCardBg,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.revealCardBorder,
    paddingVertical: spacing.lg,
    marginBottom: spacing.lg,
  },
  revealStat: { flex: 1, alignItems: 'center' },
  revealStatValue: { fontSize: 22, fontWeight: fontWeight.bold, color: colors.surface },
  revealStatValueAccent: { color: colors.revealAccent },
  revealStatLabel: { fontSize: fontSize.xs, color: '#64748B', marginTop: 4 },
  statDivider: { width: 1, backgroundColor: colors.revealCardBorder, marginVertical: spacing.xs },

  // Capture hero
  captureHero: {
    marginBottom: spacing.lg,
  },
  captureGlowBorder: {
    alignItems: 'center',
    backgroundColor: colors.revealCardBg,
    borderRadius: radius.lg,
    paddingVertical: spacing.xl,
    borderWidth: 1.5,
    borderColor: colors.revealAccent,
    shadowColor: colors.revealAccent,
    shadowOpacity: 0.3,
    shadowRadius: 20,
    elevation: 8,
  },
  captureCount: {
    color: colors.surface,
    fontSize: 56,
    fontWeight: fontWeight.bold,
    lineHeight: 62,
  },
  captureLabel: {
    color: colors.revealAccent,
    fontSize: 11,
    fontWeight: fontWeight.bold,
    letterSpacing: 1.5,
    marginTop: 4,
  },
  captureMeta: {
    color: '#64748B',
    fontSize: fontSize.sm,
    marginTop: spacing.xs,
  },
  captureItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.revealCardBg,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: colors.revealCardBorder,
  },
  captureCheck: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.revealAccent,
    marginRight: spacing.sm,
  },
  captureItemName: {
    flex: 1,
    color: colors.surface,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
  },
  captureItemBadge: {
    fontSize: 10,
    fontWeight: fontWeight.bold,
    color: colors.revealAccent,
    letterSpacing: 1,
  },

  // Map
  mapFrame: {
    height: 250,
    overflow: 'hidden',
    borderRadius: radius.lg,
    marginBottom: spacing.lg,
    borderWidth: 1,
    borderColor: colors.revealCardBorder,
  },

  // Territory segments
  sectionTitle: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.bold,
    color: '#64748B',
    textTransform: 'uppercase',
    letterSpacing: 1.2,
    marginBottom: spacing.md,
  },
  empty: { color: '#64748B', fontSize: fontSize.sm, lineHeight: 20 },

  segmentCard: {
    flexDirection: 'row',
    backgroundColor: colors.revealCardBg,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.revealCardBorder,
  },
  segmentAccent: {
    width: 4,
  },
  segmentContent: {
    flex: 1,
    padding: spacing.md,
  },
  segmentHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  segmentName: {
    fontSize: fontSize.md,
    color: colors.surface,
    fontWeight: fontWeight.semibold,
    flex: 1,
  },
  segmentBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  segmentBadgeText: {
    fontSize: 10,
    fontWeight: fontWeight.bold,
    color: colors.revealBg,
    letterSpacing: 0.5,
  },
  segmentMeta: {
    fontSize: fontSize.xs,
    color: '#64748B',
    marginBottom: spacing.sm,
  },
  influenceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  influenceLabel: {
    fontSize: fontSize.xs,
    color: colors.revealAccent,
    fontWeight: fontWeight.semibold,
  },
  legacyLabel: {
    fontSize: fontSize.xs,
    color: '#64748B',
  },
  influenceTrack: {
    height: 4,
    backgroundColor: '#1E293B',
    borderRadius: 4,
    overflow: 'hidden',
  },
  influenceBar: {
    height: '100%',
    borderRadius: 4,
  },

  footnote: {
    marginTop: spacing.lg,
    fontSize: fontSize.xs,
    color: '#475569',
  },

  // Footer
  footer: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.revealCardBorder,
    backgroundColor: colors.revealBg,
  },
  ctaButton: {
    backgroundColor: colors.surface,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    alignItems: 'center',
  },
  ctaButtonCapture: {
    backgroundColor: colors.revealAccent,
  },
  ctaButtonPressed: { opacity: 0.7 },
  ctaButtonText: {
    color: colors.revealBg,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
    letterSpacing: 0.5,
  },
  ctaButtonTextCapture: {
    color: '#042F2E',
  },
});
