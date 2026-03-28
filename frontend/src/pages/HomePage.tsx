import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, FolderOpen, Sparkles } from "lucide-react";
import { createProject } from "../utils/api";
import CrtStaticText from "../components/CrtStaticText";

export default function HomePage() {
  const navigate = useNavigate();
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim() || creating) return;

    setCreating(true);
    try {
      const project = await createProject({ name: newName.trim() });
      navigate(`/project/${project.id}`);
    } catch (err) {
      console.error("Failed to create project:", err);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="relative min-h-[calc(100vh-7rem)] overflow-hidden rounded-[28px] bg-[#070b10] px-4 py-6 scanlines sm:px-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,43,157,0.12),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(26,255,228,0.08),transparent_30%)]" />

      <section className="retro-shell relative mx-auto max-w-5xl rounded-[28px] px-5 py-6 sm:px-8 sm:py-8">
        <div className="relative z-10 flex flex-col gap-8">
          <div className="flex flex-col gap-5 border-b border-[rgba(26,255,228,0.14)] pb-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <p className="font-retro text-xs tracking-[0.45em] text-[#1affe4]/60">
                CREATE NEW
              </p>
              <CrtStaticText
                as="h1"
                text="OPEN A FRESH SESSION"
                className="mt-2"
                textClassName="font-retro text-4xl tracking-[0.22em] text-[#ff77c2] glow-text sm:text-5xl"
              />
              <p className="mt-4 max-w-xl font-mono text-sm uppercase tracking-[0.22em] text-[#91fff2]/55">
                Start a new project here. Existing edits and finished projects live in separate places now.
              </p>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="retro-panel rounded-[24px] p-6">
              <div className="relative z-10">
                <CrtStaticText
                  as="h2"
                  text="NAME YOUR MIXTAPE"
                  textClassName="font-retro text-2xl tracking-[0.2em] text-[#1affe4]"
                />
                <p className="mt-3 font-mono text-xs uppercase tracking-[0.16em] text-[#91fff2]/45">
                  Create a working project for collecting clips, tweaking ranges, and rendering outputs later.
                </p>

                <form onSubmit={handleCreate} className="mt-6 flex flex-col gap-4">
                  <div>
                    <label className="mb-2 block font-retro text-sm tracking-[0.22em] text-[#91fff2]">
                      PROJECT NAME
                    </label>
                    <input
                      type="text"
                      className="retro-input w-full rounded-xl px-4 py-3 font-mono text-sm tracking-[0.12em]"
                      placeholder="Friday Night Power Hour"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      autoFocus
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={!newName.trim() || creating}
                    className="crt-action retro-button-primary inline-flex items-center justify-center gap-3 rounded-xl px-5 py-3 font-retro text-lg tracking-[0.18em] transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Plus className="h-4 w-4" />
                    <span className="crt-action__label" data-text={creating ? "CREATING..." : "CREATE PROJECT"}>
                      {creating ? "CREATING..." : "CREATE PROJECT"}
                    </span>
                  </button>
                </form>
              </div>
            </div>

            <div className="flex flex-col gap-4">
              <div className="retro-panel rounded-[24px] p-5">
                <div className="relative z-10">
                  <p className="font-retro text-sm tracking-[0.18em] text-zinc-200">WORKS IN PROGRESS</p>
                  <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
                    Open the edit library to keep building any existing project, even after it already has rendered outputs.
                  </p>
                  <button
                    onClick={() => navigate("/works-in-progress")}
                    className="crt-action retro-button-secondary mt-5 inline-flex items-center gap-3 rounded-xl px-4 py-3 font-retro text-sm tracking-[0.16em]"
                  >
                    <FolderOpen className="h-4 w-4" />
                    <span className="crt-action__label" data-text="OPEN WIP LIBRARY">
                      OPEN WIP LIBRARY
                    </span>
                  </button>
                </div>
              </div>

              <div className="retro-panel rounded-[24px] p-5">
                <div className="relative z-10">
                  <p className="font-retro text-sm tracking-[0.18em] text-zinc-200">FINISHED OUTPUTS</p>
                  <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
                    Insert Mixtape is now the playback shelf for finished rendered videos instead of the editing queue.
                  </p>
                  <button
                    onClick={() => navigate("/mixtapes")}
                    className="crt-action retro-button-secondary mt-5 inline-flex items-center gap-3 rounded-xl px-4 py-3 font-retro text-sm tracking-[0.16em]"
                  >
                    <Sparkles className="h-4 w-4" />
                    <span className="crt-action__label" data-text="OPEN MIXTAPE PLAYER">
                      OPEN MIXTAPE PLAYER
                    </span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
