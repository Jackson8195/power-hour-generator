import { type ReactNode, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Loader2, Film, Disc3, Music4, CheckCircle2, AlertTriangle } from "lucide-react";
import CrtStaticText from "../components/CrtStaticText";
import BackButton from "../components/BackButton";
import { getAutoGenerateJob } from "../utils/api";
import type { AutoGenerateJobProgress } from "../utils/types";

export default function AutoGenerateProgressPage() {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<AutoGenerateJobProgress | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;

    async function load() {
      try {
        const nextJob = await getAutoGenerateJob(jobId);
        if (cancelled) return;
        setJob(nextJob);
        setError("");

        if (nextJob.phase === "complete" || nextJob.phase === "error") {
          window.localStorage.removeItem("power-hour-active-ai-job");
        } else {
          window.localStorage.setItem(
            "power-hour-active-ai-job",
            JSON.stringify({ jobId: nextJob.job_id, projectId: nextJob.project_id })
          );
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load generation progress");
      }
    }

    void load();
    const interval = window.setInterval(load, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [jobId]);

  const phaseCopy = getPhaseCopy(job);
  const currentSong = [job?.current_artist, job?.current_title].filter(Boolean).join(" - ");

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#070b10] scanlines">
      <div className="pointer-events-none fixed inset-0 animate-crt-flicker bg-transparent" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,43,157,0.12),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(26,255,228,0.08),transparent_30%)]" />

      <main className="relative z-10 mx-auto flex min-h-screen w-full max-w-[1800px] flex-col px-4 py-8 sm:px-6">
        <div className="retro-shell flex flex-1 flex-col px-5 py-6 sm:px-8 sm:py-8">
          <div className="relative z-10 flex h-full flex-col">
            <div className="flex flex-col gap-4 border-b border-[rgba(26,255,228,0.14)] pb-6 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-3xl">
                <p className="font-retro text-sm tracking-[0.45em] text-[#1affe4]/70">
                  AI AUTO GENERATE
                </p>
                <CrtStaticText
                  as="h1"
                  text="BUILDING YOUR POWER HOUR"
                  className="mt-2"
                  textClassName="font-retro text-4xl tracking-[0.18em] text-[#ff77c2] glow-text sm:text-5xl"
                />
                <p className="mt-4 font-mono text-base text-[#91fff2]/70">
                  Estimated time 12 minutes. So this should take about 5 or 10 minutes.
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <BackButton fallback="/auto-generate" />
                {job?.project_id ? (
                  <Link
                    to={`/project/${job.project_id}`}
                    className="crt-action retro-button-secondary inline-flex items-center gap-3 px-4 py-3 font-retro text-base tracking-[0.16em]"
                  >
                    <span className="crt-action__label" data-text="OPEN PROJECT">
                      OPEN PROJECT
                    </span>
                  </Link>
                ) : null}
              </div>
            </div>

            <div className="mt-6 flex flex-1 flex-col gap-6">
              <section className="retro-panel retro-panel--labeled p-6 pt-8">
                <span className="retro-panel__label">TRANSMISSION STATUS</span>
                <div className="relative z-10">
                  <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                    <div>
                      <p className="font-retro text-xl tracking-[0.18em] text-[#1affe4]">
                        {phaseCopy.title}
                      </p>
                      <p className="mt-2 font-mono text-sm text-[#91fff2]/70">
                        {phaseCopy.description}
                      </p>
                    </div>
                    <div className="retro-chip retro-chip--info text-xl">
                      {Math.round(job?.progress ?? 0)}%
                    </div>
                  </div>

                  <div className="mt-6 h-5 border border-[#1affe4]/18 bg-[#08131a]">
                    <div
                      className="h-full bg-[linear-gradient(90deg,#1affe4_0%,#7ef8d1_35%,#ff77c2_100%)] shadow-[0_0_24px_rgba(26,255,228,0.28)] transition-all duration-700"
                      style={{ width: `${Math.max(4, Math.min(100, job?.progress ?? 4))}%` }}
                    />
                  </div>

                  {job?.phase === "rendering" ? (
                    <div className="mt-4">
                      <span
                        className={[
                          "gpu-active-indicator",
                          !job.gpu_active && "gpu-active-indicator--cpu",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        title={
                          job.gpu_active
                            ? "Encoding on the GPU (NVENC)"
                            : "Encoding on the CPU (libx264)"
                        }
                      >
                        <span className="gpu-active-indicator__light" />
                        {job.gpu_active ? "GPU ENCODING ACTIVE" : "CPU ENCODING ACTIVE"}
                      </span>
                    </div>
                  ) : null}

                  <div className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
                    <div className="relative border border-[#1affe4]/10 bg-[#08131a]/90 p-5 pt-6">
                      <span className="retro-panel__label">CURRENT TASK</span>
                      <p className="font-retro text-2xl tracking-[0.14em] text-[#ffb6dd]">
                        {job?.current_step || "Spinning up the tape deck"}
                      </p>
                      <p className="mt-3 font-mono text-sm text-[#91fff2]/70">
                        {currentSong || "Loading the queue..."}
                      </p>
                    </div>

                    <div className="relative border border-[#ff77c2]/12 bg-[#140913]/90 p-5 pt-6">
                      <span className="retro-panel__label retro-panel__label--pink">JOB SNAPSHOT</span>
                      <div className="space-y-3 font-mono text-sm text-[#91fff2]/70">
                        <p>{job ? `${job.processed_clips} of ${job.total_clips} clips processed` : "Waiting for clip queue"}</p>
                        <p>{job?.render_id ? `Render job #${job.render_id} active` : "Render starts automatically after clipping"}</p>
                        <p>Background safe: you can leave this page and come back later.</p>
                      </div>
                    </div>
                  </div>

                  {job?.phase === "complete" ? (
                    <div className="mt-6 border border-green-400/20 bg-green-500/10 p-5">
                      <div className="flex items-center gap-3 font-retro text-lg tracking-[0.16em] text-green-300">
                        <CheckCircle2 className="h-5 w-5" />
                        FINAL RENDER COMPLETE
                      </div>
                      <p className="mt-3 font-mono text-sm text-green-100/80">
                        Your auto-generated power hour is ready.
                      </p>
                    </div>
                  ) : null}

                  {job?.phase === "error" ? (
                    <div className="mt-6 border border-red-400/20 bg-red-500/10 p-5">
                      <div className="flex items-center gap-3 font-retro text-lg tracking-[0.16em] text-red-200">
                        <AlertTriangle className="h-5 w-5" />
                        SOMETHING HIT STATIC
                      </div>
                      <p className="mt-3 font-mono text-sm text-red-100/85">
                        {job.error_message || "The AI generation run hit an error."}
                      </p>
                    </div>
                  ) : null}

                  {!job && !error ? (
                    <div className="mt-6 flex items-center gap-3 font-retro text-base tracking-[0.16em] text-[#91fff2]/70">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      WAITING FOR JOB STATUS...
                    </div>
                  ) : null}

                  {error ? (
                    <div className="mt-6 border border-red-400/20 bg-red-500/10 p-5">
                      <p className="font-retro text-lg tracking-[0.16em] text-red-200">
                        COULD NOT LOAD PROGRESS
                      </p>
                      <p className="mt-3 font-mono text-sm text-red-100/85">
                        {error}
                      </p>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="grid gap-4 md:grid-cols-3">
                <ProgressTile
                  icon={<Music4 className="h-5 w-5" />}
                  label="DOWNLOAD"
                  active={job?.phase === "processing" && job.current_step.toLowerCase().includes("download")}
                  complete={Boolean(job && job.processed_clips > 0)}
                  body="Pulling source videos one by one to keep disk use under control."
                />
                <ProgressTile
                  icon={<Disc3 className="h-5 w-5" />}
                  label="WAVEFORM + CLIP"
                  active={job?.phase === "processing" && !job.current_step.toLowerCase().includes("download")}
                  complete={Boolean(job && (job.phase === "rendering" || job.phase === "complete"))}
                  body="Analyzing energy and carving out the recommended 60-second section."
                />
                <ProgressTile
                  icon={<Film className="h-5 w-5" />}
                  label="FINAL RENDER"
                  active={job?.phase === "rendering"}
                  complete={job?.phase === "complete"}
                  body="Stitching the trimmed clips into the finished power hour video automatically."
                />
              </section>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function ProgressTile({
  icon,
  label,
  active,
  complete,
  body,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  complete?: boolean;
  body: string;
}) {
  return (
    <div className="retro-panel retro-panel--labeled p-5 pt-6">
      <span className="retro-panel__label">{label}</span>
      <div className="relative z-10">
        <div className="flex items-center gap-3">
          <div className="text-[#ff77c2]">{icon}</div>
          <span
            className={[
              "retro-chip ml-auto",
              complete
                ? "retro-chip--ok"
                : active
                  ? "retro-chip--info"
                  : "retro-chip--dim",
            ].join(" ")}
          >
            {complete ? "DONE" : active ? "LIVE" : "STANDBY"}
          </span>
        </div>
        <p className="mt-3 font-mono text-sm text-[#91fff2]/70">
          {body}
        </p>
      </div>
    </div>
  );
}

function getPhaseCopy(job: AutoGenerateJobProgress | null): { title: string; description: string } {
  if (!job) {
    return {
      title: "CONNECTING TO THE TAPE DECK",
      description: "Checking in on the background AI generation run.",
    };
  }

  if (job.phase === "processing") {
    return {
      title: "PREPPING CLIPS FOR THE FINAL MIX",
      description: "The app is downloading each source, building waveform guidance, and trimming the recommended section.",
    };
  }

  if (job.phase === "rendering") {
    return {
      title: "RENDERING THE FINAL POWER HOUR",
      description: "All approved clips are trimmed, and the final video is now being assembled automatically.",
    };
  }

  if (job.phase === "complete") {
    return {
      title: "POWER HOUR READY",
      description: "The full AI-generated power hour has been rendered successfully.",
    };
  }

  if (job.phase === "error") {
    return {
      title: "SIGNAL INTERRUPTION",
      description: "The run hit an error before the final output could finish.",
    };
  }

  return {
    title: "QUEUING THE MIX",
    description: "Your project has been approved and is being staged for processing.",
  };
}
