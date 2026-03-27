import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Trash2, Music, Clock } from "lucide-react";
import type { Project } from "../utils/types";
import { listProjects, createProject, deleteProject } from "../utils/api";

export default function HomePage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    loadProjects();
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

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;

    try {
      const project = await createProject({ name: newName.trim() });
      navigate(`/project/${project.id}`);
    } catch (err) {
      console.error("Failed to create project:", err);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this project and all its clips?")) return;
    try {
      await deleteProject(id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      console.error("Failed to delete project:", err);
    }
  }

  return (
    <div>
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Your Power Hours</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Create and manage your Power Hour video playlists
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <Plus className="h-4 w-4" />
          New Power Hour
        </button>
      </div>

      {/* Create dialog */}
      {showCreate && (
        <div className="card mb-6">
          <form onSubmit={handleCreate} className="flex items-end gap-3">
            <div className="flex-1">
              <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                Project Name
              </label>
              <input
                type="text"
                className="input-field"
                placeholder="Friday Night Power Hour"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
              />
            </div>
            <button type="submit" className="btn-primary">
              Create
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setShowCreate(false);
                setNewName("");
              }}
            >
              Cancel
            </button>
          </form>
        </div>
      )}

      {/* Project grid */}
      {loading ? (
        <div className="py-20 text-center text-zinc-500">Loading projects...</div>
      ) : projects.length === 0 ? (
        <div className="py-20 text-center">
          <Music className="mx-auto mb-3 h-12 w-12 text-zinc-700" />
          <p className="text-zinc-500">No projects yet. Create your first Power Hour!</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <div
              key={project.id}
              className="card group cursor-pointer transition-colors hover:border-zinc-700"
              onClick={() => navigate(`/project/${project.id}`)}
            >
              <div className="mb-3 flex items-start justify-between">
                <h3 className="font-semibold text-zinc-100">{project.name}</h3>
                <button
                  className="rounded p-1 text-zinc-600 opacity-0 transition-all hover:bg-zinc-800 hover:text-red-400 group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(project.id);
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>

              <div className="flex items-center gap-4 text-xs text-zinc-500">
                <span className="flex items-center gap-1">
                  <Music className="h-3.5 w-3.5" />
                  {project.clip_count} / 60 clips
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  {new Date(project.updated_at).toLocaleDateString()}
                </span>
              </div>

              {/* Progress bar */}
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-800">
                <div
                  className="h-full rounded-full bg-brand-500 transition-all"
                  style={{ width: `${(project.clip_count / 60) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
