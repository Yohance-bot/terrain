import type { WeatherReading } from './lighting';

/**
 * The latest weather reading, shared outside React.
 *
 * The lighting hook fills it; the recorder reads it when a run starts. Kept in
 * its own module so the recorder never imports a hook to get at it.
 */
let latest: WeatherReading | null = null;

export function getWeatherCache(): WeatherReading | null {
  return latest;
}

export function setWeatherCache(reading: WeatherReading): void {
  latest = reading;
}

/** Conditions for a run starting now, if the reading is fresh enough to describe it. */
export function currentConditions(): { temperature_c: number | null; weather_code: number } | null {
  if (!latest || Date.now() - latest.observedAt > 90 * 60_000) return null;
  return { temperature_c: latest.temperatureC, weather_code: latest.code };
}
