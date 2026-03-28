import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Project } from "../utils/types";
import { listProjects } from "../utils/api";
import clsx from "clsx";

const ITEMS_PER_PAGE = 4;

const DISC_COLORS = [
  "#c0392b", // red
  "#d35400", // orange
  "#f39c12", // amber
  "#27ae60", // green
  "#2980b9", // blue
  "#8e44ad", // purple
  "#e91e8c", // pink
  "#1a5276", // navy
];

function discColor(id: number): string {
  return DISC_COLORS[id % DISC_COLORS.length];
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
      <main className="relative z-10 flex flex-1 items-center justify-center px-8 py-12">
        {loading ? (
          <p className="font-retro text-2xl tracking-widest text-zinc-500 animate-pulse">
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
              className="mt-8 font-retro text-xl tracking-widest text-brand-400 transition-colors hover:glow-text hover:text-brand-300"
            >
              ▶ CREATE NEW
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-10 sm:gap-14" style={{ maxWidth: "520px", width: "100%" }}>
            {pageItems.map((project) => (
              <DiscSlot
                key={project.id}
                project={project}
                isAnimating={animatingId === project.id}
                isDimmed={animatingId !== null && animatingId !== project.id}
                onClick={() => handleDiscClick(project.id)}
              />
            ))}
            {/* Fill empty slots so grid stays stable */}
            {pageItems.length < ITEMS_PER_PAGE &&
              Array.from({ length: ITEMS_PER_PAGE - pageItems.length }).map((_, i) => (
                <div key={`empty-${i}`} className="aspect-square opacity-0" />
              ))}
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
              page === 0
                ? "cursor-not-allowed text-zinc-700"
                : "text-zinc-400 hover:text-zinc-200"
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

      {/* Loading overlay during disc-drop animation */}
      {animatingId !== null && (
        <div className="fixed inset-0 z-40 flex flex-col items-center justify-center bg-black/70">
          <div
            className="animate-disc-spin rounded-full"
            style={{
              width: 80,
              height: 80,
              backgroundColor: discColor(animatingId),
              boxShadow: `0 0 30px ${discColor(animatingId)}`,
            }}
          >
            <div
              className="absolute inset-0 m-auto rounded-full bg-[#0a0a0a]"
              style={{ width: "20%", height: "20%", top: "40%", left: "40%" }}
            />
          </div>
          <p className="mt-6 font-retro text-2xl tracking-widest text-zinc-300 animate-pulse">
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
  const color = discColor(project.id);

  return (
    <button
      onClick={onClick}
      className={clsx(
        "group flex flex-col items-center gap-3 transition-all duration-200",
        isDimmed && "pointer-events-none opacity-25",
        isAnimating && "animate-disc-drop"
      )}
    >
      {/* Disc circle */}
      <div
        className="relative w-full rounded-full"
        style={{
          aspectRatio: "1 / 1",
          backgroundColor: color,
          boxShadow: `inset 0 0 24px rgba(0,0,0,0.55), 0 0 18px ${color}55`,
          transition: "box-shadow 0.2s",
        }}
      >
        {/* Sheen ring */}
        <div
          className="absolute inset-[8%] rounded-full opacity-20"
          style={{
            background: "radial-gradient(circle at 35% 35%, white 0%, transparent 70%)",
          }}
        />
        {/* Disc label area */}
        <div
          className="absolute inset-[22%] flex items-center justify-center rounded-full"
          style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
        >
          <span
            className="max-w-[80%] overflow-hidden text-ellipsis whitespace-nowrap font-retro text-xs tracking-wide text-white/80"
            style={{ fontSize: "clamp(0.55rem, 2vw, 0.8rem)" }}
          >
            {project.name.toUpperCase()}
          </span>
        </div>
        {/* Center hole */}
        <div
          className="absolute rounded-full bg-[#0a0a0a]"
          style={{
            width: "14%",
            height: "14%",
            top: "43%",
            left: "43%",
          }}
        />
        {/* Hover glow */}
        <div
          className="absolute inset-0 rounded-full opacity-0 transition-opacity duration-200 group-hover:opacity-100"
          style={{ boxShadow: `0 0 32px ${color}` }}
        />
      </div>

      {/* Label below disc */}
      <div className="text-center">
        <p
          className="max-w-[10rem] overflow-hidden text-ellipsis whitespace-nowrap font-retro tracking-widest text-zinc-400 transition-colors group-hover:text-zinc-100"
          style={{ fontSize: "clamp(0.75rem, 2.5vw, 1rem)" }}
        >
          {project.name.toUpperCase()}
        </p>
        <p className="font-retro text-xs tracking-widest text-zinc-600">
          {project.clip_count} CLIPS
        </p>
      </div>
    </button>
  );
}
