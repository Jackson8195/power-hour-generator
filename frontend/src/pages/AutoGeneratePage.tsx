import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Loader2,
  RefreshCcw,
  Sparkles,
  Wand2,
  CheckCircle2,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import CrtStaticText from "../components/CrtStaticText";
import BackButton from "../components/BackButton";
import type { AutoGenerateProposal } from "../utils/types";
import {
  approveAutoGenerateProposal,
  getAutoGenerateProposalJob,
  startAutoGenerateProposal,
  startReplaceAutoGenerateProposalItem,
} from "../utils/api";

function formatSearchSourceLabel(source: string): string {
  if (source === "youtube_api") return "YOUTUBE API";
  if (source === "yt_dlp") return "YT-DLP";
  return source ? source.replace(/_/g, " ").toUpperCase() : "";
}

export default function AutoGeneratePage() {
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [projectName, setProjectName] = useState("");
  const [proposal, setProposal] = useState<AutoGenerateProposal | null>(null);
  const [activeJob, setActiveJob] = useState<{ jobId: string; projectId: number } | null>(null);
  const [promptPanelCollapsed, setPromptPanelCollapsed] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState("");
  const [replacingSlots, setReplacingSlots] = useState<Record<number, boolean>>({});

  const resolvedCount = useMemo(
    () => proposal?.items.filter((item) => item.status === "resolved").length ?? 0,
    [proposal]
  );

  useEffect(() => {
    const stored = window.localStorage.getItem("power-hour-active-ai-job");
    if (!stored) return;
    try {
      const parsed = JSON.parse(stored) as { jobId: string; projectId: number };
      if (parsed?.jobId && parsed?.projectId) {
        setActiveJob(parsed);
      }
    } catch {
      window.localStorage.removeItem("power-hour-active-ai-job");
    }
  }, []);

  async function handleGenerate() {
    if (!prompt.trim()) return;
    setGenerating(true);
    setError("");
    try {
      const { proposal_job_id } = await startAutoGenerateProposal(prompt.trim());
      while (true) {
        await new Promise((res) => setTimeout(res, 2000));
        const status = await getAutoGenerateProposalJob(proposal_job_id);
        if (status.status === "complete" && status.proposal) {
          setProposal(status.proposal);
          if (!projectName.trim()) {
            setProjectName(buildDefaultProjectName(status.proposal.normalized_prompt));
          }
          break;
        }
        if (status.status === "error") {
          throw new Error(status.error_message || "Failed to create AI proposal");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create AI proposal");
    } finally {
      setGenerating(false);
    }
  }

  async function handleReplace(slotIndex: number) {
    if (!proposal) return;
    setReplacingSlots((prev) => ({ ...prev, [slotIndex]: true }));
    setError("");
    try {
      const { replace_job_id } = await startReplaceAutoGenerateProposalItem(proposal.proposal_id, slotIndex);
      while (true) {
        await new Promise((res) => setTimeout(res, 2000));
        const status = await getAutoGenerateProposalJob(replace_job_id);
        if (status.status === "complete" && status.proposal) {
          setProposal(status.proposal);
          break;
        }
        if (status.status === "error") {
          throw new Error(status.error_message || "Failed to replace song");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to replace song");
    } finally {
      setReplacingSlots((prev) => ({ ...prev, [slotIndex]: false }));
    }
  }

  async function handleApprove() {
    if (!proposal) return;
    setApproving(true);
    setError("");
    try {
      const result = await approveAutoGenerateProposal(
        proposal.proposal_id,
        projectName.trim() || buildDefaultProjectName(proposal.normalized_prompt)
      );
      const nextJob = { jobId: result.job_id, projectId: result.project_id };
      window.localStorage.setItem("power-hour-active-ai-job", JSON.stringify(nextJob));
      setActiveJob(nextJob);
      navigate(`/auto-generate/progress/${result.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve playlist");
    } finally {
      setApproving(false);
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#070b10] scanlines">
      <div className="pointer-events-none fixed inset-0 animate-crt-flicker bg-transparent" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,43,157,0.12),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(26,255,228,0.08),transparent_30%)]" />

      <main className="relative z-10 mx-auto flex min-h-screen w-full max-w-[1800px] flex-col px-4 py-8 sm:px-6">
        <div className="retro-shell rounded-[28px] px-5 py-6 sm:px-8 sm:py-8">
          <div className="relative z-10">
            <div className="flex flex-col gap-4 border-b border-[rgba(26,255,228,0.14)] pb-6 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-3xl">
                <p className="font-retro text-xs tracking-[0.45em] text-[#1affe4]/60">
                  AI AUTO GENERATE
                </p>
                <CrtStaticText
                  as="h1"
                  text="BUILD A POWER HOUR FROM A PROMPT"
                  className="mt-2"
                  textClassName="font-retro text-4xl tracking-[0.18em] text-[#ff77c2] glow-text sm:text-5xl"
                />
              </div>
              <BackButton fallback="/" />
            </div>

            <div className="mt-6 flex min-h-[calc(100vh-17rem)] flex-col gap-6 xl:flex-row">
              <section
                className={[
                  "retro-panel rounded-[24px] transition-all duration-300 xl:shrink-0",
                  promptPanelCollapsed ? "p-3 xl:w-[88px]" : "p-5 xl:w-[360px]",
                ].join(" ")}
              >
                <div className="relative z-10 h-full">
                  <div className={promptPanelCollapsed ? "flex h-full flex-col items-center gap-4" : ""}>
                    <button
                      onClick={() => setPromptPanelCollapsed((current) => !current)}
                      className={[
                        "crt-action retro-button-secondary inline-flex rounded-xl font-retro text-xs tracking-[0.16em]",
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
                          <div className="font-retro text-[10px] tracking-[0.38em] text-[#1affe4]/65 [writing-mode:vertical-rl]">
                            STEP 1
                          </div>
                          <div className="font-retro text-[10px] tracking-[0.28em] text-[#ff77c2]/70 [writing-mode:vertical-rl]">
                            DESCRIBE THE MIX
                          </div>
                        </div>
                        <button
                          onClick={handleGenerate}
                          disabled={generating || !prompt.trim()}
                          className="crt-action retro-button-primary inline-flex items-center justify-center rounded-xl px-3 py-3 disabled:cursor-not-allowed disabled:opacity-40"
                          aria-label={proposal ? "Regenerate playlist" : "Generate playlist"}
                          title={proposal ? "Regenerate playlist" : "Generate playlist"}
                        >
                          {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                        </button>
                      </div>
                    ) : (
                      <>
                        <CrtStaticText
                          as="h2"
                          text="STEP 1 · DESCRIBE THE MIX"
                          textClassName="font-retro text-2xl tracking-[0.18em] text-[#1affe4]"
                        />

                        <textarea
                          value={prompt}
                          onChange={(e) => setPrompt(e.target.value)}
                          rows={10}
                          className="retro-input mt-5 w-full rounded-[20px] px-4 py-4 font-mono text-sm tracking-[0.12em]"
                          placeholder="Describe the genre, era, mood, energy, and any must-have constraints..."
                        />

                        <div className="mt-4 flex flex-wrap gap-3">
                          <button
                            onClick={handleGenerate}
                            disabled={generating || !prompt.trim()}
                            className="crt-action retro-button-primary inline-flex items-center gap-3 rounded-xl px-5 py-3 font-retro text-base tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
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

              <section className="retro-panel flex min-h-[55vh] flex-1 flex-col rounded-[24px] p-5">
                <div className="relative z-10 flex min-h-0 flex-1 flex-col">
                  <div className="flex flex-col gap-3 border-b border-[rgba(26,255,228,0.12)] pb-5 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <CrtStaticText
                        as="h2"
                        text="STEP 2 · REVIEW THE PLAYLIST"
                        textClassName="font-retro text-2xl tracking-[0.18em] text-zinc-200"
                      />
                      <p className="mt-2 font-mono text-xs uppercase tracking-[0.16em] text-[#91fff2]/45">
                        Approve the final list to create and process the project.
                      </p>
                    </div>
                    <div className="font-retro text-xs tracking-[0.24em] text-[#1affe4]/65">
                      {proposal ? `${resolvedCount}/60 RESOLVED` : "WAITING FOR PROMPT"}
                    </div>
                  </div>

                  {error ? (
                    <div className="mt-4 rounded-xl border border-red-400/20 bg-red-500/10 px-4 py-3 font-mono text-xs uppercase tracking-[0.14em] text-red-200">
                      {error}
                    </div>
                  ) : null}

                  {activeJob ? (
                    <div className="mt-4 rounded-xl border border-[#ff77c2]/20 bg-[#200815]/70 px-4 py-3">
                      <p className="font-retro text-sm tracking-[0.18em] text-[#ffb6dd]">
                        BACKGROUND GENERATION IN PROGRESS
                      </p>
                      <button
                        onClick={() => navigate(`/auto-generate/progress/${activeJob.jobId}`)}
                        className="crt-action retro-button-secondary mt-3 inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em]"
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
                          <label className="mb-2 block font-retro text-sm tracking-[0.18em] text-[#91fff2]">
                            PROJECT NAME
                          </label>
                          <input
                            value={projectName}
                            onChange={(e) => setProjectName(e.target.value)}
                            className="retro-input w-full rounded-xl px-4 py-3 font-mono text-sm tracking-[0.12em]"
                            placeholder="AI Power Hour"
                          />
                        </div>
                        <button
                          onClick={handleApprove}
                          disabled={approving || proposal.unresolved_count > 0}
                          className="crt-action retro-button-primary inline-flex items-center gap-3 rounded-xl px-5 py-3 font-retro text-base tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                          <span className="crt-action__label" data-text="APPROVE & CREATE PROJECT">
                            APPROVE & CREATE PROJECT
                          </span>
                        </button>
                      </div>

                      <div className="mt-5 flex-1 space-y-3 overflow-y-auto pr-1">
                        {proposal.items.map((item) => (
                          <div
                            key={`${proposal.proposal_id}-${item.slot_index}`}
                            className="retro-project-card rounded-[20px] p-4"
                          >
                            <div className="relative z-10 flex flex-col gap-4 lg:grid lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center">
                              <div className="flex min-w-0 items-center gap-4">
                                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#1affe4]/12 bg-[#08131a] font-retro text-xs tracking-[0.18em] text-[#91fff2]/70">
                                  {item.slot_index + 1}
                                </div>
                                {item.thumbnail ? (
                                  <img
                                    src={item.thumbnail}
                                    alt={item.title || item.requested_title}
                                    className="h-16 w-28 shrink-0 rounded-lg object-cover ring-1 ring-[#1affe4]/10"
                                  />
                                ) : (
                                  <div className="flex h-16 w-28 shrink-0 items-center justify-center rounded-lg bg-[#08131a] font-retro text-xs tracking-[0.18em] text-[#ff77c2]/60">
                                    PENDING
                                  </div>
                                )}
                              </div>
                              <div className="min-w-0 overflow-hidden">
                                <div className="flex min-w-0 flex-wrap items-center gap-2">
                                  <p className="min-w-0 max-w-full truncate font-retro text-base tracking-[0.12em] text-[#ffb6dd]">
                                    {item.title || item.requested_title}
                                  </p>
                                  {item.resolution_source ? (
                                    <span className="shrink-0 rounded-full border border-[#1affe4]/14 bg-[#08141b] px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-[#91fff2]/70">
                                      {formatSearchSourceLabel(item.resolution_source)}
                                    </span>
                                  ) : null}
                                </div>
                                <p className="mt-1 truncate font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/55">
                                  {(item.artist || item.requested_artist || "Unresolved")} {item.duration ? `· ${item.duration}` : ""}
                                </p>
                                {item.reason ? (
                                  <p className="mt-2 truncate font-mono text-xs uppercase tracking-[0.12em] text-[#91fff2]/35">
                                    {item.reason}
                                  </p>
                                ) : null}
                                {item.status !== "resolved" ? (
                                  <p className="mt-2 font-retro text-xs tracking-[0.16em] text-red-300">
                                    This slot is unresolved. Replace it or regenerate the full playlist.
                                  </p>
                                ) : null}
                              </div>
                              <button
                                onClick={() => handleReplace(item.slot_index)}
                                disabled={replacingSlots[item.slot_index] || generating || approving}
                                className="crt-action retro-button-secondary inline-flex shrink-0 self-start items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40 lg:self-auto lg:justify-self-end"
                              >
                                {replacingSlots[item.slot_index] ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <RefreshCcw className="h-3.5 w-3.5" />
                                )}
                                <span className="crt-action__label" data-text="REPLACE">
                                  REPLACE
                                </span>
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex min-h-[420px] flex-1 flex-col items-center justify-center px-6 text-center">
                      {generating ? (
                        <>
                          <Loader2 className="h-10 w-10 animate-spin text-[#ff77c2]" />
                          <p className="mt-4 font-retro text-2xl tracking-[0.18em] text-[#91fff2]">
                            GENERATING PLAYLIST...
                          </p>
                          <p className="mt-3 max-w-md font-mono text-xs uppercase tracking-[0.16em] text-[#91fff2]/40">
                            The AI is planning songs and the app is resolving them to real music videos.
                          </p>
                        </>
                      ) : (
                        <>
                          <Wand2 className="h-10 w-10 text-[#ff77c2]/70" />
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
          </div>
        </div>
      </main>
    </div>
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
