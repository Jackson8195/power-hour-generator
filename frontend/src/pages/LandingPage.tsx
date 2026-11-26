import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import clsx from "clsx";
import CrtStaticText from "../components/CrtStaticText";

const MENU_ITEMS = [
  { label: "POWER HOURS", to: "/power-hours" },
  { label: "WORKS IN PROGRESS", to: "/works-in-progress" },
  { label: "CREATE NEW", to: "/create" },
  { label: "AUTO GENERATE", to: "/auto-generate" },
] as const;

const POWERED_ON_KEY = "power-hour-crt-on";
const ITEM_HEIGHT = 52; // px; keeps the sliding cursor aligned with the rows

export default function LandingPage() {
  const navigate = useNavigate();
  const [activeIndex, setActiveIndex] = useState(0);
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  // The power-on plays once per browser session, not on every return to the menu.
  const [powerOn] = useState(() => {
    const first = !window.sessionStorage.getItem(POWERED_ON_KEY);
    window.sessionStorage.setItem(POWERED_ON_KEY, "1");
    return first;
  });

  // DVD-menu keys: arrows move the cursor, Enter picks, number keys jump.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((current) => {
          const next = (current + (event.key === "ArrowDown" ? 1 : -1) + MENU_ITEMS.length) % MENU_ITEMS.length;
          linkRefs.current[next]?.focus();
          return next;
        });
      } else if (/^[1-4]$/.test(event.key)) {
        navigate(MENU_ITEMS[Number(event.key) - 1].to);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <div className="relative min-h-screen overflow-hidden bg-crt-bg scanlines">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(255,43,157,0.09),transparent_55%)]" />

      <div className={clsx("relative", powerOn && "crt-power-on")}>
        <main className="flex min-h-screen flex-col items-center justify-center gap-10 px-4 pb-16 pt-[env(safe-area-inset-top)] sm:gap-12 sm:px-6">
          <div className="text-center">
            <CrtStaticText
              as="h1"
              text="POWER HOUR STUDIO"
              textClassName="type-display glow-text text-5xl text-magenta sm:text-7xl lg:text-8xl"
            />
          </div>

          {/* DVD-menu navigation panel */}
          <nav
            aria-label="Main menu"
            className="relative w-full max-w-[380px] border border-phosphor/20 bg-[rgba(0,20,20,0.6)] py-1"
          >
            <div
              className="menu-cursor"
              style={{ height: ITEM_HEIGHT, transform: `translateY(${activeIndex * ITEM_HEIGHT + 4}px)` }}
            />
            {MENU_ITEMS.map((item, i) => {
              const active = activeIndex === i;
              return (
                <Link
                  key={item.to}
                  ref={(node) => {
                    linkRefs.current[i] = node;
                  }}
                  to={item.to}
                  onMouseEnter={() => setActiveIndex(i)}
                  onFocus={() => setActiveIndex(i)}
                  className="crt-action relative flex items-center gap-4 px-5 font-retro text-2xl tracking-[0.12em] transition-colors duration-100 focus-visible:!outline-none"
                  style={{
                    height: ITEM_HEIGHT,
                    color: active ? "#ff77c2" : "#1affe4",
                    textShadow: active ? "0 0 8px #ff2b9d, 0 0 18px rgba(255,43,157,0.5)" : "none",
                  }}
                >
                  <span className="w-4 text-right" style={{ opacity: active ? 1 : 0 }}>
                    ▶
                  </span>
                  <span className="crt-action__label" data-text={item.label}>
                    {item.label}
                  </span>
                  <span className="ml-auto text-lg text-phosphor-text/50">{i + 1}</span>
                </Link>
              );
            })}
          </nav>

          <p className="font-retro text-lg tracking-[0.16em] text-phosphor-text/60 [@media(pointer:coarse)]:hidden">
            ▲▼ SELECT · ENTER PLAY · 1–4 JUMP
          </p>
        </main>

        <footer className="absolute bottom-0 w-full pb-6 text-center">
          <span className="font-retro text-lg tracking-[0.16em] text-phosphor-text/50">
            &#169; POWER HOUR STUDIOS &nbsp;&#183;&nbsp; EST. 2024
          </span>
        </footer>
      </div>
    </div>
  );
}
