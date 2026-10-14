import type { Price } from "@/lib/types";
import { fmtDay, fmtNum } from "@/lib/format";

// Plain SVG charts, rendered on the server: nothing to download, nothing to license,
// and they scale with the viewBox.

function scale(d0: number, d1: number, r0: number, r1: number) {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (v: number) => r0 + (v - d0) * k;
}

function niceTicks(lo: number, hi: number, n = 4) {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

export function Sparkline({ values, className = "" }: { values: number[]; className?: string }) {
  if (values.length < 2) return null;
  const w = 160, h = 40;
  const lo = Math.min(...values), hi = Math.max(...values);
  const x = scale(0, values.length - 1, 1, w - 1);
  const y = scale(lo, hi, h - 3, 3);
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} preserveAspectRatio="none" aria-hidden>
      <path d={`${d}L${w - 1},${h}L1,${h}Z`} className={up ? "fill-gain/10" : "fill-loss/10"} />
      <path d={d} fill="none" strokeWidth={1.75} className={up ? "stroke-gain" : "stroke-loss"} />
    </svg>
  );
}

type Marker = { date: string; label: string; price: number; kind: "buy" | "sell" | "signal" | "stop" };

export function CandleChart({
  prices,
  markers = [],
  lines = [],
  band,
}: {
  prices: Price[];
  markers?: Marker[];
  lines?: { price: number; label: string; kind: "stop" | "limit" }[];
  band?: { from: string; to: string; label: string };
}) {
  if (prices.length < 2) return <div className="py-10 text-center text-sm text-ink-3">No price history</div>;
  const W = 680, H = 330, padL = 6, padR = 62, padT = 18, volH = 40, gap = 10, padB = 24;
  const priceH = H - padT - volH - gap - padB;
  const vals = [
    ...prices.flatMap((p) => [p.high, p.low]),
    ...lines.map((l) => l.price),
    ...markers.map((m) => m.price),
  ].filter((v) => Number.isFinite(v) && v > 0);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const padV = (hi - lo) * 0.06 || hi * 0.02;
  lo -= padV;
  hi += padV;
  const n = prices.length;
  const slot = (W - padL - padR) / n;
  const cx = (i: number) => padL + slot * (i + 0.5);
  const y = scale(lo, hi, padT + priceH, padT);
  const vmax = Math.max(...prices.map((p) => p.volume || 0), 1);
  const vy = scale(0, vmax, H - padB, H - padB - volH);
  const idx = new Map(prices.map((p, i) => [p.date.slice(0, 10), i]));
  const at = (d: string) => idx.get(d.slice(0, 10));
  const ticks = niceTicks(lo, hi, 4);
  const bw = Math.max(1.5, Math.min(9, slot * 0.62));
  const dateTicks = [0, Math.floor(n / 3), Math.floor((2 * n) / 3), n - 1];
  const b0 = band ? at(band.from) : undefined, b1 = band ? at(band.to) : undefined;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Daily price chart">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} className="stroke-line" strokeDasharray="2 4" />
          <text x={W - padR + 6} y={y(t) + 4} className="fill-ink-3 text-[12px] num">
            {fmtNum(t, t < 100 ? 2 : 0)}
          </text>
        </g>
      ))}
      {b0 != null && b1 != null && (
        <g>
          <rect
            x={cx(b0) - slot / 2}
            y={padT}
            width={cx(b1) - cx(b0) + slot}
            height={priceH}
            className="fill-brand/8"
          />
          <text x={cx(b0) - slot / 2 + 4} y={padT + 12} className="fill-brand text-[12px] font-medium">
            {band!.label}
          </text>
        </g>
      )}
      {lines.map((l) => (
        <g key={l.label}>
          <line
            x1={padL}
            x2={W - padR}
            y1={y(l.price)}
            y2={y(l.price)}
            strokeWidth={1.25}
            strokeDasharray={l.kind === "stop" ? "6 4" : "2 3"}
            className={l.kind === "stop" ? "stroke-loss" : "stroke-ink-3"}
          />
          <text
            x={W - padR - 4}
            y={y(l.price) - 4}
            textAnchor="end"
            className={`text-[12px] ${l.kind === "stop" ? "fill-loss" : "fill-ink-2"}`}
          >
            {l.label} {fmtNum(l.price, 2)}
          </text>
        </g>
      ))}
      {prices.map((p, i) => {
        const up = p.close >= p.open;
        const top = y(Math.max(p.open, p.close)), bot = y(Math.min(p.open, p.close));
        return (
          <g key={p.date} className={up ? "fill-gain stroke-gain" : "fill-loss stroke-loss"}>
            <title>{`${fmtDay(p.date, "full")}  O ${p.open}  H ${p.high}  L ${p.low}  C ${p.close}`}</title>
            <line x1={cx(i)} x2={cx(i)} y1={y(p.high)} y2={y(p.low)} strokeWidth={1} />
            <rect x={cx(i) - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} />
            <rect
              x={cx(i) - bw / 2}
              y={vy(p.volume || 0)}
              width={bw}
              height={H - padB - vy(p.volume || 0)}
              className="fill-ink-3/30 stroke-none"
            />
          </g>
        );
      })}
      {markers.map((m) => {
        const i = at(m.date);
        if (i == null) return null;
        const yy = y(m.price);
        const cls =
          m.kind === "buy" ? "fill-brand" : m.kind === "sell" ? "fill-info" : m.kind === "stop" ? "fill-loss" : "fill-ink-2";
        const below = m.kind === "buy";
        return (
          <g key={m.label + m.date}>
            <circle cx={cx(i)} cy={yy} r={5.5} className={`${cls} stroke-surface`} strokeWidth={2} />
            <text
              x={cx(i)}
              y={below ? yy + 20 : yy - 11}
              textAnchor="middle"
              className={`${cls} text-[12px] font-semibold`}
            >
              {m.label}
            </text>
          </g>
        );
      })}
      {dateTicks.map((i) => (
        <text key={i} x={cx(i)} y={H - 6} textAnchor="middle" className="fill-ink-3 text-[12px]">
          {fmtDay(prices[i].date, "short").slice(4)}
        </text>
      ))}
    </svg>
  );
}

export function ProfitCurve({ points }: { points: { week: string; cum_profit: number; trades: number }[] }) {
  if (points.length < 2) return null;
  const W = 680, H = 240, padL = 6, padR = 64, padT = 14, padB = 26;
  const vals = points.map((p) => p.cum_profit);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const x = scale(0, points.length - 1, padL, W - padR);
  const y = scale(lo, hi, H - padB, padT);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.cum_profit).toFixed(1)}`).join("");
  const ticks = niceTicks(lo, hi, 4);
  const years: { i: number; y: string }[] = [];
  points.forEach((p, i) => {
    const yr = p.week.slice(0, 4);
    if (!years.length || years[years.length - 1].y !== yr) years.push({ i, y: yr });
  });
  const last = points[points.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Cumulative profit">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} className={t === 0 ? "stroke-ink-3" : "stroke-line"} strokeDasharray={t === 0 ? undefined : "2 4"} />
          <text x={W - padR + 6} y={y(t) + 4} className="fill-ink-3 text-[12px] num">
            {t === 0 ? "0" : `${t > 0 ? "+" : "−"}${fmtNum(Math.abs(t) / 1000, 0)}k`}
          </text>
        </g>
      ))}
      <path d={`${d}L${x(points.length - 1)},${y(0)}L${x(0)},${y(0)}Z`} className="fill-brand/10" />
      <path d={d} fill="none" strokeWidth={2} className="stroke-brand" strokeLinejoin="round" />
      <circle cx={x(points.length - 1)} cy={y(last.cum_profit)} r={4} className="fill-brand" />
      {years.map(({ i, y: yr }) => (
        <text key={yr} x={x(i)} y={H - 6} className="fill-ink-3 text-[12px]">
          {yr}
        </text>
      ))}
    </svg>
  );
}

export function Bars({
  items,
  format,
  height = 150,
}: {
  items: { label: string; value: number; sub?: string }[];
  format: (v: number) => string;
  height?: number;
}) {
  if (!items.length) return null;
  const W = Math.max(320, items.length * 64), H = height, padT = 20, padB = 34;
  const vals = items.map((i) => i.value);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const y = scale(lo, hi || 1, H - padB, padT);
  const slot = W / items.length;
  const bw = Math.min(34, slot * 0.55);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img">
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} className="stroke-line" />
      {items.map((it, i) => {
        const x0 = slot * i + slot / 2;
        const top = y(Math.max(0, it.value)), bot = y(Math.min(0, it.value));
        return (
          <g key={it.label}>
            <title>{`${it.label}: ${format(it.value)}${it.sub ? ` (${it.sub})` : ""}`}</title>
            <rect
              x={x0 - bw / 2}
              y={top}
              width={bw}
              height={Math.max(1, bot - top)}
              rx={3}
              className={it.value >= 0 ? "fill-gain/80" : "fill-loss/80"}
            />
            <text
              x={x0}
              y={it.value >= 0 ? top - 5 : bot + 13}
              textAnchor="middle"
              className="fill-ink-2 text-[12px] num"
            >
              {format(it.value)}
            </text>
            <text x={x0} y={H - 16} textAnchor="middle" className="fill-ink-3 text-[12px]">
              {it.label}
            </text>
            {it.sub && (
              <text x={x0} y={H - 3} textAnchor="middle" className="fill-ink-3 text-[11px]">
                {it.sub}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

