import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Trash2, Music, Clock, Film } from "lucide-react";
import type { Project } from "../utils/types";
import { listProjects, deleteProject } from "../utils/api";
import CrtStaticText from "../components/CrtStaticText";
import StudioPage from "../components/StudioPage";
import { useConfirm } from "../components/ConfirmDialog";

export default function WorksInProgressPage() {
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void loadProjects();
  }, []);

  async function loadProjects() {
    try {
      const data = await listProjects();
      setProjects(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load projects.");
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(project: Project) {
    const ok = await confirm({
      title: "ERASE PROJECT?",
      body: (
        <>
          <span className="text-magenta-text">{project.name}</span> and all {project.clip_count} of its clips,
          downloads and analysis files will be deleted. This can't be undone.
        </>
      ),
      confirmLabel: "ERASE",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await deleteProject(project.id);
      setProjects((prev) => prev.filter((p) => p.id !== project.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the project.");
    }
  }

  return (
    <StudioPage
      eyebrow="WORKS IN PROGRESS"
      title="EDIT LIBRARY"
      actions={
        <button
          onClick={() => navigate("/create")}
          className="crt-action retro-button-primary inline-flex items-center justify-center gap-3 px-5 py-3"
        >
          <Plus className="h-4 w-4" />
          <span className="crt-action__label type-label" data-text="NEW POWER HOUR">
            NEW POWER HOUR
          </span>
        </button>
      }
    >
      <div className="flex items-center justify-between">
        <h2 className="type-display text-3xl text-zinc-200">PROJECT STACK</h2>
        <p className="type-eyebrow">{loading ? "SYNCING..." : `${projects.length} LOADED`}</p>
      </div>

      {error ? (
        <div className="osd-notice osd-notice--error">
          <p className="osd-notice__title">SIGNAL LOST</p>
          <p className="type-body mt-1 !text-inherit">{error}</p>
        </div>
      ) : null}

      {loading ? (
        <div className="retro-panel px-6 py-16 text-center">
          <p className="type-display text-3xl text-phosphor-text/80">LOADING PROJECTS...</p>
          <div className="tracking-loader mx-auto mt-6 max-w-xs" />
        </div>
      ) : projects.length === 0 ? (
        <div className="retro-panel px-6 py-16 text-center">
          <Film className="mx-auto mb-4 h-12 w-12 text-magenta-soft/60" />
          <CrtStaticText
            as="p"
            text="NO ACTIVE PROJECTS"
            textClassName="type-display text-3xl text-magenta-soft"
          />
          <p className="type-body mt-3">Start one from scratch or let the AI build one for you.</p>
          <div className="mt-6 flex justify-center gap-3">
            <button onClick={() => navigate("/create")} className="crt-action retro-button-primary px-4 py-2.5">
              <span className="crt-action__label type-label" data-text="CREATE NEW">CREATE NEW</span>
            </button>
            <button onClick={() => navigate("/auto-generate")} className="crt-action retro-button-secondary px-4 py-2.5">
              <span className="crt-action__label type-label" data-text="AUTO GENERATE">AUTO GENERATE</span>
            </button>
          </div>
        </div>
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <div
              key={project.id}
              role="button"
              tabIndex={0}
              className="retro-project-card retro-panel--labeled crt-action group cursor-pointer p-5 pt-8 text-left transition-all duration-150"
              onClick={() => navigate(`/project/${project.id}`)}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  navigate(`/project/${project.id}`);
                }
              }}
            >
              <span className="retro-panel__label">WORK TAPE</span>
              <div className="relative z-10">
                <div className="flex items-start justify-between gap-4">
                  <h3 className="type-display min-w-0 break-words text-3xl text-magenta-light">
                    <span className="crt-action__label" data-text={project.name}>
                      {project.name}
                    </span>
                  </h3>
                  <button
                    type="button"
                    className="icon-button icon-button--danger shrink-0"
                    aria-label={`Delete ${project.name}`}
                    title="Delete project"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleDelete(project);
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>

                <div className="type-data mt-6 space-y-2 text-sm text-phosphor-text/85">
                  <div className="flex items-center gap-2">
                    <Music className="h-3.5 w-3.5 shrink-0" />
                    <span className="uppercase tracking-[0.1em]">Clips</span>
                    <span className="tracklist-row__leader" />
                    <span className="text-magenta-text">{project.clip_count} / 60</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Clock className="h-3.5 w-3.5 shrink-0" />
                    <span className="uppercase tracking-[0.1em]">Updated</span>
                    <span className="tracklist-row__leader" />
                    <span className="text-magenta-text">{new Date(project.updated_at).toLocaleDateString()}</span>
                  </div>
                </div>

                <div className="mt-6">
                  <div className="type-label mb-2 flex items-center justify-between text-lg text-phosphor-text/80">
                    <span>PROGRESS</span>
                    <span>{Math.round((project.clip_count / 60) * 100)}%</span>
                  </div>
                  <div className="retro-progress h-3">
                    <div
                      className="retro-progress__bar h-full transition-all"
                      style={{ width: `${Math.min(100, (project.clip_count / 60) * 100)}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </StudioPage>
  );
}
