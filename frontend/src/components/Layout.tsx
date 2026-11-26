import { Outlet, useLocation } from "react-router-dom";
import StudioNav, { CrumbProvider } from "./StudioNav";
import MobileTabBar from "./MobileTabBar";

export default function Layout() {
  const location = useLocation();

  return (
    <CrumbProvider>
      {(currentLabel) => (
        <div className="flex min-h-screen flex-col bg-crt-bg text-zinc-100">
          <StudioNav currentLabel={currentLabel} />

          {/* Keyed on the path so every screen change plays the channel-change roll.
              Phones get bottom padding so the tab bar never covers the last control. */}
          <main key={location.pathname} className="channel-change flex flex-1 flex-col max-md:pb-[calc(4.5rem+env(safe-area-inset-bottom))]">
            <Outlet />
          </main>

          <MobileTabBar pathname={location.pathname} />

          <footer className="border-t border-phosphor/10 px-4 py-4 max-md:hidden">
            <p className="text-center font-retro text-lg tracking-[0.16em] text-phosphor-text/60">
              POWER HOUR STUDIO V{__APP_VERSION__} · PERSONAL USE ONLY
            </p>
          </footer>
        </div>
      )}
    </CrumbProvider>
  );
}
