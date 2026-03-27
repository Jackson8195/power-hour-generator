import { Outlet, Link } from "react-router-dom";
import { Beer, Home } from "lucide-react";

export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2.5 font-semibold text-zinc-100">
            <Beer className="h-5 w-5 text-brand-400" />
            <span>Power Hour Studio</span>
          </Link>

          <nav className="flex items-center gap-1">
            <Link
              to="/"
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
            >
              <Home className="h-4 w-4" />
              Projects
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
      <footer className="border-t border-zinc-800 px-4 py-4">
        <p className="text-center text-xs text-zinc-600">
          Power Hour Studio v0.1.0 — Personal use only
        </p>
      </footer>
    </div>
  );
}
