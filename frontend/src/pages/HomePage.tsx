import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, FolderOpen, Film } from "lucide-react";
import { createProject } from "../utils/api";
import StudioPage from "../components/StudioPage";
import Spinner from "../components/Spinner";

export default function HomePage() {
  const navigate = useNavigate();
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim() || creating) return;

    setCreating(true);
    setError("");
    try {
      const project = await createProject({ name: newName.trim() });
      navigate(`/project/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the project.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <StudioPage eyebrow="CREATE NEW" title="OPEN A FRESH SESSION">
      <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="retro-panel retro-panel--labeled p-6 pt-8">
          <span className="retro-panel__label">NAME YOUR MIXTAPE</span>
          <div className="relative z-10">
            <form onSubmit={handleCreate} className="flex flex-col gap-4">
              <div>
                <label htmlFor="project-name" className="type-label mb-2 block text-phosphor-text">
                  PROJECT NAME
                </label>
                <input
                  id="project-name"
                  type="text"
                  className="retro-input w-full px-4 py-3 font-mono text-base"
                  placeholder="Friday Night Power Hour"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  autoFocus
                />
              </div>

              {error ? (
                <div className="osd-notice osd-notice--error">
                  <p className="osd-notice__title">COULD NOT CREATE</p>
                  <p className="type-body mt-1 !text-inherit">{error}</p>
                </div>
              ) : null}

              <button
                type="submit"
                disabled={!newName.trim() || creating}
                className="crt-action retro-button-primary inline-flex items-center justify-center gap-3 px-5 py-3 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {creating ? <Spinner className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                <span className="crt-action__label type-label" data-text={creating ? "CREATING..." : "CREATE PROJECT"}>
                  {creating ? "CREATING..." : "CREATE PROJECT"}
                </span>
              </button>
            </form>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <div className="retro-panel retro-panel--labeled p-5 pt-7">
            <span className="retro-panel__label">WORKS IN PROGRESS</span>
            <div className="relative z-10">
              <p className="type-body mb-4">Pick up a project you already started.</p>
              <button
                onClick={() => navigate("/works-in-progress")}
                className="crt-action retro-button-secondary inline-flex items-center gap-3 px-4 py-3"
              >
                <FolderOpen className="h-4 w-4" />
                <span className="crt-action__label type-label" data-text="OPEN WIP LIBRARY">
                  OPEN WIP LIBRARY
                </span>
              </button>
            </div>
          </div>

          <div className="retro-panel retro-panel--labeled p-5 pt-7">
            <span className="retro-panel__label">FINISHED OUTPUTS</span>
            <div className="relative z-10">
              <p className="type-body mb-4">Watch a power hour you already rendered.</p>
              <button
                onClick={() => navigate("/power-hours")}
                className="crt-action retro-button-secondary inline-flex items-center gap-3 px-4 py-3"
              >
                <Film className="h-4 w-4" />
                <span className="crt-action__label type-label" data-text="OPEN TAPE SHELF">
                  OPEN TAPE SHELF
                </span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </StudioPage>
  );
}
