import { useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";

const MENU_ITEMS = [
  { label: "INSERT MIXTAPE", to: "/mixtapes" },
  { label: "CREATE NEW", to: "/create" },
  { label: "AUTO GENERATE", to: "/auto-generate" },
] as const;

export default function LandingPage() {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#0a0a0a] scanlines">
      {/* CRT flicker overlay — own layer so children aren't repainted */}
      <div className="pointer-events-none fixed inset-0 animate-crt-flicker bg-transparent" />

      <main className="flex min-h-screen flex-col items-center justify-center gap-16 px-6">
        {/* Title block */}
        <div className="text-center">
          <h1 className="font-retro text-6xl tracking-widest text-white sm:text-7xl lg:text-8xl">
            POWER HOUR STUDIO
          </h1>
          <p className="mt-3 font-retro text-lg tracking-widest text-zinc-500 sm:text-xl">
            60 TRACKS &nbsp;·&nbsp; 60 MINUTES &nbsp;·&nbsp; 1 LEGENDARY NIGHT
          </p>
        </div>

        {/* DVD-menu navigation */}
        <nav className="flex flex-col items-start gap-2">
          {MENU_ITEMS.map((item, i) => (
            <Link
              key={item.to}
              to={item.to}
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
              onFocus={() => setHoveredIndex(i)}
              onBlur={() => setHoveredIndex(null)}
              className={clsx(
                "flex items-center gap-3 font-retro text-3xl tracking-widest transition-all duration-150 sm:text-4xl",
                hoveredIndex === i
                  ? "text-brand-400 glow-text"
                  : "text-zinc-400 hover:text-brand-400"
              )}
            >
              {/* Fixed-width arrow column — reserves space to prevent layout shift */}
              <span className="inline-block w-7 text-right">
                {hoveredIndex === i ? (
                  <span className="inline-block animate-menu-slide">▶</span>
                ) : (
                  <span className="opacity-0">▶</span>
                )}
              </span>
              {item.label}
            </Link>
          ))}
        </nav>
      </main>

      <footer className="absolute bottom-0 w-full pb-6 text-center">
        <span className="font-retro text-xs tracking-widest text-zinc-700">
          © POWER HOUR STUDIOS &nbsp;·&nbsp; EST. 2024
        </span>
      </footer>
    </div>
  );
}
