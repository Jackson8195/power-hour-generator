import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft, Tv } from "lucide-react";
import clsx from "clsx";
import { crumbsFor, parentPath } from "../utils/nav";

type CrumbContextValue = { setCurrentLabel: (label: string | undefined) => void };

const CrumbContext = createContext<CrumbContextValue>({ setCurrentLabel: () => {} });

/** Pages call this to name themselves in the breadcrumbs (e.g. the project's name). */
export function usePageCrumb(label: string | undefined) {
  const { setCurrentLabel } = useContext(CrumbContext);
  useEffect(() => {
    setCurrentLabel(label);
    return () => setCurrentLabel(undefined);
  }, [label, setCurrentLabel]);
}

export function CrumbProvider({ children }: { children: (label: string | undefined) => ReactNode }) {
  const [label, setLabel] = useState<string | undefined>();
  return (
    <CrumbContext.Provider value={{ setCurrentLabel: setLabel }}>{children(label)}</CrumbContext.Provider>
  );
}

export default function StudioNav({ currentLabel }: { currentLabel?: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const crumbs = crumbsFor(location.pathname, currentLabel);

  function goBack() {
    // "default" means this is the first entry of the app's history (a direct link or a
    // reload): going back would leave the app, so go to the parent screen instead.
    if (location.key === "default") {
      navigate(parentPath(location.pathname));
    } else {
      navigate(-1);
    }
  }

  return (
    <header className="studio-nav">
      <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-2 px-3 sm:gap-4 sm:px-4">
        <Link to="/" className="studio-nav__home shrink-0" aria-label="Home">
          <Tv className="h-5 w-5" />
          <span className="hidden font-retro text-2xl tracking-[0.14em] sm:inline">POWER HOUR STUDIO</span>
          <span className="sr-only sm:hidden">Home</span>
        </Link>

        <nav aria-label="Breadcrumb" className="studio-nav__crumbs flex-1">
          <span aria-hidden className="text-phosphor/40">/</span>
          {crumbs.map((crumb, index) => (
            <span
              key={`${crumb.label}-${index}`}
              className={clsx("min-w-0 items-center gap-2", index < crumbs.length - 1 ? "hidden sm:flex" : "flex")}
            >
              {index > 0 ? <span aria-hidden className="hidden text-phosphor/40 sm:inline">/</span> : null}
              {crumb.to ? (
                <Link to={crumb.to} className="shrink-0 transition-colors">
                  {crumb.label}
                </Link>
              ) : (
                <span className="studio-nav__crumb--current" aria-current="page">
                  {crumb.label}
                </span>
              )}
            </span>
          ))}
        </nav>

        <button onClick={goBack} className="crt-action retro-button-ghost inline-flex shrink-0 items-center gap-1 px-3 py-1.5">
          <ChevronLeft className="h-4 w-4" />
          <span className="crt-action__label type-label" data-text="BACK">
            BACK
          </span>
        </button>
      </div>
    </header>
  );
}
