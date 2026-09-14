import { useEffect, useMemo, useRef, useState } from 'react';
import type { RunFix } from './telemetry';
import { lightingPalette, type WeatherReading } from './lighting';
import { useHudPreferences } from './usePresentation';
import { getWeatherCache, setWeatherCache } from './weatherCache';

const TTL = 15 * 60_000;
/** Weather requests use a ~1 km coordinate, never the full route or identity. */
export function useLighting(fix: RunFix | null, active: boolean, simulation: boolean) {
  const enabled = useHudPreferences(s => s.weather);
  const [now, setNow] = useState(() => new Date());
  const [weather, setWeather] = useState<WeatherReading | null>(getWeatherCache);
  const latest = useRef(fix); latest.current = fix;
  const hasFix = Boolean(fix);
  useEffect(() => {
    if (!active) return;
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, [active]);
  useEffect(() => {
    if (!active || !enabled || simulation || !hasFix) return;
    let cancelled = false;
    let controller: AbortController | null = null;
    let pending = false;
    const refresh = async () => {
      const current = latest.current;
      if (!current || Date.now() - current.ts > 120_000 || pending) return;
      const lon = current.coordinate[0].toFixed(2), lat = current.coordinate[1].toFixed(2), cell = `${lat},${lon}`;
      const cached = getWeatherCache(); if (cached && cached.cell === cell && Date.now() - cached.fetchedAt < TTL) { setWeather(cached); return; }
      pending = true; controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 6000);
      try {
        const response = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=weather_code,cloud_cover,temperature_2m&daily=sunrise,sunset&timezone=auto&timeformat=unixtime&forecast_days=1`, { signal: controller.signal });
        if (!response.ok) throw new Error('Weather unavailable');
        const body = await response.json();
        const code: unknown = body.current?.weather_code, cloud: unknown = body.current?.cloud_cover, observed: unknown = body.current?.time;
        if (typeof code !== 'number' || !Number.isFinite(code) || typeof cloud !== 'number' || !Number.isFinite(cloud) || typeof observed !== 'number' || Math.abs(Date.now() - observed * 1000) > 90 * 60_000) throw new Error('Invalid weather');
        const reading: WeatherReading = { code, cloud, observedAt: observed * 1000, fetchedAt: Date.now(), cell, temperatureC: typeof body.current?.temperature_2m === 'number' && Number.isFinite(body.current.temperature_2m) ? body.current.temperature_2m : null, sunrise: typeof body.daily?.sunrise?.[0] === 'number' ? body.daily.sunrise[0] * 1000 : null, sunset: typeof body.daily?.sunset?.[0] === 'number' ? body.daily.sunset[0] * 1000 : null };
        if (!cancelled) { setWeatherCache(reading); setWeather(reading); }
      } catch { /* Time palette remains available offline; stale weather expires below. */ }
      finally { clearTimeout(timeout); pending = false; }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), TTL);
    return () => { cancelled = true; controller?.abort(); clearInterval(timer); };
  }, [active, enabled, simulation, hasFix]);
  return useMemo(() => lightingPalette(now, enabled && !simulation && weather && now.getTime() - weather.observedAt < 90 * 60_000 ? weather : null), [now, weather, enabled, simulation]);
}
