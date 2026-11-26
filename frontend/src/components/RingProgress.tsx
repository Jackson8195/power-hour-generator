import type { ReactNode } from "react";

type RingProgressProps = {
  /** 0-100 */
  value: number;
  size?: number;
  stroke?: number;
  /** Small line under the percentage. */
  caption?: ReactNode;
};

const SEGMENTS = 40;

/** Circular segmented meter with the percentage in the middle. */
export default function RingProgress({ value, size = 168, stroke = 12, caption }: RingProgressProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const gap = circumference / SEGMENTS;

  return (
    <div
      className="ring-progress"
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <linearGradient id="ring-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#1affe4" />
            <stop offset="55%" stopColor="#7ef8d1" />
            <stop offset="100%" stopColor="#ff77c2" />
          </linearGradient>
        </defs>
        <circle className="ring-progress__track" cx={size / 2} cy={size / 2} r={radius} strokeWidth={stroke} />
        <circle
          className="ring-progress__bar"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped / 100)}
        />
        {/* Thin dark cuts over the ring so it reads as segments. */}
        <circle
          className="ring-progress__ticks"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke + 2}
          strokeDasharray={`2 ${gap - 2}`}
        />
      </svg>
      <div className="ring-progress__value">
        <span style={{ fontSize: size * 0.3, lineHeight: 1 }}>{Math.round(clamped)}%</span>
        {caption ? <span className="mt-1 text-lg tracking-[0.14em] text-phosphor-text/80">{caption}</span> : null}
      </div>
    </div>
  );
}
