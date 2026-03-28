import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Trash2, Music, Clock, Film } from "lucide-react";
import type { Project } from "../utils/types";
import { listProjects, deleteProject } from "../utils/api";
import CrtStaticText from "../components/CrtStaticText";

export default function WorksInProgressPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void loadProjects();
  }, []);

  async function loadProjects() {
    try {
      const data = await listProjects();
      setProjects(data);
    } catch (err) {
      console.error("Failed to load projects:", err);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this project and all its clips?")) return;
    try {
      await deleteProject(id);
      setProjects((prev) => prev.filter((project) => project.id !== id));
    } catch (err) {
      console.error("Failed to delete project:", err);
    }
  }

  return (
    <div className="relative min-h-[calc(100vh-7rem)] overflow-hidden rounded-[28px] bg-[#070b10] px-4 py-6 scanlines sm:px-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,43,157,0.12),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(26,255,228,0.08),transparent_30%)]" />

      <section className="retro-shell relative mx-auto max-w-6xl rounded-[28px] px-5 py-6 sm:px-8 sm:py-8">
        <div className="relative z-10 flex flex-col gap-6">
          <div className="flex flex-col gap-5 border-b border-[rgba(26,255,228,0.14)] pb-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <p className="font-retro text-xs tracking-[0.45em] text-[#1affe4]/60">
                WORKS IN PROGRESS
              </p>
              <CrtStaticText
                as="h1"
                text="EDIT LIBRARY"
                className="mt-2"
                textClassName="font-retro text-4xl tracking-[0.22em] text-[#ff77c2] glow-text sm:text-5xl"
              />
            </div>

            <button
              onClick={() => navigate("/create")}
              className="crt-action retro-button-primary inline-flex items-center justify-center gap-3 rounded-xl px-5 py-3 font-retro text-lg tracking-[0.18em] transition-all duration-150"
            >
              <Plus className="h-4 w-4" />
              <span className="crt-action__label" data-text="NEW POWER HOUR">
                NEW POWER HOUR
              </span>
            </button>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <CrtStaticText
                as="h2"
                text="PROJECT STACK"
                textClassName="font-retro text-2xl tracking-[0.2em] text-zinc-200"
              />
            </div>
            <p className="font-retro text-xs tracking-[0.32em] text-[#1affe4]/60">
              {loading ? "SYNCING..." : `${projects.length} LOADED`}
            </p>
          </div>

          {loading ? (
            <div className="retro-panel rounded-[22px] px-6 py-16 text-center">
              <p className="animate-pulse font-retro text-2xl tracking-[0.22em] text-[#91fff2]/70">
                LOADING PROJECTS...
              </p>
            </div>
          ) : projects.length === 0 ? (
            <div className="retro-panel rounded-[22px] px-6 py-16 text-center">
              <Film className="mx-auto mb-4 h-12 w-12 text-[#ff77c2]/45" />
              <CrtStaticText
                as="p"
                text="NO ACTIVE PROJECTS"
                textClassName="font-retro text-3xl tracking-[0.2em] text-[#ff77c2]/85"
              />
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {projects.map((project) => (
                <div
                  key={project.id}
                  role="button"
                  tabIndex={0}
                  className="retro-project-card crt-action group rounded-[22px] p-5 text-left transition-all duration-150"
                  onClick={() => navigate(`/project/${project.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      navigate(`/project/${project.id}`);
                    }
                  }}
                >
                  <div className="relative z-10">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="font-retro text-[0.65rem] tracking-[0.32em] text-[#1affe4]/60">
                          WORK TAPE
                        </p>
                        <h3 className="mt-3 font-retro text-2xl tracking-[0.14em] text-[#ff9bd2]">
                          <span className="crt-action__label" data-text={project.name}>
                            {project.name}
                          </span>
                        </h3>
                      </div>
                      <button
                        type="button"
                        className="rounded-lg border border-transparent p-2 text-zinc-600 opacity-0 transition-all hover:border-red-400/30 hover:bg-red-500/10 hover:text-red-300 group-hover:opacity-100"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(project.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    <div className="mt-6 flex flex-wrap gap-3 text-[0.7rem] uppercase tracking-[0.18em] text-[#91fff2]/60">
                      <span className="inline-flex items-center gap-2 rounded-full border border-[#1affe4]/10 bg-[#06141c]/80 px-3 py-1.5">
                        <Music className="h-3.5 w-3.5" />
                        {project.clip_count} / 60 clips
                      </span>
                      <span className="inline-flex items-center gap-2 rounded-full border border-[#ff2b9d]/10 bg-[#190811]/80 px-3 py-1.5 text-[#ffb6dd]/65">
                        <Clock className="h-3.5 w-3.5" />
                        {new Date(project.updated_at).toLocaleDateString()}
                      </span>
                    </div>

                    <div className="mt-6">
                      <div className="mb-2 flex items-center justify-between font-retro text-[0.65rem] tracking-[0.28em] text-[#91fff2]/55">
                        <span>PROGRESS</span>
                        <span>{project.clip_count}/60</span>
                      </div>
                      <div className="retro-progress h-2 overflow-hidden rounded-full">
                        <div
                          className="retro-progress__bar h-full rounded-full transition-all"
                          style={{ width: `${(project.clip_count / 60) * 100}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
