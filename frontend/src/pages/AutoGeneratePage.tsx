import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  RefreshCcw,
  Sparkles,
  Wand2,
  CheckCircle2,
  PanelLeftClose,
  PanelLeftOpen,
  Film,
  Lock,
  LockOpen,
  MessageSquarePlus,
  Undo2,
} from "lucide-react";
import Spinner from "../components/Spinner";
import StudioPage from "../components/StudioPage";
import SegmentedControl from "../components/SegmentedControl";
import ChangeoverBuilder from "../components/ChangeoverBuilder";
import AiTransitionReview from "../components/AiTransitionReview";
import type { AiSession, AiSessionState, AutoGenerateMode, AutoGenerateProposal } from "../utils/types";
import {
  ACTIVE_AI_JOB_KEY,
  approveAutoGenerateProposal,
  createProjectForProposal,
  getAiSession,
  isNotFound,
  LostContactError,
  lockAutoGenerateSlot,
  saveAiSession,
  startAutoGenerateProposal,
  startReplaceAutoGenerateProposalItem,
  startReviseAutoGenerateProposal,
  undoAutoGenerateRevision,
  waitForProposalJob,
} from "../utils/api";

// Keep in sync with NOTE_MAX_CHARS / AutoGenerateProposalReviseRequest in the backend.
const SWAP_NOTE_MAX_LENGTH = 300;
const REVISE_COMMENT_MAX_LENGTH = 1000;

// Keep in sync with PROMPT_MAX_LENGTH in backend/app/models/schemas.py.
const PROMPT_MAX_LENGTH = 4000;

type TransitionMode = "default" | "ai" | "custom";
type AiTransitionSources = "cards" | "youtube" | "both";

const TRANSITION_OPTIONS: { value: TransitionMode; label: string; pink?: boolean }[] = [
  { value: "default", label: "DEFAULT SHOT" },
  { value: "ai", label: "AI CREATES" },
  { value: "custom", label: "CUSTOM CLIP", pink: true },
];

const TRANSITION_HELP: Record<TransitionMode, string> = {
  default: "Default: drink art with a corner 3·2·1 countdown into SHOT! and a beer-can crack.",
  ai: "The AI creates several different transitions (drink-art cards and short video moments, each with a corner countdown and a drink cue) and cycles through them. Generate and review them below before building.",
  custom: "Custom clip — build it below.",
};

const MODE_OPTIONS: { value: AutoGenerateMode; label: string; help: string }[] = [
  { value: "music", label: "SONGS", help: "Songs only, resolved to official music videos." },
  { value: "videos", label: "VIDEOS", help: "Regular YouTube videos, with no music assumptions." },
  {
    value: "mixed",
    label: "MIXED",
    help: "The AI chooses songs and non-music clips per slot, following your prompt.",
  },
];

function formatSearchSourceLabel(source: string): string {
  if (source === "youtube_api") return "YOUTUBE API";
  if (source === "yt_dlp") return "YT-DLP";
  return source ? source.replace(/_/g, " ").toUpperCase() : "";
}

export default function AutoGeneratePage() {
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<AutoGenerateMode>("music");
  const [projectName, setProjectName] = useState("");
  const [proposal, setProposal] = useState<AutoGenerateProposal | null>(null);
  const [activeJob, setActiveJob] = useState<{ jobId: string; projectId: number } | null>(null);
  const [promptPanelCollapsed, setPromptPanelCollapsed] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState("");
  const [replacingSlots, setReplacingSlots] = useState<Record<number, boolean>>({});
  const [lockingSlots, setLockingSlots] = useState<Record<number, boolean>>({});
  // A steered swap: which slot's note box is open, and what's typed in it.
  const [noteSlot, setNoteSlot] = useState<number | null>(null);
  const [noteText, setNoteText] = useState("");
  // REVISE: a comment on the whole playlist. The job id is shared so both devices follow it.
  const [reviseComment, setReviseComment] = useState("");
  const [reviseJobId, setReviseJobId] = useState("");
  const [revising, setRevising] = useState(false);
  const [reviseResult, setReviseResult] = useState("");
  // Transition (changeover) config, chosen before approval.
  // OFF (default): backend builds a default 3·2·1 → "SHOT!" card.
  // ON: pre-create the project so the full builder can attach a custom clip.
  const [transitionMode, setTransitionMode] = useState<TransitionMode>("default");
  const [aiTransitionCount, setAiTransitionCount] = useState(4);
  const [aiTransitionSources, setAiTransitionSources] = useState<AiTransitionSources>("both");
  const includeCustomTransition = transitionMode === "custom";
  const [transitionProjectId, setTransitionProjectId] = useState<number | null>(null);
  const [preparingTransition, setPreparingTransition] = useState(false);
  // AI transition review: the user's direction, and what has been generated so far.
  const [transitionPrompt, setTransitionPrompt] = useState("");
  // The call word at the end of each AI transition ("" = no text).
  const [drinkText, setDrinkText] = useState("DRINK!");
  const [aiReview, setAiReview] = useState<{ ready: number; busy: boolean }>({ ready: 0, busy: false });
  // A playlist being generated (saved to the shared draft so the other device can follow it).
  const [proposalJobId, setProposalJobId] = useState("");
  // Shared-draft bookkeeping: the server version we last saw, whether local edits are waiting
  // to be saved, and whether the first load from the server has happened yet.
  const sessionVersion = useRef(-1);
  const localDirty = useRef(false);
  const [hydrated, setHydrated] = useState(false);
  const followingJob = useRef("");
  const followingRevise = useRef("");
  // The draft exactly as the server last had it, so applying it doesn't echo a save back.
  const lastSynced = useRef("");

  const resolvedCount = useMemo(
    () => proposal?.items.filter((item) => item.status === "resolved").length ?? 0,
    [proposal]
  );

  const currentSession = useCallback(
    (): AiSessionState => ({
      prompt,
      mode,
      project_name: projectName,
      proposal_id: proposal?.proposal_id ?? "",
      proposal_job_id: proposalJobId,
      transition_mode: transitionMode,
      ai_transition_count: aiTransitionCount,
      ai_transition_sources: aiTransitionSources,
      transition_project_id: transitionProjectId,
      transition_prompt: transitionPrompt,
      drink_text: drinkText,
      revise_job_id: reviseJobId,
    }),
    [prompt, mode, projectName, proposal, proposalJobId, transitionMode, aiTransitionCount, aiTransitionSources, transitionProjectId, transitionPrompt, drinkText, reviseJobId]
  );

  /** Apply what the server holds (from this device's last save or the other device's). */
  const applySession = useCallback((remote: AiSession, includeDraft: boolean) => {
    sessionVersion.current = remote.version;
    const job = remote.active_job;
    if (job && job.phase !== "complete" && job.phase !== "error") {
      setActiveJob({ jobId: job.job_id, projectId: job.project_id });
    } else {
      setActiveJob(null);
    }
    if (!includeDraft) {
      // Same draft, but the proposal may have changed (a slot replaced on the other device).
      if (remote.proposal) setProposal(remote.proposal);
      return;
    }
    const d = remote.session;
    lastSynced.current = JSON.stringify(d);
    setPrompt(d.prompt);
    setMode(d.mode);
    setProjectName(d.project_name);
    setProposal(remote.proposal);
    setProposalJobId(d.proposal_job_id);
    setTransitionMode(d.transition_mode);
    setAiTransitionCount(d.ai_transition_count);
    setAiTransitionSources(d.ai_transition_sources);
    setTransitionProjectId(d.transition_project_id);
    setTransitionPrompt(d.transition_prompt);
    setDrinkText(d.drink_text ?? "DRINK!");
    setReviseJobId(d.revise_job_id ?? "");
  }, []);

  // First load: restore the shared draft (whichever device last touched it).
  useEffect(() => {
    let cancelled = false;
    getAiSession()
      .then((remote) => {
        if (cancelled) return;
        applySession(remote, true);
      })
      .catch(() => {
        // Backend unreachable: fall back to the job this browser remembers, if any.
        const stored = window.localStorage.getItem(ACTIVE_AI_JOB_KEY);
        try {
          const parsed = stored ? (JSON.parse(stored) as { jobId: string; projectId: number }) : null;
          if (parsed?.jobId && parsed.projectId) setActiveJob(parsed);
        } catch {
          window.localStorage.removeItem(ACTIVE_AI_JOB_KEY);
        }
      })
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });
    return () => {
      cancelled = true;
    };
  }, [applySession]);

  // Save local edits to the shared draft (debounced, so typing doesn't spam the server).
  const snapshot = JSON.stringify(currentSession());
  useEffect(() => {
    if (!hydrated || snapshot === lastSynced.current) return;
    localDirty.current = true;
    const timer = window.setTimeout(() => {
      saveAiSession(JSON.parse(snapshot) as AiSessionState)
        .then((saved) => {
          sessionVersion.current = saved.version;
          lastSynced.current = snapshot;
        })
        .catch(() => {
          // Offline for a moment: the next edit or poll retries.
        })
        .finally(() => {
          localDirty.current = false;
        });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [snapshot, hydrated]);

  // Follow the other device: pick up its edits while this page is open and visible.
  useEffect(() => {
    if (!hydrated) return;
    const timer = window.setInterval(() => {
      if (document.hidden || localDirty.current || approving) return;
      getAiSession()
        .then((remote) => {
          if (localDirty.current) return;
          applySession(remote, remote.version !== sessionVersion.current);
        })
        .catch(() => {});
    }, 4000);
    return () => window.clearInterval(timer);
  }, [hydrated, approving, applySession]);

  // A playlist generating (started here or on the other device): poll it until it lands.
  useEffect(() => {
    if (!proposalJobId || followingJob.current === proposalJobId) return;
    followingJob.current = proposalJobId;
    let cancelled = false;
    let keepJob = false;
    setGenerating(true);
    (async () => {
      try {
        const status = await waitForProposalJob(proposalJobId, () => cancelled);
        if (cancelled || !status) return;
        if (status.status === "complete" && status.proposal) {
          setProposal(status.proposal);
          // A new proposal invalidates any pre-created transition project.
          setTransitionProjectId(null);
          setAiReview({ ready: 0, busy: false });
          setTransitionMode("default");
          setProjectName((current) => current.trim() || buildDefaultProjectName(status.proposal!.normalized_prompt));
        } else {
          throw new Error(status.error_message || "Failed to create AI proposal");
        }
      } catch (err) {
        if (cancelled) return;
        // Server unreachable: the build keeps going there, so leave it attached to the draft.
        keepJob = err instanceof LostContactError;
        setError(
          isNotFound(err)
            ? "That playlist job is gone (the backend restarted). Generate it again."
            : err instanceof Error
              ? err.message
              : "Failed to create AI proposal"
        );
      } finally {
        if (!cancelled) {
          setGenerating(false);
          if (!keepJob) {
            setProposalJobId("");
            followingJob.current = "";
          }
        }
      }
    })();
    return () => {
      cancelled = true;
      followingJob.current = "";
    };
  }, [proposalJobId]);

  // A REVISE running (started here or on the other device): poll it until it lands.
  useEffect(() => {
    if (!reviseJobId) {
      setRevising(false);
      return;
    }
    if (followingRevise.current === reviseJobId) return;
    followingRevise.current = reviseJobId;
    let cancelled = false;
    let keepJob = false;
    setRevising(true);
    setReviseResult("");
    (async () => {
      try {
        const status = await waitForProposalJob(reviseJobId, () => cancelled);
        if (cancelled || !status) return;
        if (status.status === "complete" && status.proposal) {
          setProposal(status.proposal);
          const swapped = status.proposal.items.filter((item) => item.revised).length;
          setReviseResult(
            swapped
              ? `SWAPPED ${swapped} SLOT${swapped === 1 ? "" : "S"} · TAGGED NEW`
              : "NOTHING SWAPPED. TRY NAMING WHAT SHOULD CHANGE"
          );
          setReviseComment("");
        } else {
          throw new Error(status.error_message || "Failed to revise the playlist");
        }
      } catch (err) {
        if (cancelled) return;
        keepJob = err instanceof LostContactError;
        setError(
          isNotFound(err)
            ? "That revision is gone (the backend restarted). Try it again."
            : err instanceof Error
              ? err.message
              : "Failed to revise the playlist"
        );
      } finally {
        if (!cancelled) {
          setRevising(false);
          if (!keepJob) {
            setReviseJobId("");
            followingRevise.current = "";
          }
        }
      }
    })();
    return () => {
      cancelled = true;
      followingRevise.current = "";
    };
  }, [reviseJobId]);

  async function handleRevise() {
    const comment = reviseComment.trim();
    if (!proposal || !comment || revising) return;
    setError("");
    setReviseResult("");
    setRevising(true);
    try {
      const { revise_job_id } = await startReviseAutoGenerateProposal(proposal.proposal_id, comment);
      setReviseJobId(revise_job_id);
    } catch (err) {
      setRevising(false);
      setError(err instanceof Error ? err.message : "Failed to revise the playlist");
    }
  }

  async function handleUndoRevision() {
    if (!proposal) return;
    setError("");
    try {
      setProposal(await undoAutoGenerateRevision(proposal.proposal_id));
      setReviseResult("RESTORED THE LIST FROM BEFORE THE LAST REVISE");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to undo the revision");
    }
  }

  async function handleLock(slotIndex: number, locked: boolean) {
    if (!proposal) return;
    setLockingSlots((prev) => ({ ...prev, [slotIndex]: true }));
    setError("");
    try {
      setProposal(await lockAutoGenerateSlot(proposal.proposal_id, slotIndex, locked));
      if (locked && noteSlot === slotIndex) setNoteSlot(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to lock the slot");
    } finally {
      setLockingSlots((prev) => ({ ...prev, [slotIndex]: false }));
    }
  }

  function toggleNote(slotIndex: number) {
    setNoteSlot((current) => (current === slotIndex ? null : slotIndex));
    setNoteText("");
  }

  async function handleGenerate() {
    if (!prompt.trim()) return;
    setGenerating(true);
    setError("");
    try {
      const { proposal_job_id } = await startAutoGenerateProposal(prompt.trim(), mode);
      setProposalJobId(proposal_job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create AI proposal");
      setGenerating(false);
    }
  }

  async function handleReplace(slotIndex: number, note = "") {
    if (!proposal) return;
    setReplacingSlots((prev) => ({ ...prev, [slotIndex]: true }));
    setError("");
    if (noteSlot === slotIndex) setNoteSlot(null);
    try {
      const { replace_job_id } = await startReplaceAutoGenerateProposalItem(proposal.proposal_id, slotIndex, note.trim());
      const status = await waitForProposalJob(replace_job_id);
      if (status?.status === "complete" && status.proposal) {
        // A pre-created transition project is kept: approving re-syncs its clips with
        // the proposal, so reviewed/custom transitions survive a song swap.
        setProposal(status.proposal);
      } else {
        throw new Error(status?.error_message || "Failed to replace song");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to replace song");
    } finally {
      setReplacingSlots((prev) => ({ ...prev, [slotIndex]: false }));
    }
  }

  async function handleSelectTransitionMode(next: TransitionMode) {
    if (next === transitionMode || preparingTransition) return;
    const previous = transitionMode;
    setTransitionMode(next);
    // Choosing "custom" or "ai" the first time pre-creates the project so the builder /
    // the AI transition review has a real project id to attach transitions to.
    if ((next === "custom" || next === "ai") && transitionProjectId === null && proposal) {
      setPreparingTransition(true);
      setError("");
      try {
        const { project_id } = await createProjectForProposal(
          proposal.proposal_id,
          projectName.trim() || buildDefaultProjectName(proposal.normalized_prompt)
        );
        setTransitionProjectId(project_id);
      } catch (err) {
        setTransitionMode(previous);
        setError(err instanceof Error ? err.message : "Failed to prepare transition builder");
      } finally {
        setPreparingTransition(false);
      }
    }
  }

  async function handleApprove() {
    if (!proposal) return;
    setApproving(true);
    setError("");
    try {
      const result = await approveAutoGenerateProposal(proposal.proposal_id, {
        projectName: projectName.trim() || buildDefaultProjectName(proposal.normalized_prompt),
        // Reuse the pre-created project when a custom transition was configured
        // (avoids orphaning it); backend falls back to the default SHOT card.
        projectId: transitionProjectId,
        includeTransition: true,
        aiTransitionCount: transitionMode === "ai" ? aiTransitionCount : 0,
        aiTransitionSources,
        aiTransitionsReviewed: transitionMode === "ai" && aiReview.ready > 0,
        aiTransitionPrompt: transitionMode === "ai" ? transitionPrompt : "",
        aiTransitionText: transitionMode === "ai" ? drinkText.trim() : undefined,
      });
      const nextJob = { jobId: result.job_id, projectId: result.project_id };
      window.localStorage.setItem(ACTIVE_AI_JOB_KEY, JSON.stringify(nextJob));
      setActiveJob(nextJob);
      navigate(`/auto-generate/progress/${result.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve playlist");
    } finally {
      setApproving(false);
    }
  }

  return (
    <StudioPage eyebrow="AI AUTO GENERATE" title="BUILD A POWER HOUR FROM A PROMPT">
            <div className="flex min-h-[calc(100vh-17rem)] flex-col gap-6 xl:flex-row">
              <section
                className={[
                  "retro-panel transition-all duration-300 xl:shrink-0",
                  !promptPanelCollapsed && "retro-panel--labeled",
                  promptPanelCollapsed ? "p-3 xl:w-[88px]" : "p-5 pt-7 xl:w-[360px]",
                ].filter(Boolean).join(" ")}
              >
                {!promptPanelCollapsed && (
                  <span className="retro-panel__label">STEP 1 · DESCRIBE THE MIX</span>
                )}
                <div className="relative z-10 h-full">
                  <div className={promptPanelCollapsed ? "flex h-full flex-col items-center gap-4" : ""}>
                    <button
                      onClick={() => setPromptPanelCollapsed((current) => !current)}
                      className={[
                        "crt-action retro-button-secondary font-retro text-lg tracking-[0.16em] hidden xl:inline-flex",
                        promptPanelCollapsed
                          ? "w-full items-center justify-center px-2 py-2"
                          : "items-center gap-2 self-start px-3 py-2",
                      ].join(" ")}
                      aria-label={promptPanelCollapsed ? "Open panel" : "Collapse panel"}
                      title={promptPanelCollapsed ? "Open panel" : "Collapse panel"}
                    >
                      {promptPanelCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                      {!promptPanelCollapsed ? (
                        <span
                          className="crt-action__label"
                          data-text="COLLAPSE PANEL"
                        >
                          COLLAPSE PANEL
                        </span>
                      ) : null}
                    </button>

                    {promptPanelCollapsed ? (
                      <div className="flex flex-1 flex-col items-center justify-between py-3">
                        <div className="flex flex-col items-center gap-4">
                          <div className="font-retro text-lg tracking-[0.2em] text-phosphor/70 [writing-mode:vertical-rl]">
                            STEP 1
                          </div>
                          <div className="font-retro text-lg tracking-[0.2em] text-magenta-soft/80 [writing-mode:vertical-rl]">
                            DESCRIBE THE MIX
                          </div>
                        </div>
                        <button
                          onClick={handleGenerate}
                          disabled={generating || revising || !prompt.trim()}
                          className="crt-action retro-button-primary inline-flex items-center justify-center px-3 py-3 disabled:cursor-not-allowed disabled:opacity-40"
                          aria-label={proposal ? "Regenerate playlist" : "Generate playlist"}
                          title={proposal ? "Regenerate playlist" : "Generate playlist"}
                        >
                          {generating ? <Spinner className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
                        </button>
                      </div>
                    ) : (
                      <>
                        <textarea
                          value={prompt}
                          onChange={(e) => setPrompt(e.target.value)}
                          rows={10}
                          maxLength={PROMPT_MAX_LENGTH}
                          className="retro-input w-full px-4 py-4 font-mono text-[15px] leading-relaxed"
                          placeholder="Describe the genre, era, mood, energy, and any must-have constraints..."
                        />
                        <p className="type-data mt-1 text-right text-sm text-phosphor-text/75">
                          {prompt.length} / {PROMPT_MAX_LENGTH}
                        </p>

                        <p className="type-label mt-4 mb-2 text-phosphor-text">PLAYLIST CONTENT</p>
                        <SegmentedControl
                          label="Playlist content"
                          options={MODE_OPTIONS}
                          value={mode}
                          onChange={setMode}
                        />
                        <p className="mt-1.5 type-body">
                          {MODE_OPTIONS.find((option) => option.value === mode)?.help}
                        </p>

                        <div className="mt-4 flex flex-wrap gap-3">
                          <button
                            onClick={handleGenerate}
                            disabled={generating || revising || !prompt.trim()}
                            className="crt-action retro-button-primary inline-flex items-center gap-3 px-5 py-3 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            {generating ? <Spinner className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
                            <span className="crt-action__label" data-text={proposal ? "REGENERATE PLAYLIST" : "GENERATE PLAYLIST"}>
                              {proposal ? "REGENERATE PLAYLIST" : "GENERATE PLAYLIST"}
                            </span>
                          </button>
                        </div>

                      </>
                    )}
                  </div>
                </div>
              </section>

              <section className="retro-panel retro-panel--labeled flex min-h-[55vh] flex-1 flex-col p-5 pt-7">
                <span className="retro-panel__label">STEP 2 · REVIEW THE PLAYLIST</span>
                <div className="relative z-10 flex min-h-0 flex-1 flex-col">
                  <div className="flex flex-col gap-3 border-b border-[rgba(26,255,228,0.12)] pb-5 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <p className="type-body">
                        Approving downloads every video and pre-selects the AI&apos;s pick on each one. Nothing is
                        trimmed or rendered until you&apos;ve checked them on the project page.
                      </p>
                    </div>
                    <div className="font-retro text-lg tracking-[0.2em] text-phosphor/75">
                      {proposal ? `${resolvedCount}/60 RESOLVED` : "WAITING FOR PROMPT"}
                    </div>
                  </div>

                  {error ? (
                    <div className="osd-notice osd-notice--error mt-4">
                      <p className="osd-notice__title">SIGNAL LOST</p>
                      <p className="type-body mt-1 !text-inherit">{error}</p>
                    </div>
                  ) : null}

                  {activeJob ? (
                    <div className="mt-4 border border-magenta-soft/20 bg-[#200815]/70 px-4 py-3">
                      <p className="font-retro text-lg tracking-[0.18em] text-magenta-text">
                        BACKGROUND GENERATION IN PROGRESS
                      </p>
                      <button
                        onClick={() => navigate(`/auto-generate/progress/${activeJob.jobId}`)}
                        className="crt-action retro-button-secondary mt-3 inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em]"
                      >
                        <span className="crt-action__label" data-text="RESUME PROGRESS">
                          RESUME PROGRESS
                        </span>
                      </button>
                    </div>
                  ) : null}

                  {proposal ? (
                    <div className="mt-5 flex min-h-0 flex-1 flex-col">
                      <div className="mt-5 grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
                        <div>
                          <label className="mb-2 block font-retro text-lg tracking-[0.18em] text-phosphor-text">
                            PROJECT NAME
                          </label>
                          <input
                            value={projectName}
                            onChange={(e) => setProjectName(e.target.value)}
                            className="retro-input w-full px-4 py-3 font-mono text-sm tracking-[0.12em]"
                            placeholder="AI Power Hour"
                          />
                        </div>
                        <button
                          onClick={handleApprove}
                          disabled={approving || revising || proposal.unresolved_count > 0 || (transitionMode === "ai" && aiReview.busy)}
                          className="crt-action retro-button-primary inline-flex items-center gap-3 px-5 py-3 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {approving ? <Spinner className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                          <span className="crt-action__label" data-text="APPROVE & PREP FOR REVIEW">
                            APPROVE & PREP FOR REVIEW
                          </span>
                        </button>
                      </div>

                      {/* Transition between clips */}
                      <div className="mt-5">
                        <div className="border border-phosphor/14 bg-crt-panel/60 p-4">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                            <div className="flex items-start gap-3">
                              <Film className="mt-0.5 h-4 w-4 shrink-0 text-magenta-soft" />
                              <div>
                                <p className="font-retro text-lg tracking-[0.18em] text-zinc-200">
                                  TRANSITION BETWEEN CLIPS
                                </p>
                                <p className="mt-1 type-body">
                                  {TRANSITION_HELP[transitionMode]}
                                </p>
                              </div>
                            </div>
                            {preparingTransition ? (
                              <span className="type-label inline-flex h-11 w-full items-center justify-center gap-2 border border-phosphor/20 text-phosphor-text/80 sm:w-[26rem]">
                                <Spinner className="h-3.5 w-3.5" /> PREPARING…
                              </span>
                            ) : (
                              <SegmentedControl
                                label="Transition type"
                                options={TRANSITION_OPTIONS}
                                value={transitionMode}
                                onChange={handleSelectTransitionMode}
                                className="w-full shrink-0 sm:w-[26rem]"
                              />
                            )}
                          </div>

                          {transitionMode === "ai" && (
                            <div className="mt-4 grid gap-3 border-t border-phosphor/14 pt-4 sm:grid-cols-2">
                              <label className="flex items-center justify-between gap-3 font-mono text-sm tracking-[0.08em] text-phosphor-text/80">
                                How many different transitions
                                <select
                                  value={aiTransitionCount}
                                  onChange={(e) => setAiTransitionCount(Number(e.target.value))}
                                  className="retro-input px-2 py-1.5 font-mono text-sm"
                                >
                                  {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                                    <option key={n} value={n}>{n}</option>
                                  ))}
                                </select>
                              </label>
                              <label className="flex items-center justify-between gap-3 font-mono text-sm tracking-[0.08em] text-phosphor-text/80">
                                Made from
                                <select
                                  value={aiTransitionSources}
                                  onChange={(e) => setAiTransitionSources(e.target.value as AiTransitionSources)}
                                  className="retro-input px-2 py-1.5 font-mono text-sm"
                                >
                                  <option value="both">Cards + YouTube clips</option>
                                  <option value="cards">Generated cards only</option>
                                  <option value="youtube">YouTube clips only</option>
                                </select>
                              </label>
                              <p className="type-body sm:col-span-2">
                                Cards + YouTube alternates the two. Video moments never reuse a song from the playlist; one that can't be fetched falls back to a drink-art card.
                              </p>
                              {transitionProjectId !== null && (
                                <div className="sm:col-span-2">
                                  <AiTransitionReview
                                    projectId={transitionProjectId}
                                    powerHourPrompt={proposal.normalized_prompt}
                                    transitionPrompt={transitionPrompt}
                                    onTransitionPromptChange={setTransitionPrompt}
                                    drinkText={drinkText}
                                    onDrinkTextChange={setDrinkText}
                                    count={aiTransitionCount}
                                    sources={aiTransitionSources}
                                    onStatus={setAiReview}
                                  />
                                </div>
                              )}
                            </div>
                          )}
                        </div>

                        {includeCustomTransition && transitionProjectId !== null && (
                          <div className="mt-4">
                            <ChangeoverBuilder projectId={transitionProjectId} />
                          </div>
                        )}
                      </div>

                      {/* Revise the picks without redoing the prompt */}
                      <div className="mt-5 border border-phosphor/14 bg-crt-panel/60 p-4">
                        <div className="flex items-start gap-3">
                          <Wand2 className="mt-0.5 h-4 w-4 shrink-0 text-magenta-soft" />
                          <div className="min-w-0">
                            <p className="font-retro text-lg tracking-[0.18em] text-zinc-200">REVISE THE PICKS</p>
                            <p className="mt-1 type-body">
                              Tell the AI what to change. It swaps only the slots that need it, never touches locked
                              ones, and tags what it changed NEW. The length stays at 60.
                            </p>
                          </div>
                        </div>
                        <textarea
                          value={reviseComment}
                          onChange={(e) => setReviseComment(e.target.value)}
                          rows={2}
                          maxLength={REVISE_COMMENT_MAX_LENGTH}
                          disabled={revising}
                          className="retro-input mt-3 w-full px-4 py-3 font-mono text-[15px] leading-relaxed disabled:opacity-60"
                          placeholder="e.g. more funny auditions, fewer ballads, use a compilation if there's a good one"
                        />
                        <div className="mt-3 flex flex-wrap items-center gap-3">
                          <button
                            onClick={handleRevise}
                            disabled={!reviseComment.trim() || revising || generating || approving || Object.values(replacingSlots).some(Boolean)}
                            className="crt-action retro-button-primary inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            {revising ? <Spinner className="h-3.5 w-3.5" /> : <Wand2 className="h-3.5 w-3.5" />}
                            <span className="crt-action__label" data-text={revising ? "REVISING…" : "REVISE"}>
                              {revising ? "REVISING…" : "REVISE"}
                            </span>
                          </button>
                          {proposal.can_undo ? (
                            <button
                              onClick={handleUndoRevision}
                              disabled={revising || approving}
                              className="crt-action retro-button-secondary inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              <Undo2 className="h-3.5 w-3.5" />
                              <span className="crt-action__label" data-text="UNDO REVISE">UNDO REVISE</span>
                            </button>
                          ) : null}
                          {proposal.items.some((item) => item.locked) ? (
                            <span className="type-label text-phosphor-text/80">
                              {proposal.items.filter((item) => item.locked).length} LOCKED
                            </span>
                          ) : null}
                        </div>
                        {revising ? (
                          <p className="mt-3 type-body">
                            The AI is picking which slots to swap; only those are searched and checked.
                          </p>
                        ) : reviseResult ? (
                          <div className="osd-notice osd-notice--ok mt-3">
                            <p className="osd-notice__title">{reviseResult}</p>
                          </div>
                        ) : null}
                        {proposal.notes && proposal.notes.length > 0 ? (
                          <div className="mt-3 border-t border-phosphor/14 pt-3">
                            <p className="type-label text-phosphor-text">EVERY SWAP FOLLOWS YOUR NOTES</p>
                            <ol className="mt-1 list-decimal space-y-1 pl-6">
                              {proposal.notes.map((note, index) => (
                                <li key={index} className="type-body">{note}</li>
                              ))}
                            </ol>
                          </div>
                        ) : null}
                      </div>

                      <div className="tracklist mt-5 flex-1 overflow-y-auto pr-1">
                        {proposal.items.map((item) => (
                          <div
                            key={`${proposal.proposal_id}-${item.slot_index}`}
                            className={[
                              "tracklist-row flex-col !items-stretch gap-0 p-0",
                              item.status !== "resolved" ? "tracklist-row--warn" : "",
                            ].filter(Boolean).join(" ")}
                          >
                            <div className="flex flex-col gap-4 p-4 lg:grid lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center">
                              <div className="flex min-w-0 items-center gap-4">
                                <span className="tracklist-row__num">{String(item.slot_index + 1).padStart(2, "0")}</span>
                                {item.thumbnail ? (
                                  <img
                                    src={item.thumbnail}
                                    alt={item.title || item.requested_title}
                                    className="h-16 w-28 shrink-0 object-cover ring-1 ring-phosphor/10"
                                  />
                                ) : (
                                  <div className="flex h-16 w-28 shrink-0 items-center justify-center bg-crt-panel">
                                    <span className="retro-chip retro-chip--dim">PENDING</span>
                                  </div>
                                )}
                              </div>
                              <div className="min-w-0 overflow-hidden">
                                <div className="flex min-w-0 flex-wrap items-center gap-2">
                                  <p className="min-w-0 max-w-full truncate font-retro text-lg tracking-[0.12em] text-magenta-text">
                                    {item.title || item.requested_title}
                                  </p>
                                  {proposal?.mode === "mixed" ? (
                                    <span className="retro-chip retro-chip--dim shrink-0">
                                      {item.kind === "clip" ? "CLIP" : "SONG"}
                                    </span>
                                  ) : null}
                                  {(item.segment_count ?? 1) > 1 ? (
                                    <span
                                      className="retro-chip retro-chip--dim shrink-0"
                                      title="One compilation video, cut into several different clips"
                                    >
                                      PART {(item.segment_index ?? 0) + 1}/{item.segment_count}
                                    </span>
                                  ) : null}
                                  {item.revised ? (
                                    <span className="retro-chip retro-chip--pink shrink-0" title="Swapped in by the last REVISE">
                                      NEW
                                    </span>
                                  ) : null}
                                  {item.locked ? (
                                    <span className="retro-chip retro-chip--ok shrink-0" title="REVISE and REPLACE leave this slot alone">
                                      LOCKED
                                    </span>
                                  ) : null}
                                  {item.resolution_source ? (
                                    <span className="retro-chip retro-chip--info shrink-0">
                                      {formatSearchSourceLabel(item.resolution_source)}
                                    </span>
                                  ) : null}
                                </div>
                                <p className="mt-1 truncate font-mono text-sm uppercase tracking-[0.14em] text-phosphor-text/70">
                                  {(item.artist || item.requested_artist || "Unresolved")} {item.duration ? `· ${item.duration}` : ""}
                                </p>
                                {item.reason ? (
                                  <p className="mt-2 truncate type-body">
                                    {item.reason}
                                  </p>
                                ) : null}
                                {item.status !== "resolved" ? (
                                  <p className="mt-2 font-mono text-sm text-red-300">
                                    This slot is unresolved. Replace it or regenerate the full playlist.
                                  </p>
                                ) : null}
                              </div>
                              <div className="flex shrink-0 items-center gap-2 self-start lg:self-auto lg:justify-self-end">
                                <button
                                  onClick={() => handleLock(item.slot_index, !item.locked)}
                                  disabled={lockingSlots[item.slot_index] || replacingSlots[item.slot_index] || approving}
                                  aria-pressed={Boolean(item.locked)}
                                  aria-label={item.locked ? `Unlock slot ${item.slot_index + 1}` : `Lock slot ${item.slot_index + 1}`}
                                  title={item.locked ? "Unlock: REVISE and REPLACE may change it again" : "Lock: REVISE and REPLACE leave it alone"}
                                  className={[
                                    "crt-action inline-flex h-11 w-11 items-center justify-center disabled:cursor-not-allowed disabled:opacity-40",
                                    item.locked ? "retro-button-primary" : "retro-button-ghost",
                                  ].join(" ")}
                                >
                                  {item.locked ? <Lock className="h-4 w-4" /> : <LockOpen className="h-4 w-4" />}
                                </button>
                                <button
                                  onClick={() => toggleNote(item.slot_index)}
                                  disabled={item.locked || replacingSlots[item.slot_index] || generating || approving || revising}
                                  aria-expanded={noteSlot === item.slot_index}
                                  aria-label={`Replace slot ${item.slot_index + 1} with a note`}
                                  title="Replace with a note: a comment, an exact entry, or a YouTube link"
                                  className="crt-action retro-button-ghost inline-flex h-11 w-11 items-center justify-center disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  <MessageSquarePlus className="h-4 w-4" />
                                </button>
                                <button
                                  onClick={() => handleReplace(item.slot_index)}
                                  disabled={item.locked || replacingSlots[item.slot_index] || generating || approving || revising}
                                  className="crt-action retro-button-secondary inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  {replacingSlots[item.slot_index] ? (
                                    <Spinner className="h-3.5 w-3.5" />
                                  ) : (
                                    <RefreshCcw className="h-3.5 w-3.5" />
                                  )}
                                  <span className="crt-action__label" data-text="REPLACE">
                                    REPLACE
                                  </span>
                                </button>
                              </div>
                            </div>
                            {noteSlot === item.slot_index && !item.locked ? (
                              <form
                                onSubmit={(e) => {
                                  e.preventDefault();
                                  handleReplace(item.slot_index, noteText);
                                }}
                                className="border-t border-phosphor/14 px-4 pb-4 pt-3"
                              >
                                <label className="type-label mb-2 block text-phosphor-text" htmlFor={`swap-note-${item.slot_index}`}>
                                  WHAT INSTEAD?
                                </label>
                                <div className="flex flex-col gap-2 sm:flex-row">
                                  <input
                                    id={`swap-note-${item.slot_index}`}
                                    autoFocus
                                    value={noteText}
                                    onChange={(e) => setNoteText(e.target.value)}
                                    maxLength={SWAP_NOTE_MAX_LENGTH}
                                    className="retro-input min-w-0 flex-1 px-3 py-2 font-mono text-sm"
                                    placeholder="something funnier · Artist - Title · a YouTube link"
                                  />
                                  <div className="flex gap-2">
                                    <button
                                      type="submit"
                                      disabled={!noteText.trim()}
                                      className="crt-action retro-button-primary inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                      <span className="crt-action__label" data-text="SWAP">SWAP</span>
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setNoteSlot(null)}
                                      className="crt-action retro-button-ghost inline-flex items-center px-4 py-2 font-retro text-lg tracking-[0.16em]"
                                    >
                                      <span className="crt-action__label" data-text="CANCEL">CANCEL</span>
                                    </button>
                                  </div>
                                </div>
                                <p className="mt-2 type-body">
                                  A comment steers the AI. A song or video you name exactly is used without the off-topic
                                  check, and a YouTube link is used as-is.
                                </p>
                              </form>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex min-h-[420px] flex-1 flex-col items-center justify-center px-6 text-center">
                      {generating ? (
                        <>
                          <Spinner className="h-10 w-10 text-magenta-soft" />
                          <p className="mt-4 font-retro text-2xl tracking-[0.18em] text-phosphor-text">
                            GENERATING PLAYLIST...
                          </p>
                          <p className="mt-3 max-w-md type-body">
                            The AI is planning songs and the app is resolving them to real music videos.
                          </p>
                        </>
                      ) : (
                        <>
                          <Wand2 className="h-10 w-10 text-magenta-soft/70" />
                          <p className="mt-4 font-retro text-2xl tracking-[0.18em] text-zinc-200">
                            NO PLAYLIST YET
                          </p>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </section>
            </div>
    </StudioPage>
  );
}

function buildDefaultProjectName(prompt: string): string {
  const words = prompt
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 6)
    .join(" ");
  return words ? `${words} Power Hour` : "AI Power Hour";
}
