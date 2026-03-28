import { Outlet, Link } from "react-router-dom";
import { Beer, Home } from "lucide-react";

export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-[#060b10] text-zinc-100">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-[#1affe4]/10 bg-[#050a0f]/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
          <Link to="/" className="crt-action flex items-center gap-3 text-zinc-100">
            <Beer className="h-5 w-5 text-[#ff77c2]" />
            <span
              className="crt-action__label font-retro text-lg tracking-[0.16em] text-[#ff9bd2]"
              data-text="POWER HOUR STUDIO"
            >
              POWER HOUR STUDIO
            </span>
          </Link>

          <nav className="flex items-center gap-1">
            <Link
              to="/"
              className="crt-action flex items-center gap-2 rounded-lg border border-transparent px-3 py-2 font-retro text-sm tracking-[0.16em] text-[#91fff2]/70 transition-colors hover:border-[#1affe4]/20 hover:bg-[#08161f] hover:text-[#defffb]"
            >
              <Home className="h-4 w-4" />
              <span className="crt-action__label" data-text="MENU">
                MENU
              </span>
            </Link>
          </nav>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1">
        <div className="mx-auto max-w-7xl px-4 py-6">
          <Outlet />
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-[#1affe4]/10 px-4 py-4">
        <p className="text-center font-retro text-xs tracking-[0.18em] text-[#91fff2]/35">
          POWER HOUR STUDIO V0.1.0 · PERSONAL USE ONLY
        </p>
      </footer>
    </div>
  );
}
