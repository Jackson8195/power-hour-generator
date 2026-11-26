import { type ReactNode, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import clsx from "clsx";
import { Film, Scissors, Music4, CheckCircle2, AlertTriangle, FolderOpen, Tv } from "lucide-react";
import StudioPage from "../components/StudioPage";
import RingProgress from "../components/RingProgress";
import { ACTIVE_AI_JOB_KEY, getAutoGenerateJob, isNotFound } from "../utils/api";
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

        if (nextJob.phase === "complete" || nextJob.phase === "error" || nextJob.phase === "review") {
          window.localStorage.removeItem(ACTIVE_AI_JOB_KEY);
        } else {
          window.localStorage.setItem(
            ACTIVE_AI_JOB_KEY,
            JSON.stringify({ jobId: nextJob.job_id, projectId: nextJob.project_id })
          );
        }
      } catch (err) {
        if (cancelled) return;
        if (isNotFound(err)) {
          // The backend no longer knows this job (it restarted, or the job expired). Polling
          // again can't bring it back, so forget it and say so plainly.
          window.localStorage.removeItem(ACTIVE_AI_JOB_KEY);
          window.clearInterval(interval);
          setError(
            "This generation job no longer exists: the backend restarted or the job expired. " +
              "Clips that finished are still in the project; start a new generation to build the rest."
          );
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load generation progress");
      }
    }

    const interval = window.setInterval(load, 2000);
    void load();

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [jobId]);

  const phaseCopy = getPhaseCopy(job);
  const currentSong = [job?.current_artist, job?.current_title].filter(Boolean).join(" - ");
  const live = job ? !["complete", "error", "review"].includes(job.phase) : !error;
  const downloading = job?.phase === "processing" && job.current_step.toLowerCase().includes("download");

  return (
    <StudioPage
      eyebrow="AI AUTO GENERATE"
      title="BUILDING YOUR POWER HOUR"
      subtitle="Estimated time 12 minutes. So this should take about 5 or 10 minutes."
      actions={
        job?.project_id ? (
          <Link
            to={`/project/${job.project_id}`}
            className="crt-action retro-button-secondary inline-flex items-center gap-3 px-4 py-3"
          >
            <FolderOpen className="h-4 w-4" />
            <span className="crt-action__label type-label" data-text="OPEN PROJECT">
              OPEN PROJECT
            </span>
          </Link>
        ) : null
      }
    >
      <section className="retro-panel retro-panel--labeled p-6 pt-8">
        <span className="retro-panel__label">TRANSMISSION STATUS</span>
        <div className="relative z-10 flex flex-col items-center gap-8 md:flex-row md:items-center">
          <RingProgress
            value={job?.progress ?? 0}
            size={188}
            caption={job ? `${job.processed_clips}/${job.total_clips} CLIPS` : "STANDBY"}
          />

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-4">
              {live ? <span className="rec-light">REC</span> : null}
              <p className="type-display text-3xl text-phosphor">{phaseCopy.title}</p>
            </div>
            <p className="type-body mt-2">{phaseCopy.description}</p>

            <div className="mt-5 border-l-2 border-magenta/60 pl-4">
              <p className="type-eyebrow">CURRENT TASK</p>
              <p className="type-display mt-1 text-2xl text-magenta-text">
                {job?.current_step || "Loading the tape"}
                {live ? <span className="ml-1 animate-pulse">_</span> : null}
              </p>
              <p className="type-body mt-1">{currentSong || "Lining up the queue..."}</p>
            </div>

            {job?.phase === "rendering" ? (
              <div className="mt-4">
                <span
                  className={clsx("gpu-active-indicator", !job.gpu_active && "gpu-active-indicator--cpu")}
                  title={job.gpu_active ? "Encoding on the GPU (NVENC)" : "Encoding on the CPU (libx264)"}
                >
                  <span className="gpu-active-indicator__light" />
                  {job.gpu_active ? "GPU ENCODING ACTIVE" : "CPU ENCODING ACTIVE"}
                </span>
              </div>
            ) : null}

            <p className="type-body mt-4 text-phosphor-text/70">
              Background safe: you can leave this page and come back later.
            </p>
          </div>
        </div>

        {job?.phase === "review" ? (
          <div className="osd-notice osd-notice--ok relative z-10 mt-6">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5" />
              <p className="osd-notice__title">READY FOR YOUR REVIEW</p>
            </div>
            <p className="type-body mt-1 !text-inherit">
              Every clip has the AI&apos;s pick pre-selected on its full video. Check each one (drag the window
              anywhere you like), then press Render on the project page. Nothing has been trimmed yet.
            </p>
            {job.current_step && job.current_step !== "Ready for your review" ? (
              <p className="type-body mt-1 !text-status-warn">{job.current_step}</p>
            ) : null}
            <Link
              to={`/project/${job.project_id}`}
              className="crt-action retro-button-primary mt-4 inline-flex items-center gap-2 px-4 py-2.5"
            >
              <Scissors className="h-4 w-4" />
              <span className="crt-action__label type-label" data-text="REVIEW TRIMS">
                REVIEW TRIMS
              </span>
            </Link>
          </div>
        ) : null}

        {job?.phase === "complete" ? (
          <div className="osd-notice osd-notice--ok relative z-10 mt-6">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5" />
              <p className="osd-notice__title">FINAL RENDER COMPLETE</p>
            </div>
            <p className="type-body mt-1 !text-inherit">Your auto-generated power hour is on the tape shelf.</p>
            <Link to="/power-hours" className="crt-action retro-button-primary mt-4 inline-flex items-center gap-2 px-4 py-2.5">
              <Tv className="h-4 w-4" />
              <span className="crt-action__label type-label" data-text="GO TO TAPE SHELF">
                GO TO TAPE SHELF
              </span>
            </Link>
          </div>
        ) : null}

        {job?.phase === "error" ? (
          <div className="osd-notice osd-notice--error relative z-10 mt-6">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-5 w-5" />
              <p className="osd-notice__title">SOMETHING HIT STATIC</p>
            </div>
            <p className="type-body mt-1 !text-inherit">{job.error_message || "The AI generation run hit an error."}</p>
          </div>
        ) : null}

        {error ? (
          <div className="osd-notice osd-notice--error relative z-10 mt-6">
            <p className="osd-notice__title">COULD NOT LOAD PROGRESS</p>
            <p className="type-body mt-1 !text-inherit">{error}</p>
          </div>
        ) : null}
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <ProgressTile
          step={1}
          icon={<Music4 className="h-5 w-5" />}
          label="DOWNLOAD"
          active={downloading}
          complete={Boolean(job && ["review", "rendering", "complete"].includes(job.phase))}
          body="Pulling each source video once (compilations feed several clips)."
        />
        <ProgressTile
          step={2}
          icon={<Scissors className="h-5 w-5" />}
          label="WAVEFORM + AI PICK"
          active={job?.phase === "processing" && !downloading}
          complete={Boolean(job && ["review", "rendering", "complete"].includes(job.phase))}
          body="Analyzing each video and pre-selecting the AI's suggested range for you to check."
        />
        <ProgressTile
          step={3}
          icon={<Film className="h-5 w-5" />}
          label="YOUR REVIEW"
          active={job?.phase === "review"}
          complete={job?.phase === "complete"}
          body="You check every pick on the project page and render when it's right."
        />
      </section>
    </StudioPage>
  );
}

function ProgressTile({
  step,
  icon,
  label,
  active,
  complete,
  body,
}: {
  step: number;
  icon: ReactNode;
  label: string;
  active?: boolean;
  complete?: boolean;
  body: string;
}) {
  return (
    <div
      className={clsx(
        "retro-panel retro-panel--labeled p-5 pt-7 transition-shadow duration-300",
        active && "shadow-[0_0_0_1px_rgba(26,255,228,0.35),0_0_28px_rgba(26,255,228,0.12)]"
      )}
    >
      <span className="retro-panel__label">
        {step} · {label}
      </span>
      <div className="relative z-10">
        <div className="flex items-center gap-3">
          <div className={active ? "text-magenta-soft" : complete ? "text-status-ok" : "text-phosphor-text/50"}>{icon}</div>
          <span
            className={clsx(
              "retro-chip ml-auto",
              complete ? "retro-chip--ok" : active ? "retro-chip--info" : "retro-chip--dim"
            )}
          >
            {complete ? "DONE" : active ? "LIVE" : "STANDBY"}
          </span>
        </div>
        <p className="type-body mt-3">{body}</p>
        {active ? <div className="tracking-loader mt-4" /> : null}
      </div>
    </div>
  );
}

function getPhaseCopy(job: AutoGenerateJobProgress | null): { title: string; description: string } {
  if (!job) {
    return {
      title: "TUNING IN",
      description: "Checking in on the background AI generation run.",
    };
  }

  if (job.phase === "processing") {
    return {
      title: "PREPPING CLIPS FOR THE FINAL MIX",
      description: "Downloading each source, building waveform guidance, and pre-selecting the AI's pick for your review.",
    };
  }

  if (job.phase === "review") {
    return {
      title: "READY FOR YOUR REVIEW",
      description: "Every video is downloaded and analyzed, with the AI's pick pre-selected on each clip.",
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
