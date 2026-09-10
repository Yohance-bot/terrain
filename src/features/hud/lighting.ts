export type WeatherReading = { code: number; cloud: number; observedAt: number; fetchedAt: number; sunrise: number | null; sunset: number | null; cell: string };
export function daylight(now: Date, weather: WeatherReading | null): number {
  const time = now.getTime();
  if (weather?.sunrise && weather.sunset && time >= weather.sunrise - 6 * 3600000 && time <= weather.sunset + 6 * 3600000) {
    return Math.max(0, Math.min(1, (time - weather.sunrise + 1800000) / 3600000, (weather.sunset - time + 1800000) / 3600000));
  }
  // Device local time works offline and updates after timezone changes on resume.
  const hour = now.getHours() + now.getMinutes() / 60;
  return Math.max(0, Math.min(1, (hour - 5.5), (18.5 - hour)));
}
export function mixColor(a: string, b: string, amount: number): string {
  const t = Math.max(0, Math.min(1, amount));
  return '#' + [1, 3, 5].map(i => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - t) + parseInt(b.slice(i, i + 2), 16) * t).toString(16).padStart(2, '0')).join('');
}
export function weatherKind(code: number, cloud: number): string {
  if (code >= 95) return 'Storm';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'Snow';
  if (code >= 51 && code <= 82) return 'Rain';
  if (code === 45 || code === 48) return 'Fog';
  return cloud > 50 ? 'Cloudy' : 'Clear';
}
export function lightingPalette(now: Date, weather: WeatherReading | null) {
  const day = daylight(now, weather);
  const kind = weather ? weatherKind(weather.code, weather.cloud) : null;
  const rain = kind === 'Rain' || kind === 'Storm';
  const haze = weather ? (rain ? 0.28 : Math.min(0.2, weather.cloud / 500)) : 0;
  const blend = (night: string, light: string) => mixColor(mixColor(night, light, day), kind === 'Snow' ? '#B9D1DF' : kind === 'Storm' ? '#655C87' : rain ? '#526D84' : '#8A9EA6', haze);
  return {
    background: blend('#153447', '#D9EEDC'), land: blend('#244A54', '#BEDCCB'), park: blend('#23635D', '#80C89B'),
    water: blend('#174F71', '#8FCBD9'), road: blend('#88ADB0', '#F7F4EC'), casing: blend('#416F7C', '#B4C3B6'),
    avenue: blend('#A7B8AB', '#F1E9D5'), path: blend('#6DAFA0', '#DCEBDD'), roadMarking: blend('#CEE1D0', '#CFC6B2'),
    building: blend('#56768B', '#F0EDE5'), roof: blend('#95B2C2', '#F5F2EA'), roofAccent: blend('#67AFB8', '#DDBB92'),
    // Rooftop objects: light utility volumes and dark solar arrays.
    structure: blend('#3E5568', '#D5DAD3'), panel: blend('#1B2740', '#44567E'), doorway: blend('#241C16', '#9C7A5C'),
    label: blend('#D5E4EA', '#334D44'), halo: blend('#102238', '#EBF2DE'),
    name: `${day < 0.25 ? 'Night' : day < 0.8 ? 'Twilight' : 'Day'}${weather ? ` · ${kind}` : ' · Time only'}`,
  };
}
