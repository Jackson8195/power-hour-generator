import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const MENU_ITEMS = [
  { label: "INSERT MIXTAPE", to: "/mixtapes" },
  { label: "CREATE NEW", to: "/create" },
  { label: "AUTO GENERATE", to: "/auto-generate" },
] as const;

export default function LandingPage() {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [titleSweepActive, setTitleSweepActive] = useState(false);

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

        setTitleSweepActive(true);

        sweepResetId = window.setTimeout(() => {
          if (cancelled) {
            return;
          }

          setTitleSweepActive(false);
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
    <div className="relative min-h-screen overflow-hidden bg-[#0a0a0a] scanlines">
      {/* CRT flicker overlay */}
      <div className="pointer-events-none fixed inset-0 animate-crt-flicker bg-transparent" />

      <main className="flex min-h-screen flex-col items-center justify-center gap-12 px-6">
        {/* Title block */}
        <div className="text-center">
          <div className={`crt-title ${titleSweepActive ? "crt-title--sweeping" : ""}`}>
            <h1
              className="crt-title__text font-retro tracking-widest glow-text text-6xl sm:text-7xl lg:text-8xl"
              data-text="POWER HOUR STUDIO"
              style={{ color: "#ff2b9d" }}
            >
              POWER HOUR STUDIO
            </h1>
          </div>
        </div>

        {/* DVD-menu navigation panel */}
        <nav
          className="w-full"
          style={{
            maxWidth: "360px",
            border: "1px solid rgba(26, 255, 228, 0.15)",
            background: "rgba(0, 20, 20, 0.6)",
          }}
        >
          {MENU_ITEMS.map((item, i) => (
            <div
              key={item.to}
              className="group relative cursor-pointer"
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              {/* Highlight bar */}
              <div
                className="absolute inset-0 transition-opacity duration-100"
                style={{
                  opacity: hoveredIndex === i ? 1 : 0,
                  background: "rgba(255, 43, 157, 0.15)",
                  borderLeft: "3px solid #ff2b9d",
                }}
              />
              <Link
                to={item.to}
                onFocus={() => setHoveredIndex(i)}
                onBlur={() => setHoveredIndex(null)}
                className="crt-action relative flex items-center gap-4 px-5 py-2.5 font-retro text-xl tracking-wider transition-colors duration-100"
                style={{
                  color: hoveredIndex === i ? "#ff2b9d" : "#1affe4",
                  textShadow:
                    hoveredIndex === i
                      ? "0 0 8px #ff2b9d, 0 0 20px #ff2b9d88"
                      : "none",
                }}
              >
                <span
                  className="w-4 text-right"
                  style={{ opacity: hoveredIndex === i ? 1 : 0 }}
                >
                  ▶
                </span>
                <span className="crt-action__label" data-text={item.label}>
                  {item.label}
                </span>
              </Link>
            </div>
          ))}
        </nav>
      </main>

      <footer className="absolute bottom-0 w-full pb-6 text-center">
        <span
          className="font-retro text-xs tracking-widest"
          style={{ color: "#0d4040" }}
        >
          &#169; POWER HOUR STUDIOS &nbsp;&#183;&nbsp; EST. 2024
        </span>
      </footer>
    </div>
  );
}
