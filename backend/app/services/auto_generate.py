"""AI-powered playlist planning and auto-trim processing."""

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass, field, replace as dc_replace
from datetime import datetime, timedelta
from typing import Iterable
from uuid import uuid4

from openai import AsyncOpenAI

from app.api.clip_utils import remove_clip_analysis, save_clip_analysis
from app.core.config import settings
from app.core.security import public_render_url, resolve_managed_path, unlink_managed_file
from app.models.schemas import AiSessionState, AutoGenerateProposalItem, SearchResult
from app.services.audio_analysis import analyze_audio
from app.services.youtube import (
    _meaningful_terms,
    download_video,
    lookup_video,
    parse_youtube_id,
    search_youtube,
)

logger = logging.getLogger(__name__)

PROPOSAL_SIZE = 60
PLANNER_TARGET_COUNT = 80
PROPOSAL_TTL = timedelta(hours=2)
MAX_PLANNING_ATTEMPTS = 4
MAX_REPLACEMENT_ATTEMPTS = 3
GLOBAL_AUTO_PROCESS_SEMAPHORE = asyncio.Semaphore(1)
_AUTO_PROCESS_TASKS: set[asyncio.Task] = set()
AUTO_PROCESS_FAILURE_MESSAGE = "Automatic clip processing failed."
AUTO_RENDER_FAILURE_MESSAGE = "Automatic final render failed."
NOT_ENOUGH_FOOTAGE_MESSAGE = "The compilation did not have enough distinct footage for this part."
# A download that fails because the network is down (e.g. Docker's DNS dropping out) is
# retried after these waits (about 15 minutes in all) instead of failing the clip at once.
NETWORK_RETRY_DELAYS = (15, 30, 60, 120, 240, 480)
_NETWORK_ERROR_MARKERS = (
    "name resolution",
    "name or service not known",
    "nodename nor servname",
    "network is unreachable",
    "connection refused",
    "connection reset",
    "timed out",
    "unable to download webpage",
    "unable to download api page",
    "transporterror",
)
# The auto-render only runs when at least this share of the playlist is ready, so an outage
# that wipes out most downloads doesn't get rendered as a short "finished" power hour.
MIN_READY_FRACTION_TO_RENDER = 0.8

# Compilations: one long video can fill several slots, downloaded and analyzed once.
MAX_COMPILATION_SEGMENTS = 5
SECONDS_PER_SEGMENT = 90          # a source needs this much runtime per clip taken from it
MAX_SINGLE_CLIP_SECONDS = 20 * 60  # longer videos are not downloaded for just one clip...
FALLBACK_LONG_SEGMENTS = 3        # ...unless nothing shorter matched; then take this many parts
MAX_SOURCE_SECONDS = 90 * 60       # never download anything longer than this

# Proposal speed: searches run a few at a time, and a slot the review rejects first tries the
# other results of its own search (re-reviewed) before the planner is asked for new ideas.
SEARCH_CONCURRENCY = 4
REVIEW_FALLBACK_ROUNDS = 2
# Playlist revisions: REVISE comments kept to steer later swaps, and the per-slot note limit.
MAX_PROPOSAL_NOTES = 10
NOTE_MAX_CHARS = 300


@dataclass
class PlannedSong:
    title: str
    artist: str
    reason: str = ""
    kind: str = "song"  # "song" (music search) or "clip" (plain YouTube search)
    segments: int = 1   # >1: a compilation video the AI wants several clips from
    query: str = ""     # clips: the planner's short YouTube search phrase (else artist - title)
    exact: bool = False  # the user named this exact entry, so the off-topic review is skipped


@dataclass
class StoredProposal:
    proposal_id: str
    prompt: str
    normalized_prompt: str
    items: list[AutoGenerateProposalItem]
    expires_at: datetime
    mode: str = "music"  # "music" | "videos" | "mixed"
    created_at: datetime = field(default_factory=datetime.utcnow)
    # The user's REVISE comments, oldest first; they steer every later swap too.
    notes: list[str] = field(default_factory=list)
    # (items, notes) from before the latest REVISE, for one-step UNDO.
    undo: tuple[list[AutoGenerateProposalItem], list[str]] | None = None


@dataclass
class AutoGenerateJob:
    job_id: str
    project_id: int
    total_clips: int
    phase: str = "queued"
    progress: float = 0.0
    processed_clips: int = 0
    current_step: str = "Preparing downloads"
    current_title: str = ""
    current_artist: str = ""
    render_id: int | None = None
    output_path: str = ""
    error_message: str = ""
    gpu_active: bool = False
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ProposalJob:
    job_id: str
    prompt: str
    status: str = "pending"   # pending | complete | error
    proposal_id: str = ""
    error_message: str = ""
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)


class ProposalStore:
    """In-memory ephemeral proposal storage."""

    def __init__(self) -> None:
        self._proposals: dict[str, StoredProposal] = {}
        self._lock = asyncio.Lock()

    async def save(self, proposal: StoredProposal) -> StoredProposal:
        async with self._lock:
            self._cleanup_locked()
            self._proposals[proposal.proposal_id] = proposal
            return proposal

    async def get(self, proposal_id: str) -> StoredProposal | None:
        async with self._lock:
            self._cleanup_locked()
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return None
            proposal.expires_at = datetime.utcnow() + PROPOSAL_TTL
            return proposal

    async def replace_item(
        self,
        proposal_id: str,
        slot_index: int,
        item: AutoGenerateProposalItem,
    ) -> StoredProposal | None:
        async with self._lock:
            self._cleanup_locked()
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return None
            # Locked while the swap ran (e.g. from the other device): the lock wins.
            if not proposal.items[slot_index].locked:
                proposal.items[slot_index] = item.model_copy(update={"locked": False, "revised": False})
                proposal.items = _label_segments(proposal.items)
            proposal.expires_at = datetime.utcnow() + PROPOSAL_TTL
            return proposal

    async def set_locked(self, proposal_id: str, slot_index: int, locked: bool) -> StoredProposal | None:
        async with self._lock:
            self._cleanup_locked()
            proposal = self._proposals.get(proposal_id)
            if not proposal or not 0 <= slot_index < len(proposal.items):
                return None
            proposal.items[slot_index] = proposal.items[slot_index].model_copy(update={"locked": locked})
            proposal.expires_at = datetime.utcnow() + PROPOSAL_TTL
            return proposal

    async def apply_revision(
        self, proposal_id: str, changes: dict[int, AutoGenerateProposalItem], comment: str
    ) -> StoredProposal | None:
        """Swap in a REVISE's slots (never a slot locked meanwhile), keep the comment, and
        remember the list from before so UNDO can restore it."""
        async with self._lock:
            self._cleanup_locked()
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return None
            proposal.undo = ([item.model_copy() for item in proposal.items], list(proposal.notes))
            items = []
            for item in proposal.items:
                new = changes.get(item.slot_index)
                if new is not None and not item.locked:
                    items.append(new.model_copy(update={
                        "slot_index": item.slot_index, "locked": False, "revised": True,
                    }))
                else:
                    items.append(item.model_copy(update={"revised": False}))
            proposal.items = _label_segments(items)
            proposal.notes = (proposal.notes + [comment])[-MAX_PROPOSAL_NOTES:]
            proposal.expires_at = datetime.utcnow() + PROPOSAL_TTL
            return proposal

    async def undo_revision(self, proposal_id: str) -> StoredProposal | None:
        """Restore the list from before the latest REVISE (keeping the current locks)."""
        async with self._lock:
            self._cleanup_locked()
            proposal = self._proposals.get(proposal_id)
            if not proposal or proposal.undo is None:
                return None
            items, notes = proposal.undo
            locks = {item.slot_index: item.locked for item in proposal.items}
            proposal.items = _label_segments([
                item.model_copy(update={"locked": locks.get(item.slot_index, False), "revised": False})
                for item in items
            ])
            proposal.notes = notes
            proposal.undo = None
            proposal.expires_at = datetime.utcnow() + PROPOSAL_TTL
            return proposal

    def _cleanup_locked(self) -> None:
        now = datetime.utcnow()
        expired = [proposal_id for proposal_id, proposal in self._proposals.items() if proposal.expires_at <= now]
        for expired_proposal_id in expired:
            self._proposals.pop(expired_proposal_id, None)


proposal_store = ProposalStore()


class AutoGenerateJobStore:
    """In-memory progress tracking for approved AI generation jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, AutoGenerateJob] = {}
        self._lock = asyncio.Lock()

    async def save(self, job: AutoGenerateJob) -> AutoGenerateJob:
        async with self._lock:
            self._cleanup_locked()
            self._jobs[job.job_id] = job
            return job

    async def get(self, job_id: str) -> AutoGenerateJob | None:
        async with self._lock:
            self._cleanup_locked()
            return self._jobs.get(job_id)

    async def update(self, job_id: str, **changes) -> AutoGenerateJob | None:
        async with self._lock:
            self._cleanup_locked()
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = datetime.utcnow()
            return job

    async def active(self) -> AutoGenerateJob | None:
        """The most recently updated job that is still running (any device may have started it)."""
        async with self._lock:
            self._cleanup_locked()
            running = [job for job in self._jobs.values() if job.phase not in ("complete", "error", "review")]
            return max(running, key=lambda job: job.updated_at, default=None)

    def _cleanup_locked(self) -> None:
        now = datetime.utcnow()
        ttl = timedelta(hours=12)
        expired = [job_id for job_id, job in self._jobs.items() if job.updated_at + ttl <= now]
        for expired_job_id in expired:
            self._jobs.pop(expired_job_id, None)


job_store = AutoGenerateJobStore()


class ProposalJobStore:
    """In-memory progress tracking for pending proposal generation jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, ProposalJob] = {}
        self._lock = asyncio.Lock()

    async def save(self, job: ProposalJob) -> ProposalJob:
        async with self._lock:
            self._cleanup_locked()
            self._jobs[job.job_id] = job
            return job

    async def get(self, job_id: str) -> ProposalJob | None:
        async with self._lock:
            self._cleanup_locked()
            return self._jobs.get(job_id)

    async def update(self, job_id: str, **changes) -> ProposalJob | None:
        async with self._lock:
            self._cleanup_locked()
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = datetime.utcnow()
            return job

    def _cleanup_locked(self) -> None:
        now = datetime.utcnow()
        ttl = timedelta(hours=3)
        expired = [job_id for job_id, job in self._jobs.items() if job.updated_at + ttl <= now]
        for expired_job_id in expired:
            self._jobs.pop(expired_job_id, None)


proposal_job_store = ProposalJobStore()


class AiSessionStore:
    """The AI generator's in-progress draft (prompt, proposal, transition settings).

    In memory like proposals: a backend restart loses both together, so the draft can never
    point at a proposal that survived without it. Writes bump ``version`` so devices can
    tell their copy is stale; the last write wins (one person, two screens).
    """

    def __init__(self) -> None:
        self.state = AiSessionState()
        self.version = 0
        self.updated_at = datetime.utcnow()
        self._lock = asyncio.Lock()

    async def get(self) -> tuple[AiSessionState, int, datetime]:
        async with self._lock:
            return self.state.model_copy(), self.version, self.updated_at

    async def put(self, state: AiSessionState) -> tuple[AiSessionState, int, datetime]:
        async with self._lock:
            self.state = state.model_copy()
            self.version += 1
            self.updated_at = datetime.utcnow()
            return self.state.model_copy(), self.version, self.updated_at

    async def reset(self) -> None:
        await self.put(AiSessionState())


ai_session_store = AiSessionStore()


def proposal_to_response(proposal: StoredProposal) -> dict:
    unresolved_count = sum(1 for item in proposal.items if item.status != "resolved")
    return {
        "proposal_id": proposal.proposal_id,
        "normalized_prompt": proposal.normalized_prompt,
        "mode": proposal.mode,
        "items": proposal.items,
        "unresolved_count": unresolved_count,
        "expires_at": proposal.expires_at,
        "notes": list(proposal.notes),
        "can_undo": proposal.undo is not None,
    }


def job_to_response(job: AutoGenerateJob) -> dict:
    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "phase": job.phase,
        "progress": job.progress,
        "total_clips": job.total_clips,
        "processed_clips": job.processed_clips,
        "current_step": job.current_step,
        "current_title": job.current_title,
        "current_artist": job.current_artist,
        "render_id": job.render_id,
        "output_path": public_render_url(job.output_path) if job.output_path else "",
        "error_message": job.error_message,
        "gpu_active": job.gpu_active,
        "updated_at": job.updated_at,
    }


async def create_playlist_proposal(prompt: str, mode: str = "music") -> StoredProposal:
    """Create an ephemeral AI proposal and resolve it to YouTube-backed tracks."""
    normalized_prompt = " ".join(prompt.split())
    items = await _build_resolved_items(normalized_prompt, mode=mode)
    proposal = StoredProposal(
        proposal_id=uuid4().hex,
        prompt=prompt,
        normalized_prompt=normalized_prompt,
        items=items,
        expires_at=datetime.utcnow() + PROPOSAL_TTL,
        mode=mode,
    )
    await proposal_store.save(proposal)
    return proposal


async def start_proposal_job(prompt: str, mode: str = "music") -> ProposalJob:
    """Kick off create_playlist_proposal as a background task and return a job immediately."""
    job = ProposalJob(job_id=uuid4().hex, prompt=prompt)
    await proposal_job_store.save(job)

    async def _run() -> None:
        try:
            proposal = await create_playlist_proposal(prompt, mode=mode)
            await proposal_job_store.update(job.job_id, status="complete", proposal_id=proposal.proposal_id)
        except Exception as exc:
            logger.error("Proposal job %s failed: %s", job.job_id, exc)
            await proposal_job_store.update(job.job_id, status="error", error_message="AI playlist generation failed.")

    task = asyncio.create_task(_run())
    _AUTO_PROCESS_TASKS.add(task)
    task.add_done_callback(_AUTO_PROCESS_TASKS.discard)
    return job


async def start_replace_job(proposal_id: str, slot_index: int, note: str = "") -> ProposalJob:
    """Kick off replace_playlist_item as a background task and return a job immediately."""
    job = ProposalJob(job_id=uuid4().hex, prompt=f"replace:{proposal_id}:{slot_index}")
    await proposal_job_store.save(job)

    async def _run() -> None:
        try:
            proposal = await proposal_store.get(proposal_id)
            if not proposal:
                await proposal_job_store.update(job.job_id, status="error", error_message="Proposal not found or expired.")
                return
            item = await replace_playlist_item(proposal, slot_index, note=note)
            updated = await proposal_store.replace_item(proposal_id, slot_index, item)
            if not updated:
                await proposal_job_store.update(job.job_id, status="error", error_message="Proposal not found or expired.")
                return
            await proposal_job_store.update(job.job_id, status="complete", proposal_id=proposal_id)
        except Exception as exc:
            logger.error("Replace job %s failed: %s", job.job_id, exc)
            await proposal_job_store.update(job.job_id, status="error", error_message="AI playlist generation failed.")

    task = asyncio.create_task(_run())
    _AUTO_PROCESS_TASKS.add(task)
    task.add_done_callback(_AUTO_PROCESS_TASKS.discard)
    return job


async def start_revise_job(proposal_id: str, comment: str) -> ProposalJob:
    """Kick off revise_playlist as a background task and return a job immediately."""
    job = ProposalJob(job_id=uuid4().hex, prompt=f"revise:{proposal_id}")
    await proposal_job_store.save(job)

    async def _run() -> None:
        try:
            proposal = await proposal_store.get(proposal_id)
            if not proposal:
                await proposal_job_store.update(job.job_id, status="error", error_message="Proposal not found or expired.")
                return
            changes = await revise_playlist(proposal, comment)
            updated = await proposal_store.apply_revision(proposal_id, changes, _clean_note(comment, 1000))
            if not updated:
                await proposal_job_store.update(job.job_id, status="error", error_message="Proposal not found or expired.")
                return
            await proposal_job_store.update(job.job_id, status="complete", proposal_id=proposal_id)
        except Exception as exc:
            logger.error("Revise job %s failed: %s", job.job_id, exc)
            await proposal_job_store.update(job.job_id, status="error", error_message="AI playlist revision failed.")

    task = asyncio.create_task(_run())
    _AUTO_PROCESS_TASKS.add(task)
    task.add_done_callback(_AUTO_PROCESS_TASKS.discard)
    return job


def proposal_job_to_response(job: ProposalJob, proposal: StoredProposal | None) -> dict:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "error_message": job.error_message,
        "proposal": proposal_to_response(proposal) if proposal else None,
        "updated_at": job.updated_at,
    }


async def replace_playlist_item(
    proposal: StoredProposal, slot_index: int, note: str = ""
) -> AutoGenerateProposalItem:
    """Replace a single slot while preserving theme and avoiding duplicates.

    ``note`` steers this one swap: a YouTube link is used as-is, an exact entry the AI
    recognises skips the off-topic review, and anything else is direction for the planner.
    Every swap also follows the proposal's REVISE comments.
    """
    existing_items = [item for item in proposal.items if item.slot_index != slot_index]
    excluded_songs = _song_keys_from_items(existing_items)
    excluded_ids = {item.youtube_id for item in existing_items if item.youtube_id}
    original = proposal.items[slot_index]
    # In mixed mode a slot keeps its own kind (a song is replaced by a song, a clip by a clip).
    slot_mode = _slot_mode(proposal.mode, original.kind)
    note = _clean_note(note)
    prompt = _steered_prompt(proposal)

    video_id = parse_youtube_id(note)
    if video_id:
        result = await lookup_video(video_id)
        if result:
            picked = PlannedSong(title=result.title, artist=result.artist, reason="Your pick", kind=original.kind)
            return _item_from_result(picked, result, slot_index)

    for _ in range(MAX_REPLACEMENT_ATTEMPTS):
        alternates = await _plan_replacements(
            prompt=prompt,
            original=original,
            exclude_song_keys=excluded_songs,
            count=8,
            mode=slot_mode,
            note=note,
        )
        # A replacement fills exactly one slot, so any compilation hint is ignored here.
        while alternates:
            replacement, _ = await _resolve_candidates_to_item(
                slot_index=slot_index,
                candidates=alternates,
                used_song_keys=excluded_songs,
                used_youtube_ids=excluded_ids,
            )
            if not replacement or replacement.status != "resolved":
                break
            first = alternates[0]
            exact = first.exact and _song_key(replacement.requested_artist, replacement.requested_title) == _song_key(first.artist, first.title)
            if exact or not await _review_results(prompt, [replacement]):
                return replacement
            # Off-prompt: never offer this video or idea again, then try the next alternate.
            excluded_ids.add(replacement.youtube_id)
            excluded_songs.add(_song_key(replacement.requested_artist, replacement.requested_title))

    return AutoGenerateProposalItem(
        slot_index=slot_index,
        requested_title=original.requested_title,
        requested_artist=original.requested_artist,
        title=original.title,
        artist=original.artist,
        thumbnail=original.thumbnail,
        duration=original.duration,
        youtube_id=original.youtube_id,
        resolution_source=original.resolution_source,
        reason=original.reason,
        status="unresolved",
        kind=original.kind,
    )


async def create_auto_generate_job(project_id: int, total_clips: int) -> AutoGenerateJob:
    job = AutoGenerateJob(
        job_id=uuid4().hex,
        project_id=project_id,
        total_clips=total_clips,
    )
    await job_store.save(job)
    return job


async def auto_process_clip(clip_id: int, job_id: str, clip_index: int, total_clips: int) -> bool:
    """Download, analyze, auto-select, trim, and discard full source for one clip."""
    return await auto_process_source([clip_id], job_id, clip_index, total_clips) == 1


async def auto_process_source(
    clip_ids: list[int], job_id: str, first_index: int, total_clips: int
) -> int:
    """Download one source video once and pre-select a range for each of ``clip_ids``.

    Nothing is trimmed: every clip keeps the full source with the AI's suggested range saved
    as an editable draft (plus its waveform/highlights), so the user reviews every pick
    before rendering. Several ids means a compilation: the parts share the one source file
    and each gets its own non-overlapping range. The source is deleted here only when no
    clip ended up using it. Returns how many clips became READY.
    """
    from app.core.database import async_session
    from app.models.schemas import ClipDB, ClipStatus
    from sqlalchemy import select

    async with GLOBAL_AUTO_PROCESS_SEMAPHORE:
        async with async_session() as db:
            result = await db.execute(select(ClipDB).where(ClipDB.id.in_(clip_ids)))
            by_id = {clip.id: clip for clip in result.scalars().all()}
            clips = [by_id[clip_id] for clip_id in clip_ids if clip_id in by_id]
            if not clips:
                await _mark_job_error(job_id, f"Clip {clip_ids[0]} could not be found")
                return 0

            lead = clips[0]
            count = len(clips)
            resolved_source = None
            ready = 0

            async def progress(index: int, step: str, step_progress: float) -> None:
                await _update_job_processing(
                    job_id=job_id,
                    processed_clips=first_index + index,
                    total_clips=total_clips,
                    clip_title=lead.source_title,
                    clip_artist=lead.source_artist,
                    step=step,
                    step_progress=step_progress,
                )

            try:
                source_note = f" ({count} clips from one video)" if count > 1 else ""
                await progress(0, f"Downloading source video{source_note}", 0.12)
                for clip in clips:
                    clip.status = ClipStatus.DOWNLOADING
                    clip.error_message = ""
                await db.commit()

                dl_result = await _download_with_network_retry(
                    lead.youtube_id,
                    file_stem=f"{lead.youtube_id}_{lead.id}",
                    on_wait=lambda delay: progress(
                        0, f"Network down, retrying download in {delay}s", 0.12
                    ),
                )
                resolved_source = resolve_managed_path(dl_result["file_path"], settings.media_dir)
                if not resolved_source or not resolved_source.exists():
                    raise RuntimeError("Download completed but no local media file was found")

                for clip in clips:
                    if dl_result.get("title"):
                        clip.source_title = dl_result["title"]
                    if dl_result.get("artist"):
                        clip.source_artist = dl_result["artist"]

                await progress(0, "Generating waveform analysis", 0.5)
                for clip in clips:
                    clip.status = ClipStatus.ANALYZING
                await db.commit()

                analysis = await analyze_audio(str(resolved_source), segment_count=count)
                if not analysis.get("waveform") or float(analysis.get("duration", 0) or 0) <= 0:
                    raise RuntimeError("Audio analysis did not produce waveform data")

                if count == 1:
                    ranges = [(
                        float(analysis.get("suggested_start", 0) or 0),
                        float(analysis.get("suggested_end", 0) or 0),
                    )]
                else:
                    ranges = [
                        (float(seg["start"]), float(seg["end"]))
                        for seg in analysis.get("segments", [])
                    ]

                source_seconds = float(analysis.get("duration", 0) or 0)
                for index, clip in enumerate(clips):
                    if index >= len(ranges):
                        clip.status = ClipStatus.ERROR
                        clip.error_message = NOT_ENOUGH_FOOTAGE_MESSAGE
                        await db.commit()
                        await progress(index + 1, "Skipped: not enough distinct footage", 0.0)
                        continue
                    start, end = ranges[index]
                    if end <= start:
                        logger.error("AI analysis gave clip %s an empty range", clip.id)
                        clip.status = ClipStatus.ERROR
                        clip.error_message = AUTO_PROCESS_FAILURE_MESSAGE
                        await db.commit()
                        await progress(index + 1, "Skipped after processing error", 0.0)
                        continue

                    # The AI's pick becomes an editable draft on the full source; the review
                    # screen shows this clip's own range as its recommendation.
                    clip_analysis = dict(analysis)
                    clip_analysis["suggested_start"] = start
                    clip_analysis["suggested_end"] = end
                    if count > 1:
                        clip_analysis["highlights"] = [
                            {"start": start, "end": end, "score": 1.0, "label": f"AI pick (part {index + 1})"},
                            *[h for h in analysis.get("highlights", []) if h.get("end", 0) <= start or h.get("start", 0) >= end],
                        ]
                    save_clip_analysis(clip.id, clip_analysis)

                    clip.bpm = analysis.get("bpm")
                    clip.energy = analysis.get("energy")
                    clip.file_path = str(resolved_source)
                    clip.duration = source_seconds
                    clip.start_time = start
                    clip.end_time = end
                    clip.suggested_start = start
                    clip.status = ClipStatus.READY
                    clip.error_message = ""
                    await db.commit()
                    ready += 1
                    step = "AI pick saved for review" if count == 1 else f"Part {index + 1} of {count} saved for review"
                    await progress(index + 1, step, 0.0)
                return ready
            except Exception as exc:
                logger.error("Auto-processing failed for clips %s: %s", clip_ids, exc)
                for clip in clips:
                    if clip.status != ClipStatus.READY:
                        clip.status = ClipStatus.ERROR
                        clip.error_message = AUTO_PROCESS_FAILURE_MESSAGE
                await db.commit()
                await progress(count, "Skipped after processing error", 0.0)
                return ready
            finally:
                # The source stays for review unless no clip ended up using it.
                if resolved_source is not None and ready == 0:
                    unlink_managed_file(str(resolved_source), settings.media_dir)
                for clip in clips:
                    if clip.status != ClipStatus.READY:
                        remove_clip_analysis(clip.id)


def _is_network_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _NETWORK_ERROR_MARKERS)


async def _download_with_network_retry(youtube_id: str, file_stem: str, on_wait=None) -> dict:
    """download_video, but a network outage waits and retries instead of failing the clip."""
    for delay in (*NETWORK_RETRY_DELAYS, None):
        try:
            return await download_video(youtube_id, file_stem=file_stem)
        except Exception as exc:
            if delay is None or not _is_network_error(exc):
                raise
            logger.warning(
                "Download of %s hit a network error; retrying in %ss: %s",
                youtube_id, delay, str(exc).splitlines()[0][:200],
            )
            if on_wait is not None:
                await on_wait(delay)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


def _enough_ready_to_render(ready: int, total: int) -> bool:
    return total > 0 and ready / total >= MIN_READY_FRACTION_TO_RENDER


def _group_by_source(clips: Iterable[tuple[int, str]]) -> list[list[int]]:
    """Group (clip_id, youtube_id) pairs that share a video, in first-appearance order."""
    groups: dict[str, list[int]] = {}
    ordered: list[list[int]] = []
    for clip_id, youtube_id in clips:
        if not youtube_id:
            ordered.append([clip_id])
            continue
        if youtube_id not in groups:
            groups[youtube_id] = []
            ordered.append(groups[youtube_id])
        groups[youtube_id].append(clip_id)
    return ordered


@dataclass
class AiTransitionRequest:
    theme: str
    count: int
    sources: str = "both"
    prompt: str = ""  # the user's direction for the transitions
    drink_text: str | None = None  # the user's own call word (None: the AI picks)


async def _create_ai_transitions_step(job_id: str, project_id: int, request: AiTransitionRequest) -> None:
    """Build the AI's transition clips before rendering; falls back to the default card."""
    from app.core.database import async_session
    from app.services.ai_transitions import create_ai_transitions
    from app.services.changeover import ensure_default_changeover

    await job_store.update(
        job_id,
        phase="processing",
        progress=70.0,
        current_step="Creating transition clips",
        current_title="",
        current_artist="",
    )
    try:
        async with async_session() as db:
            ready = await create_ai_transitions(
                db, project_id, request.theme, request.count, request.sources,
                **({"transition_prompt": request.prompt} if request.prompt else {}),
                drink_text=request.drink_text,
            )
            if ready == 0:
                await ensure_default_changeover(db, project_id)
    except Exception as exc:
        logger.error("AI transition step failed for project %s: %s", project_id, exc)


def start_auto_process_queue(
    job_id: str,
    project_id: int,
    clip_ids: Iterable[int],
    transitions: AiTransitionRequest | None = None,
) -> asyncio.Task:
    """Start sequential processing for a newly approved AI playlist."""

    async def _run() -> None:
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.schemas import ClipDB

        clip_list = list(clip_ids)
        async with async_session() as db:
            rows = await db.execute(select(ClipDB.id, ClipDB.youtube_id).where(ClipDB.id.in_(clip_list)))
            youtube_ids = dict(rows.all())
        # Slots cut from the same (compilation) video share one download and one analysis.
        groups = _group_by_source((clip_id, youtube_ids.get(clip_id, "")) for clip_id in clip_list)

        ready_count = 0
        processed = 0
        for group in groups:
            ready_count += await auto_process_source(
                clip_ids=group,
                job_id=job_id,
                first_index=processed,
                total_clips=len(clip_list),
            )
            processed += len(group)

        if ready_count == 0:
            await _mark_job_error(job_id, "No clips finished processing, so there is nothing to review.")
            return

        if transitions:
            await _create_ai_transitions_step(job_id, project_id, transitions)

        # Every build stops here: the user checks each AI pick on the project page and
        # renders from there (nothing is trimmed or rendered automatically).
        failed = len(clip_list) - ready_count
        if _enough_ready_to_render(ready_count, len(clip_list)):
            step = "Ready for your review"
        else:
            step = f"Ready for your review ({failed} clips failed: replace them before rendering)"
        await job_store.update(
            job_id,
            phase="review",
            progress=100.0,
            processed_clips=len(clip_list),
            current_step=step,
            current_title="",
            current_artist="",
        )

    task = asyncio.create_task(_run())
    _AUTO_PROCESS_TASKS.add(task)
    task.add_done_callback(_AUTO_PROCESS_TASKS.discard)
    return task


@dataclass
class _BatchEntry:
    item: AutoGenerateProposalItem
    segments: int
    candidate: PlannedSong
    results: list[SearchResult]  # the candidate's whole search, for fallbacks after a rejection


async def _review_with_fallbacks(
    prompt: str, batch: list[_BatchEntry], used_youtube_ids: set[str]
) -> list[_BatchEntry]:
    """Review a batch; a rejected slot tries the next result from its own search first.

    Re-reviewing a few fallbacks costs one short AI call and no searches, which is far
    cheaper than another planning round. Returns the accepted entries.
    """
    accepted: list[_BatchEntry] = []
    pending = batch
    for attempt in range(REVIEW_FALLBACK_ROUNDS + 1):
        if not pending:
            break
        rejected = await _review_results(prompt, [entry.item for entry in pending])
        accepted.extend(entry for index, entry in enumerate(pending) if index not in rejected)
        if attempt == REVIEW_FALLBACK_ROUNDS:
            break
        retries = []
        for index in sorted(rejected):
            entry = pending[index]
            result, segments = _choose_result(entry.candidate, entry.results, used_youtube_ids)
            if result is None:
                continue
            used_youtube_ids.add(result.youtube_id)
            retries.append(_BatchEntry(
                _item_from_result(entry.candidate, result, entry.item.slot_index),
                segments, entry.candidate, entry.results,
            ))
        pending = retries
    return accepted


async def _build_resolved_items(prompt: str, mode: str = "music") -> list[AutoGenerateProposalItem]:
    used_song_keys: set[str] = set()
    used_youtube_ids: set[str] = set()
    resolved_items: list[AutoGenerateProposalItem] = []
    unresolved_candidates: list[PlannedSong] = []

    for _ in range(MAX_PLANNING_ATTEMPTS):
        if len(resolved_items) >= PROPOSAL_SIZE:
            break

        planned = await _plan_playlist(
            prompt=prompt,
            exclude_song_keys=used_song_keys | {_song_key(song.artist, song.title) for song in unresolved_candidates},
            target_count=PLANNER_TARGET_COUNT,
            mode=mode,
        )
        # Resolve the batch first, then let the AI review the real YouTube results in one call.
        batch: list[_BatchEntry] = []
        slots_pending = 0
        needed = PROPOSAL_SIZE - len(resolved_items)
        # Resolve a few spares so review rejections don't leave the playlist short. Each spare
        # costs a search, so the margin stays small.
        target = needed + max(2, needed // 5)
        fresh = [
            candidate for candidate in planned
            if _song_key(candidate.artist, candidate.title) not in used_song_keys
        ]
        start = 0
        while slots_pending < target and start < len(fresh):
            # Search about as many candidates as are still needed in parallel, then claim the
            # results in plan order so duplicates resolve the same way a one-by-one pass would.
            chunk = fresh[start:start + max(SEARCH_CONCURRENCY, target - slots_pending)]
            start += len(chunk)
            for candidate, results in zip(chunk, await _search_all(chunk)):
                if slots_pending >= target:
                    break
                key = _song_key(candidate.artist, candidate.title)
                if key in used_song_keys:
                    continue
                result, segments = _choose_result(candidate, results, used_youtube_ids)
                if not result:
                    unresolved_candidates.append(candidate)
                    continue
                batch.append(_BatchEntry(
                    _item_from_result(candidate, result, len(resolved_items)), segments, candidate, results
                ))
                slots_pending += segments
                # Claimed now so later candidates can't resolve to the same video; a rejected
                # video stays excluded too.
                used_song_keys.add(key)
                used_youtube_ids.add(result.youtube_id)

        accepted = await _review_with_fallbacks(prompt, batch, used_youtube_ids)
        for entry in accepted:
            # A compilation fills several slots, each a different part of the same video.
            for _ in range(min(entry.segments, PROPOSAL_SIZE - len(resolved_items))):
                resolved_items.append(entry.item.model_copy())

    combined = _space_artists(resolved_items)
    for candidate in unresolved_candidates:
        if len(combined) >= PROPOSAL_SIZE:
            break
        combined.append(
            AutoGenerateProposalItem(
                slot_index=len(combined),
                requested_title=candidate.title,
                requested_artist=candidate.artist,
                reason=candidate.reason,
                status="unresolved",
                kind=candidate.kind,
            )
        )

    while len(combined) < PROPOSAL_SIZE:
        slot_index = len(combined)
        combined.append(
            AutoGenerateProposalItem(
                slot_index=slot_index,
                requested_title=f"UNRESOLVED SLOT {slot_index + 1}",
                requested_artist="",
                status="unresolved",
                reason="Could not resolve this slot yet. Replace or regenerate.",
            )
        )

    return _label_segments([
        item.model_copy(update={"slot_index": index})
        for index, item in enumerate(combined[:PROPOSAL_SIZE])
    ])


def _label_segments(items: list[AutoGenerateProposalItem]) -> list[AutoGenerateProposalItem]:
    """Number the resolved slots that share a video (part 1 of 3, ...) in playlist order."""
    totals: dict[str, int] = {}
    for item in items:
        if item.status == "resolved" and item.youtube_id:
            totals[item.youtube_id] = totals.get(item.youtube_id, 0) + 1
    seen: dict[str, int] = {}
    labeled = []
    for item in items:
        if item.status == "resolved" and item.youtube_id:
            index = seen.get(item.youtube_id, 0)
            seen[item.youtube_id] = index + 1
            update = {"segment_index": index, "segment_count": totals[item.youtube_id]}
        else:
            update = {"segment_index": 0, "segment_count": 1}
        labeled.append(item.model_copy(update=update))
    return labeled


async def _resolve_candidates_to_item(
    slot_index: int,
    candidates: list[PlannedSong],
    used_song_keys: set[str],
    used_youtube_ids: set[str],
) -> tuple[AutoGenerateProposalItem | None, int]:
    """Resolve the first usable candidate. Returns ``(item, slots_it_should_fill)``."""
    for candidate in candidates:
        key = _song_key(candidate.artist, candidate.title)
        if not candidate.title or key in used_song_keys:
            continue
        result, segments = await _resolve_song(candidate, used_youtube_ids)
        if not result:
            continue
        return _item_from_result(candidate, result, slot_index), segments

    if candidates:
        fallback = candidates[0]
        return AutoGenerateProposalItem(
            slot_index=slot_index,
            requested_title=fallback.title,
            requested_artist=fallback.artist,
            reason=fallback.reason,
            status="unresolved",
            kind=fallback.kind,
        ), 1

    return None, 1


async def _resolve_song(
    candidate: PlannedSong, used_youtube_ids: set[str] | None = None
) -> tuple[SearchResult | None, int]:
    """Search for a candidate. Returns ``(result, slots_it_should_fill)``."""
    return _choose_result(candidate, await _search_candidate(candidate), used_youtube_ids or set())


async def _search_candidate(candidate: PlannedSong) -> list[SearchResult]:
    """One YouTube search for a candidate, keeping every usable result (best first)."""
    query = _search_query(candidate)
    results = await search_youtube(
        query,
        max_results=6,
        preferred_artists=[candidate.artist] if candidate.artist else None,
        music=candidate.kind == "song",
    )
    results = [result for result in results if result.youtube_id]
    if candidate.kind == "song":
        return results
    # Plain searches happily return trending videos that share no words with the request.
    return [result for result in results if _shares_query_terms(result, query)]


def _choose_result(
    candidate: PlannedSong, results: list[SearchResult], used_youtube_ids: set[str]
) -> tuple[SearchResult | None, int]:
    """Pick the best not-yet-used result. Returns ``(result, slots_it_should_fill)``."""
    results = [result for result in results if result.youtube_id not in used_youtube_ids]
    if candidate.kind == "song":
        return (results[0], 1) if results else (None, 1)
    return _pick_clip_source(results, candidate.segments)


async def _search_all(candidates: list[PlannedSong]) -> list[list[SearchResult]]:
    """Search several candidates at once (SEARCH_CONCURRENCY at a time); a failure is no results."""
    limit = asyncio.Semaphore(SEARCH_CONCURRENCY)

    async def one(candidate: PlannedSong) -> list[SearchResult]:
        async with limit:
            try:
                return await _search_candidate(candidate)
            except Exception as exc:
                logger.warning("Search failed for %r: %s", candidate.title, exc)
                return []

    return list(await asyncio.gather(*(one(candidate) for candidate in candidates)))


def _item_from_result(
    candidate: PlannedSong, result: SearchResult, slot_index: int
) -> AutoGenerateProposalItem:
    return AutoGenerateProposalItem(
        slot_index=slot_index,
        requested_title=candidate.title,
        requested_artist=candidate.artist,
        youtube_id=result.youtube_id,
        title=result.title,
        artist=result.artist,
        thumbnail=result.thumbnail,
        duration=result.duration,
        resolution_source=result.search_source,
        reason=candidate.reason,
        status="resolved",
        kind=candidate.kind,
    )


# Fraction of the request's meaningful words a clip result must contain (title + channel).
MIN_TERM_OVERLAP = 0.25


def _shares_query_terms(result: SearchResult, query: str) -> bool:
    terms = _meaningful_terms(query)
    if not terms:
        return True
    haystack = f" {_normalize_text(result.title)} {_normalize_text(result.artist)} "
    hits = sum(1 for term in terms if f" {term} " in haystack)
    return hits >= max(1, math.ceil(len(terms) * MIN_TERM_OVERLAP))


REVIEW_SYSTEM_PROMPT = (
    "You check YouTube search results for a power hour playlist against the user's request. "
    "For each numbered result you get its kind, real YouTube title, channel, and length. "
    "Reject a result when its title or channel shows it does not fit the request: off-topic content "
    "(news, crime, bodycam, unrelated vlogs), a different show, franchise, or competition than the one "
    "requested (even with shared judges or hosts), a person, era, or season outside what the request "
    "names, or reaction/commentary videos unless the request wants them. Do not reject only because "
    "a detail is missing from the title; reject on evidence. "
    'Return only strict JSON shaped as {"reject": [numbers]} (an empty list when all fit).'
)


async def _review_results(prompt: str, items: list[AutoGenerateProposalItem]) -> set[int]:
    """Ask the AI which resolved results don't fit the prompt. Returns indices into ``items``.

    Fails open: if the review call errors or returns junk, nothing is rejected, so a flaky
    review never blocks a playlist.
    """
    if not items:
        return set()
    listing = "\n".join(
        f"{index + 1}. [{item.kind}] {item.title or item.requested_title} | channel: {item.artist or '?'}"
        f" | length: {item.duration or '?'}"
        for index, item in enumerate(items)
    )
    try:
        client = _get_openai_client()
        response = await client.chat.completions.create(
            model=settings.openai_review_model or settings.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": f"Request: {prompt}\n\nResults:\n{listing}"},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        raw = payload.get("reject", []) if isinstance(payload, dict) else []
    except Exception as exc:
        logger.warning("Result review failed; keeping all %d results: %s", len(items), exc)
        return set()
    rejected = set()
    for number in raw if isinstance(raw, list) else []:
        try:
            index = int(number) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(items):
            rejected.add(index)
    if rejected:
        logger.info(
            "Review rejected %d of %d results: %s",
            len(rejected), len(items), [items[i].title for i in sorted(rejected)],
        )
    return rejected


def _pick_clip_source(results: list[SearchResult], wanted: int) -> tuple[SearchResult | None, int]:
    """Choose a non-music video by length, so long downloads are only made when they pay off.

    A single-clip slot prefers videos under MAX_SINGLE_CLIP_SECONDS; a compilation request
    needs SECONDS_PER_SEGMENT of runtime per part. If the only match is long, it is used for
    a few parts rather than just one. Nothing over MAX_SOURCE_SECONDS is ever picked.
    """
    wanted = max(1, min(wanted, MAX_COMPILATION_SEGMENTS))
    usable = []
    for result in results:
        seconds = _duration_seconds(result.duration)
        if seconds is not None and seconds > MAX_SOURCE_SECONDS:
            continue
        usable.append((result, seconds))

    def parts_from(seconds: int | None, cap: int) -> int:
        if seconds is None:
            return 1
        return max(1, min(cap, seconds // SECONDS_PER_SEGMENT))

    if wanted > 1:
        for result, seconds in usable:
            if seconds is not None and seconds >= 2 * SECONDS_PER_SEGMENT:
                return result, parts_from(seconds, wanted)
    for result, seconds in usable:
        if seconds is None or seconds <= MAX_SINGLE_CLIP_SECONDS:
            return result, 1
    if usable:
        result, seconds = usable[0]
        return result, parts_from(seconds, FALLBACK_LONG_SEGMENTS)
    return None, 1


def _duration_seconds(duration: str) -> int | None:
    """'1:02:03' / '4:33' -> seconds; None when unknown."""
    parts = (duration or "").strip().split(":")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


async def _plan_playlist(
    prompt: str,
    exclude_song_keys: set[str],
    target_count: int,
    mode: str = "music",
) -> list[PlannedSong]:
    client = _get_openai_client()
    exclusion_text = _format_exclusions(exclude_song_keys)
    if mode == "mixed":
        system_content = (
            "You are a supervisor building a 60-item power hour playlist that mixes songs with ordinary YouTube clips "
            "(movie scenes, comedy bits, sports moments, speeches, etc.). "
            "Return only strict JSON shaped as {\"tracks\": [{\"kind\": \"song\" | \"clip\", \"title\": string, \"artist\": string, \"query\": string, \"reason\": string}]}. "
            "For kind \"song\", use the song title and artist and favor recognizable songs with likely official music videos "
            "(avoid live versions, lyric videos, karaoke, remixes unless requested); \"query\" may be blank. "
            "For kind \"clip\", use \"title\" for the video's subject/title and \"artist\" for the channel or creator if known (blank is fine). "
            + _CLIP_QUERY_GUIDANCE
            + "Follow the user's prompt for the balance and placement of songs versus clips; if it doesn't say, mostly songs with some clips mixed in. "
            "Avoid duplicates, and do not cluster the same artist/creator repeatedly in sequence. "
            + _COMPILATION_GUIDANCE
        )
    elif mode == "music":
        system_content = (
            "You are a music supervisor building a 60-song power hour playlist. "
            "Return only strict JSON shaped as {\"tracks\": [{\"title\": string, \"artist\": string, \"reason\": string}]}. "
            "Favor recognizable songs with likely official music videos. Avoid duplicates, live versions, lyric videos, karaoke, remixes unless requested. "
            "Do not cluster the same artist repeatedly in sequence unless the user explicitly asks for a narrow artist-focused mix."
        )
    else:
        system_content = (
            "You are a video supervisor building a 60-clip power hour playlist from ordinary YouTube videos "
            "(not necessarily music videos). "
            "Return only strict JSON shaped as {\"tracks\": [{\"title\": string, \"artist\": string, \"query\": string, \"reason\": string}]}, "
            "using \"title\" for the video's subject/title and \"artist\" for the channel or creator if known (blank is fine). "
            + _CLIP_QUERY_GUIDANCE
            + "Favor findable, recognizable videos that match the prompt. Avoid duplicates or near-identical clips. "
            + _COMPILATION_GUIDANCE
        )
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": system_content,
            },
            {
                "role": "user",
                "content": (
                    f"Build {target_count} candidate {_MODE_NOUN[mode]} for this power hour prompt: {prompt}\n"
                    "Keep variety unless the prompt explicitly asks for something narrow.\n"
                    "Stay strictly inside any show, franchise, people, era, or seasons the prompt names: "
                    "related but different shows or spin-offs do not count.\n"
                    "Make each title specific enough to search for (include the show or source name when there is one).\n"
                    "Mix sources across the running order so the same artist/creator does not play back to back when possible.\n"
                    f"Avoid these already used entries: {exclusion_text}."
                ),
            },
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return _dedupe_planned_songs(payload.get("tracks", []), mode)


async def _plan_replacements(
    prompt: str,
    original: AutoGenerateProposalItem,
    exclude_song_keys: set[str],
    count: int,
    mode: str = "music",
    note: str = "",
) -> list[PlannedSong]:
    # Replacements are always single-kind: in mixed mode the caller passes the slot's own kind.
    music = mode == "music"
    note_text = (
        f"\nThe user's note for this slot (follow it): {note}\n"
        "If the note names one specific song or video, make that exact entry the first track and set "
        "\"exact\": true at the top level; otherwise set \"exact\": false."
        if note else ""
    )
    client = _get_openai_client()
    exclusion_text = _format_exclusions(exclude_song_keys)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You return only strict JSON shaped as {\"tracks\": [{\"title\": string, \"artist\": string, \"query\": string, \"reason\": string}]}. "
                    + (
                        "Suggest replacements that preserve the same theme but are distinct songs; \"query\" may be blank."
                        if music
                        else "Suggest replacement YouTube videos (not necessarily music videos) that preserve the same theme but are distinct clips. "
                        + _CLIP_QUERY_GUIDANCE
                    )
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Prompt: {prompt}\n"
                    f"Replace this song with {count} alternatives: {original.requested_artist} - {original.requested_title}\n"
                    f"Avoid these already selected songs: {exclusion_text}."
                    + note_text
                ),
            },
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    songs = _dedupe_planned_songs(payload.get("tracks", []), mode)
    if note and songs and payload.get("exact") is True:
        songs[0].exact = True
    return songs


REVISE_SYSTEM_PROMPT = (
    "You revise an existing 60-slot power hour playlist from the user's comment. You get the original "
    "request, earlier comments, and the numbered current list (kind, title, channel). Change only the "
    "slots the comment calls for, keep everything else, and never change a slot marked LOCKED. The "
    "playlist length is fixed: you swap what fills a slot, you never add or remove slots. Each change "
    "replaces whole slots with a new entry that is not already in the list. "
    "Return only strict JSON shaped as {\"changes\": [{\"slots\": [numbers], \"kind\": \"song\" | \"clip\", "
    "\"title\": string, \"artist\": string, \"query\": string, \"reason\": string}]} "
    "(an empty list when nothing should change). A change normally has one slot. Only a compilation "
    "clip (a real, popular 'best of' / 'funniest moments' upload) may list 2-"
    f"{MAX_COMPILATION_SEGMENTS} slots; it fills each with a different 60-second part. "
)


def _clean_note(text: str, limit: int = NOTE_MAX_CHARS) -> str:
    return " ".join((text or "").split())[:limit]


def _steered_prompt(proposal: StoredProposal, extra: str = "") -> str:
    """The original request plus the user's REVISE comments, which every later pick follows."""
    notes = [note for note in [*proposal.notes, extra] if note]
    if not notes:
        return proposal.normalized_prompt
    listed = "; ".join(f"{i + 1}) {note}" for i, note in enumerate(notes))
    return f"{proposal.normalized_prompt}\nUser revisions (later ones win): {listed}"


def _revision_listing(proposal: StoredProposal) -> str:
    lines = []
    for item in proposal.items:
        flags = " | LOCKED" if item.locked else ""
        if item.status != "resolved":
            flags += " | UNRESOLVED"
        lines.append(
            f"{item.slot_index + 1}. [{item.kind}] {item.title or item.requested_title}"
            f" | channel: {item.artist or '?'}{flags}"
        )
    return "\n".join(lines)


async def _plan_revision(proposal: StoredProposal, comment: str) -> list[tuple[list[int], PlannedSong]]:
    """Ask the AI which slots the comment changes. Returns ``(slot indexes, new entry)`` pairs,
    validated: real unlocked slots only, each slot at most once, kinds the mode allows."""
    mode_rule = {
        "music": "Every change is kind \"song\". ",
        "videos": "Every change is kind \"clip\" (ordinary YouTube videos). ",
        "mixed": "Pick song or clip per change as the comment needs. ",
    }[proposal.mode]
    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": REVISE_SYSTEM_PROMPT + mode_rule + _CLIP_QUERY_GUIDANCE},
            {
                "role": "user",
                "content": (
                    f"Original request: {proposal.normalized_prompt}\n"
                    f"Earlier comments: {'; '.join(proposal.notes) or 'none'}\n\n"
                    f"Current playlist:\n{_revision_listing(proposal)}\n\n"
                    f"The user's comment: {comment}"
                ),
            },
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    raw_changes = payload.get("changes", []) if isinstance(payload, dict) else []
    taken: set[int] = set()
    planned: list[tuple[list[int], PlannedSong]] = []
    for raw in raw_changes if isinstance(raw_changes, list) else []:
        if not isinstance(raw, dict):
            continue
        songs = _dedupe_planned_songs([raw], proposal.mode)
        if not songs:
            continue
        song = songs[0]
        raw_slots = raw.get("slots")
        slots: list[int] = []
        for number in raw_slots if isinstance(raw_slots, list) else [raw_slots]:
            try:
                index = int(number) - 1
            except (TypeError, ValueError):
                continue
            if (
                0 <= index < len(proposal.items) and index not in taken and index not in slots
                and not proposal.items[index].locked
            ):
                slots.append(index)
        slots = slots[:MAX_COMPILATION_SEGMENTS if song.kind == "clip" else 1]
        if not slots:
            continue
        taken.update(slots)
        song.segments = len(slots)
        planned.append((slots, song))
    return planned


async def revise_playlist(proposal: StoredProposal, comment: str) -> dict[int, AutoGenerateProposalItem]:
    """Work out a REVISE: returns the new item for each slot that changes.

    The AI picks the slots and new entries in one call; only those are searched and reviewed
    (against the request plus every comment). A slot whose new entry can't be found or fails
    review gets an ordinary steered swap; if that fails too the slot keeps what it had.
    """
    comment = _clean_note(comment, 1000)
    prompt = _steered_prompt(proposal, comment)
    plan = await _plan_revision(proposal, comment)
    if not plan:
        return {}
    changing = {slot for slots, _ in plan for slot in slots}
    kept = [item for item in proposal.items if item.slot_index not in changing]
    used_ids = {item.youtube_id for item in kept if item.youtube_id}
    used_keys = _song_keys_from_items(kept)

    batch: list[_BatchEntry] = []
    slots_for: dict[int, list[int]] = {}
    retry_slots: list[int] = []
    for (slots, candidate), results in zip(plan, await _search_all([song for _, song in plan])):
        key = _song_key(candidate.artist, candidate.title)
        result, parts = (None, 1) if key in used_keys else _choose_result(candidate, results, used_ids)
        if result is None:
            retry_slots.extend(slots)
            continue
        used_ids.add(result.youtube_id)
        used_keys.add(key)
        batch.append(_BatchEntry(_item_from_result(candidate, result, slots[0]), parts, candidate, results))
        slots_for[slots[0]] = slots

    changes: dict[int, AutoGenerateProposalItem] = {}
    accepted = await _review_with_fallbacks(prompt, batch, used_ids)
    accepted_first = {entry.item.slot_index for entry in accepted}
    for first, slots in slots_for.items():
        if first not in accepted_first:
            retry_slots.extend(slots)
    for entry in accepted:
        slots = slots_for[entry.item.slot_index]
        # A compilation may hold fewer parts than asked for; the extra slots get their own swap.
        filled = slots[:max(1, min(entry.segments, len(slots)))]
        for slot in filled:
            changes[slot] = entry.item.model_copy(update={"slot_index": slot})
        retry_slots.extend(slots[len(filled):])

    if retry_slots:
        working = dc_replace(
            proposal,
            items=[changes.get(item.slot_index, item) for item in proposal.items],
            notes=[*proposal.notes, comment],
        )
        for slot in sorted(retry_slots):
            item = await replace_playlist_item(working, slot)
            if item.status == "resolved":
                changes[slot] = item
                working.items[slot] = item
    return changes


def _get_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(api_key=settings.openai_api_key)


_MODE_NOUN = {"music": "songs", "videos": "video clips", "mixed": "songs and video clips"}

# Clip searches use the planner's own short phrase; long "label - title: description" strings
# found poor YouTube matches, which the review then rejected, costing extra planning rounds.
_CLIP_QUERY_GUIDANCE = (
    "For each clip, \"query\" is the short phrase you would type into YouTube search to find that exact "
    "video: 3-8 plain words naming the people, the show or source, and the moment (e.g. "
    "\"William Hung She Bangs American Idol audition\"). No quotes, brackets, dashes, or labels like "
    "\"compilation\", \"fan channel\", or \"clip\" unless they are words the real video title would use. "
    "Never put such labels in \"artist\" either; leave it blank when the channel is unknown. "
)

# Appended to the planner prompts that can return non-music clips.
_COMPILATION_GUIDANCE = (
    "Each slot plays about 60 seconds of one video. Pick whichever kind of source is most likely to "
    "really exist on YouTube and contain what the prompt asks for; neither kind is preferred. "
    "A standalone video (roughly 1-15 minutes) is best for a moment that people upload on its own, "
    "such as a full performance or a famous audition. A compilation is often the better or only "
    "source for short moments that are rarely uploaded alone, such as funny auditions, judge "
    "reactions, bloopers, or one-liners: many of those exist only inside 'funniest moments', "
    "'best of', or 'worst auditions' compilations. Do not invent a standalone video for such a "
    "moment just to avoid a compilation, and do not use a compilation when good standalone videos "
    "exist. Only plan a compilation you are confident is a real, popular upload: a few broad ones "
    "(e.g. 'funniest auditions', 'best judge moments') with more parts each beat many narrowly "
    "titled ones (one per season, per judge, per week) that may not exist. "
    "To use a compilation, add \"segments\": 2-"
    f"{MAX_COMPILATION_SEGMENTS} to that clip entry and the app cuts that many different 60-second "
    "parts from it; each segment fills one of the 60 slots. Keep compilations to roughly half of "
    "the slots or fewer so the playlist stays varied, and omit \"segments\" for single clips."
)


def _slot_mode(proposal_mode: str, item_kind: str) -> str:
    """Mode used to plan/resolve one slot; mixed proposals keep each slot's own kind."""
    if proposal_mode == "mixed":
        return "music" if item_kind == "song" else "videos"
    return proposal_mode


def _planned_kind(mode: str, raw_kind: object) -> str:
    if mode == "music":
        return "song"
    if mode == "videos":
        return "clip"
    return "clip" if str(raw_kind).strip().lower() == "clip" else "song"


def _dedupe_planned_songs(raw_tracks: list[dict], mode: str = "music") -> list[PlannedSong]:
    songs: list[PlannedSong] = []
    seen: set[str] = set()
    for raw_track in raw_tracks:
        title = str(raw_track.get("title", "")).strip()
        artist = str(raw_track.get("artist", "")).strip()
        reason = str(raw_track.get("reason", "")).strip()
        if not title:
            continue
        key = _song_key(artist, title)
        if key in seen:
            continue
        seen.add(key)
        kind = _planned_kind(mode, raw_track.get("kind"))
        songs.append(
            PlannedSong(
                title=title,
                artist=artist,
                reason=reason,
                kind=kind,
                segments=_planned_segments(raw_track.get("segments")) if kind == "clip" else 1,
                query=_clean_query(raw_track.get("query")) if kind == "clip" else "",
            )
        )
    return songs


_QUERY_JUNK = re.compile(r"[\"“”‘’()\[\]{}|/—–:]+")


def _clean_query(raw: object) -> str:
    """Tidy the planner's search phrase: no quotes, brackets, or dash/slash labels."""
    text = _QUERY_JUNK.sub(" ", str(raw or ""))
    return " ".join(text.split())[:120]


def _search_query(candidate: PlannedSong) -> str:
    if candidate.kind == "clip" and candidate.query:
        return candidate.query
    return " - ".join(part for part in [candidate.artist.strip(), candidate.title.strip()] if part)


def _planned_segments(raw: object) -> int:
    try:
        return max(1, min(int(raw), MAX_COMPILATION_SEGMENTS))
    except (TypeError, ValueError):
        return 1


def _song_keys_from_items(items: Iterable[AutoGenerateProposalItem]) -> set[str]:
    return {
        _song_key(item.requested_artist, item.requested_title)
        for item in items
        if item.requested_title
    }


def _song_key(artist: str, title: str) -> str:
    return f"{_normalize_text(artist)}::{_normalize_text(title)}"


def _normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _format_exclusions(exclude_song_keys: set[str]) -> str:
    exclusions = sorted(key.replace("::", " - ") for key in exclude_song_keys if key)
    return ", ".join(exclusions[:80]) if exclusions else "none"


def _space_artists(items: list[AutoGenerateProposalItem]) -> list[AutoGenerateProposalItem]:
    """Reorder resolved items to reduce consecutive artists in the final proposal."""
    remaining = items[:]
    ordered: list[AutoGenerateProposalItem] = []
    previous_artist = ""

    while remaining:
        best_index = 0
        best_score = None

        for index, item in enumerate(remaining):
            artist_key = _normalize_text(item.requested_artist or item.artist)
            artist_count = sum(
                1
                for other in remaining
                if _normalize_text(other.requested_artist or other.artist) == artist_key
            )
            repeated_penalty = 1000 if artist_key and artist_key == previous_artist else 0
            score = (repeated_penalty, -artist_count, index)
            if best_score is None or score < best_score:
                best_score = score
                best_index = index

        selected = remaining.pop(best_index)
        ordered.append(selected)
        previous_artist = _normalize_text(selected.requested_artist or selected.artist)

    return ordered


async def _update_job_processing(
    job_id: str,
    processed_clips: int,
    total_clips: int,
    clip_title: str,
    clip_artist: str,
    step: str,
    step_progress: float,
) -> None:
    progress = 0.0
    if total_clips > 0:
        progress = min(75.0, ((processed_clips + step_progress) / total_clips) * 75.0)

    await job_store.update(
        job_id,
        phase="processing",
        progress=progress,
        processed_clips=processed_clips,
        current_step=step,
        current_title=clip_title,
        current_artist=clip_artist,
        error_message="",
    )


async def _mark_job_error(job_id: str, message: str) -> None:
    await job_store.update(
        job_id,
        phase="error",
        current_step="Generation stopped",
        error_message=message,
    )


