import { Outlet, Link } from "react-router-dom";
import { Beer } from "lucide-react";
import BackButton from "./BackButton";

export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-[#060b10] text-zinc-100">
      {/* Header */}
      <header
        className="sticky top-0 z-50 border-b border-[#1affe4]/14 bg-[#050a0f]/85 backdrop-blur-md"
        style={{ boxShadow: "0 3px 0 rgba(26,255,228,0.04)" }}
      >
        <div className="mx-auto flex h-16 max-w-[1800px] items-center justify-between px-4">
          <BackButton fallback="/" />

          <Link to="/" className="crt-action flex items-center gap-3 text-zinc-100">
            <Beer className="h-5 w-5 text-[#ff77c2]" />
            <span
              className="crt-action__label font-retro text-xl tracking-[0.16em] text-[#ff9bd2]"
              data-text="POWER HOUR STUDIO"
            >
              POWER HOUR STUDIO
            </span>
          </Link>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1">
        <div className="mx-auto max-w-[1800px] px-4 py-6">
          <Outlet />
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-[#1affe4]/10 px-4 py-4">
        <p className="text-center font-retro text-sm tracking-[0.18em] text-[#91fff2]/55">
          POWER HOUR STUDIO V0.1.0 · PERSONAL USE ONLY
        </p>
      </footer>
    </div>
  );
}
