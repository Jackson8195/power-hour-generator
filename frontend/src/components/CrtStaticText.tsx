import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import clsx from "clsx";

type CrtStaticTextProps = {
  text: string;
  className?: string;
  textClassName?: string;
  as?: "h1" | "h2" | "p" | "span";
  style?: CSSProperties;
};

export default function CrtStaticText({
  text,
  className,
  textClassName,
  as = "span",
  style,
}: CrtStaticTextProps) {
  const [sweepActive, setSweepActive] = useState(false);
  const Tag = as;
  const WrapperTag = as === "span" ? "span" : "div";

  useEffect(() => {
    let timeoutId: number | undefined;
    let sweepResetId: number | undefined;
    let cancelled = false;

    const queueNextSweep = () => {
      const delay = 2200 + Math.random() * 4200;

      timeoutId = window.setTimeout(() => {
        if (cancelled) {
          return;
        }

        setSweepActive(true);

        sweepResetId = window.setTimeout(() => {
          if (cancelled) {
            return;
          }

          setSweepActive(false);
          queueNextSweep();
        }, 950);
      }, delay);
    };

    queueNextSweep();

    return () => {
      cancelled = true;

      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }

      if (sweepResetId) {
        window.clearTimeout(sweepResetId);
      }
    };
  }, []);

  return (
    <WrapperTag className={clsx("crt-title", sweepActive && "crt-title--sweeping", className)}>
      <Tag className={clsx("crt-title__text", textClassName)} data-text={text} style={style}>
        {text}
      </Tag>
    </WrapperTag>
  );
}
