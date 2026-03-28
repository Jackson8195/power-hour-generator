import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Project } from "../utils/types";
import { listProjects } from "../utils/api";
import clsx from "clsx";

const ITEMS_PER_PAGE = 4;

const CD_GRADIENT = [
  "radial-gradient(circle at 30% 25%, rgba(255,255,255,0.65) 0%, rgba(255,255,255,0.05) 28%, transparent 48%)",
  "radial-gradient(circle at 50% 50%, rgba(210,210,225,0.5) 0%, rgba(170,170,190,0.15) 45%, transparent 68%)",
  "conic-gradient(from 200deg, #adadb8, #cfc060, #e085b0, #85a8e0, #85e0b8, #b885e0, #e09085, #adadb8, #cfc060, #adadb8)",
].join(", ");

function splitName(name: string): [string, string | null] {
  if (name.length <= 9) return [name, null];
  const mid = name.lastIndexOf(" ", 9);
  if (mid <= 0) return [name.slice(0, 8) + "…", null];
  return [name.slice(0, mid), name.slice(mid + 1)];
}

export default function MixtapeBinderPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [animatingId, setAnimatingId] = useState<number | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const totalPages = Math.max(1, Math.ceil(projects.length / ITEMS_PER_PAGE));
  const pageItems = projects.slice(page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current);
  }, []);

  function handleDiscClick(id: number) {
    if (animatingId !== null) return;
    setAnimatingId(id);
    timeoutRef.current = setTimeout(() => {
      navigate(`/project/${id}`);
    }, 1200);
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-[#0a0a0a] scanlines">
      {/* CRT flicker overlay */}
      <div className="pointer-events-none fixed inset-0 animate-crt-flicker bg-transparent" />

      {/* Header */}
      <header className="relative z-10 flex items-center gap-6 px-8 pt-8">
        <button
          onClick={() => navigate("/")}
          className="font-retro text-xl tracking-widest text-zinc-500 transition-colors hover:text-zinc-200"
        >
          ◀ BACK
        </button>
        <h1 className="font-retro text-3xl tracking-widest text-zinc-200 sm:text-4xl">
          SELECT YOUR MIXTAPE
        </h1>
      </header>

      {/* Main content */}
      <main className="relative z-10 flex flex-1 items-center justify-center px-4 py-8 sm:px-8 sm:py-12">
        {loading ? (
          <p className="animate-pulse font-retro text-2xl tracking-widest text-zinc-500">
            LOADING...
          </p>
        ) : projects.length === 0 ? (
          <div className="text-center">
            <p className="font-retro text-3xl tracking-widest text-zinc-500">NO MIXTAPES FOUND</p>
            <p className="mt-3 font-retro text-lg tracking-widest text-zinc-700">
              CREATE ONE TO GET STARTED
            </p>
            <button
              onClick={() => navigate("/create")}
              className="mt-8 font-retro text-xl tracking-widest text-brand-400 transition-colors hover:text-brand-300"
            >
              ▶ CREATE NEW
            </button>
          </div>
        ) : (
          /* Binder container */
          <div
            style={{
              position: "relative",
              background: "linear-gradient(135deg, #1c1c2e 0%, #0f0f1a 100%)",
              boxShadow: "inset 0 0 60px rgba(0,0,0,0.6), 0 12px 40px rgba(0,0,0,0.8)",
              border: "1px solid #2a2a3a",
              borderRadius: "10px",
              padding: "20px 16px",
              maxWidth: "480px",
              width: "100%",
            }}
          >
            {/* Binder spine divider */}
            <div
              style={{
                position: "absolute",
                top: "6%",
                bottom: "6%",
                left: "50%",
                width: "2px",
                background:
                  "linear-gradient(to bottom, transparent, #2a2a3a 20%, #3a3a4a 50%, #2a2a3a 80%, transparent)",
                transform: "translateX(-50%)",
              }}
            />

            <div className="grid grid-cols-2 gap-3 sm:gap-4">
              {pageItems.map((project) => (
                <DiscSlot
                  key={project.id}
                  project={project}
                  isAnimating={animatingId === project.id}
                  isDimmed={animatingId !== null && animatingId !== project.id}
                  onClick={() => handleDiscClick(project.id)}
                />
              ))}
              {pageItems.length < ITEMS_PER_PAGE &&
                Array.from({ length: ITEMS_PER_PAGE - pageItems.length }).map((_, i) => (
                  <div key={`empty-${i}`} className="cd-sleeve opacity-0" />
                ))}
            </div>
          </div>
        )}
      </main>

      {/* Pagination footer */}
      {projects.length > 0 && (
        <footer className="relative z-10 flex items-center justify-center gap-8 pb-10">
          <button
            onClick={() => setPage((p) => p - 1)}
            disabled={page === 0}
            className={clsx(
              "font-retro text-2xl tracking-widest transition-colors",
              page === 0 ? "cursor-not-allowed text-zinc-700" : "text-zinc-400 hover:text-zinc-200"
            )}
          >
            ◀ PREV
          </button>
          <span className="font-retro text-xl tracking-widest text-zinc-500">
            DISC {page + 1} OF {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= totalPages - 1}
            className={clsx(
              "font-retro text-2xl tracking-widest transition-colors",
              page >= totalPages - 1
                ? "cursor-not-allowed text-zinc-700"
                : "text-zinc-400 hover:text-zinc-200"
            )}
          >
            NEXT ▶
          </button>
        </footer>
      )}

      {/* Loading overlay */}
      {animatingId !== null && (
        <div className="fixed inset-0 z-40 flex flex-col items-center justify-center bg-black/75">
          <div
            className="animate-disc-spin rounded-full"
            style={{
              width: 88,
              height: 88,
              background: CD_GRADIENT,
              boxShadow: "0 0 30px rgba(200,200,255,0.4), 0 0 60px rgba(160,160,220,0.2)",
            }}
          >
            {/* spindle hole */}
            <div
              style={{
                position: "absolute",
                width: "14%",
                height: "14%",
                top: "43%",
                left: "43%",
                borderRadius: "50%",
                background: "#07070e",
              }}
            />
          </div>
          <p className="mt-6 animate-pulse font-retro text-2xl tracking-widest text-zinc-300">
            LOADING DISC...
          </p>
        </div>
      )}
    </div>
  );
}

function DiscSlot({
  project,
  isAnimating,
  isDimmed,
  onClick,
}: {
  project: Project;
  isAnimating: boolean;
  isDimmed: boolean;
  onClick: () => void;
}) {
  const [line1, line2] = splitName(project.name);

  return (
    <button
      onClick={onClick}
      className={clsx(
        "group flex flex-col items-center gap-1.5 transition-all duration-200",
        isDimmed && "pointer-events-none opacity-20",
        isAnimating && "animate-disc-drop"
      )}
    >
      {/* Sleeve pocket */}
      <div className="cd-sleeve w-full">
        {/* Disc */}
        <div
          className="relative w-full rounded-full transition-all duration-200 group-hover:brightness-110"
          style={{
            aspectRatio: "1 / 1",
            background: CD_GRADIENT,
            boxShadow: "0 2px 12px rgba(0,0,0,0.5), inset 0 0 0 1px rgba(255,255,255,0.15)",
          }}
        >
          {/* Top outer-ring text */}
          <div
            style={{
              position: "absolute",
              top: "7%",
              left: "12%",
              right: "12%",
              textAlign: "center",
            }}
          >
            <span
              className="font-marker text-[#111]"
              style={{
                fontSize: "clamp(0.42rem, 2vw, 0.65rem)",
                transform: "rotate(-3deg)",
                display: "block",
                lineHeight: 1.1,
              }}
            >
              {line1}
            </span>
          </div>

          {/* Hub ring — visual only */}
          <div
            style={{
              position: "absolute",
              inset: "28%",
              borderRadius: "50%",
              background: "rgba(0,0,0,0.22)",
              border: "1px solid rgba(255,255,255,0.1)",
            }}
          />

          {/* Spindle hole */}
          <div
            style={{
              position: "absolute",
              width: "7%",
              height: "7%",
              top: "46.5%",
              left: "46.5%",
              borderRadius: "50%",
              background: "#07070e",
            }}
          />

          {/* Bottom outer-ring text (overflow) */}
          {line2 && (
            <div
              style={{
                position: "absolute",
                bottom: "7%",
                left: "12%",
                right: "12%",
                textAlign: "center",
              }}
            >
              <span
                className="font-marker text-[#111]"
                style={{
                  fontSize: "clamp(0.42rem, 2vw, 0.65rem)",
                  transform: "rotate(3deg)",
                  display: "block",
                  lineHeight: 1.1,
                }}
              >
                {line2}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Clip count below sleeve */}
      <p className="font-retro text-xs tracking-widest text-zinc-600">
        {project.clip_count} CLIPS
      </p>
    </button>
  );
}
