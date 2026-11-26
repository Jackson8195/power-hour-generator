import { NavLink } from "react-router-dom";
import clsx from "clsx";
import { FolderOpen, Plus, Sparkles, Tv } from "lucide-react";

const TABS = [
  { to: "/power-hours", label: "TAPES", icon: Tv },
  { to: "/works-in-progress", label: "WORK", icon: FolderOpen, also: ["/project/"] },
  { to: "/create", label: "NEW", icon: Plus },
  { to: "/auto-generate", label: "AI", icon: Sparkles },
] as const;

/** Phone-only bottom bar: the four main sections within thumb reach. Hidden from md up,
 *  where the top nav bar and the landing menu do this job. */
export default function MobileTabBar({ pathname }: { pathname: string }) {
  return (
    <nav aria-label="Sections" className="mobile-tabbar md:hidden">
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const alsoActive = "also" in tab && tab.also.some((prefix) => pathname.startsWith(prefix));
        return (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) => clsx("mobile-tabbar__tab", (isActive || alsoActive) && "mobile-tabbar__tab--active")}
          >
            <Icon className="h-5 w-5" aria-hidden />
            <span>{tab.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
