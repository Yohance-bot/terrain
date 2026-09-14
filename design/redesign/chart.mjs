// Weekly distance columns: one series, current week emphasised, past weeks a
// lighter step of the same green. 4px rounded caps, square baseline.
const W = 350, H = 164, left = 30, top = 8, base = 136, max = 30;
const plotW = W - left, band = plotW / 12, barW = 14;
const y = v => base - (v * (base - top)) / max;
const r1 = n => Math.round(n * 10) / 10;
function chart(values, labels) {
  const out = [`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" fill="none">`];
  for (const t of [0, 10, 20, 30]) {
    const gy = r1(y(t)) + 0.5;
    out.push(`<line x1="${left}" x2="${W}" y1="${gy}" y2="${gy}" stroke="#E2E6E0" stroke-width="1"></line>`);
    out.push(`<text x="${left - 8}" y="${r1(y(t)) + 4}" text-anchor="end" font-size="11" font-weight="500" fill="#8A958E" font-family="Barlow, sans-serif">${t}</text>`);
  }
  values.forEach((v, i) => {
    if (v <= 0) return;
    const x = r1(left + i * band + (band - barW) / 2), t = r1(y(v)), h = base - t, r = Math.min(4, h);
    const fill = i === values.length - 1 ? '#1F7A4D' : '#A8CDB6';
    out.push(`<path d="M${x} ${base}V${r1(t + r)}Q${x} ${t} ${r1(x + r)} ${t}H${r1(x + barW - r)}Q${r1(x + barW)} ${t} ${r1(x + barW)} ${r1(t + r)}V${base}Z" fill="${fill}"></path>`);
    if (i === values.length - 1)
      out.push(`<text x="${r1(x + barW / 2)}" y="${r1(t - 6)}" text-anchor="middle" font-size="12" font-weight="600" fill="#0E1A13" font-family="Barlow, sans-serif">${v}</text>`);
  });
  for (const [i, text] of labels) {
    const cx = r1(left + i * band + band / 2);
    const anchor = i === 11 ? 'end' : 'middle';
    const lx = i === 11 ? W : cx;
    out.push(`<text x="${lx}" y="156" text-anchor="${anchor}" font-size="11" font-weight="500" fill="#8A958E" font-family="Barlow, sans-serif">${text}</text>`);
  }
  out.push('</svg>');
  return out.join('\n');
}
const labels = [[0, 'Jun 22'], [4, 'Jul 20'], [8, 'Aug 17'], [11, 'This week']];
console.log('=== PROFILE\n' + chart([14.2, 18.0, 9.5, 21.3, 16.8, 0, 12.4, 19.1, 22.6, 17.3, 24.1, 18.4], labels));
console.log('=== FRIEND\n' + chart([8.0, 12.5, 10.1, 0, 15.2, 18.7, 11.0, 20.4, 16.9, 21.8, 19.5, 14.2], labels));
