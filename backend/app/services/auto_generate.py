"""AI-powered playlist planning and auto-trim processing."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable
from uuid import uuid4

from openai import AsyncOpenAI

from app.api.clip_utils import remove_clip_analysis
from app.core.config import settings
from app.core.security import public_render_url, resolve_managed_path, unlink_managed_file
from app.models.schemas import AutoGenerateProposalItem, SearchResult
from app.services.audio_analysis import analyze_audio
from app.services.changeover import apply_changeover_interleave
from app.services.ffmpeg import extract_clip_segment
from app.services.youtube import download_video, search_youtube

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


@dataclass
class PlannedSong:
    title: str
    artist: str
    reason: str = ""


@dataclass
class StoredProposal:
    proposal_id: str
    prompt: str
    normalized_prompt: str
    items: list[AutoGenerateProposalItem]
    expires_at: datetime
    created_at: datetime = field(default_factory=datetime.utcnow)


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
            proposal.items[slot_index] = item
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


def proposal_to_response(proposal: StoredProposal) -> dict:
    unresolved_count = sum(1 for item in proposal.items if item.status != "resolved")
    return {
        "proposal_id": proposal.proposal_id,
        "normalized_prompt": proposal.normalized_prompt,
        "items": proposal.items,
        "unresolved_count": unresolved_count,
        "expires_at": proposal.expires_at,
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


async def create_playlist_proposal(prompt: str) -> StoredProposal:
    """Create an ephemeral AI proposal and resolve it to YouTube-backed tracks."""
    normalized_prompt = " ".join(prompt.split())
    items = await _build_resolved_items(normalized_prompt)
    proposal = StoredProposal(
        proposal_id=uuid4().hex,
        prompt=prompt,
        normalized_prompt=normalized_prompt,
        items=items,
        expires_at=datetime.utcnow() + PROPOSAL_TTL,
    )
    await proposal_store.save(proposal)
    return proposal


async def start_proposal_job(prompt: str) -> ProposalJob:
    """Kick off create_playlist_proposal as a background task and return a job immediately."""
    job = ProposalJob(job_id=uuid4().hex, prompt=prompt)
    await proposal_job_store.save(job)

    async def _run() -> None:
        try:
            proposal = await create_playlist_proposal(prompt)
            await proposal_job_store.update(job.job_id, status="complete", proposal_id=proposal.proposal_id)
        except Exception as exc:
            logger.error("Proposal job %s failed: %s", job.job_id, exc)
            await proposal_job_store.update(job.job_id, status="error", error_message="AI playlist generation failed.")

    task = asyncio.create_task(_run())
    _AUTO_PROCESS_TASKS.add(task)
    task.add_done_callback(_AUTO_PROCESS_TASKS.discard)
    return job


async def start_replace_job(proposal_id: str, slot_index: int) -> ProposalJob:
    """Kick off replace_playlist_item as a background task and return a job immediately."""
    job = ProposalJob(job_id=uuid4().hex, prompt=f"replace:{proposal_id}:{slot_index}")
    await proposal_job_store.save(job)

    async def _run() -> None:
        try:
            proposal = await proposal_store.get(proposal_id)
            if not proposal:
                await proposal_job_store.update(job.job_id, status="error", error_message="Proposal not found or expired.")
                return
            item = await replace_playlist_item(proposal, slot_index)
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


def proposal_job_to_response(job: ProposalJob, proposal: StoredProposal | None) -> dict:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "error_message": job.error_message,
        "proposal": proposal_to_response(proposal) if proposal else None,
        "updated_at": job.updated_at,
    }


async def replace_playlist_item(proposal: StoredProposal, slot_index: int) -> AutoGenerateProposalItem:
    """Replace a single slot while preserving theme and avoiding duplicates."""
    existing_items = [item for item in proposal.items if item.slot_index != slot_index]
    excluded_songs = _song_keys_from_items(existing_items)
    excluded_ids = {item.youtube_id for item in existing_items if item.youtube_id}
    original = proposal.items[slot_index]

    for _ in range(MAX_REPLACEMENT_ATTEMPTS):
        alternates = await _plan_replacements(
            prompt=proposal.normalized_prompt,
            original=original,
            exclude_song_keys=excluded_songs,
            count=8,
        )
        replacement = await _resolve_candidates_to_item(
            slot_index=slot_index,
            candidates=alternates,
            used_song_keys=excluded_songs,
            used_youtube_ids=excluded_ids,
        )
        if replacement and replacement.status == "resolved":
            return replacement

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
    from app.core.database import async_session
    from app.models.schemas import ClipDB, ClipStatus
    from sqlalchemy import select

    async with GLOBAL_AUTO_PROCESS_SEMAPHORE:
        async with async_session() as db:
            result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
            clip = result.scalar_one_or_none()
            if not clip:
                await _mark_job_error(job_id, f"Clip {clip_id} could not be found")
                return False

            try:
                await _update_job_processing(
                    job_id=job_id,
                    processed_clips=clip_index,
                    total_clips=total_clips,
                    clip_title=clip.source_title,
                    clip_artist=clip.source_artist,
                    step="Downloading source video",
                    step_progress=0.12,
                )
                clip.status = ClipStatus.DOWNLOADING
                clip.error_message = ""
                await db.commit()

                dl_result = await download_video(clip.youtube_id)
                source_file_path = dl_result["file_path"]
                resolved_source = resolve_managed_path(source_file_path, settings.media_dir)
                if not resolved_source or not resolved_source.exists():
                    raise RuntimeError("Download completed but no local media file was found")

                if dl_result.get("title"):
                    clip.source_title = dl_result["title"]
                if dl_result.get("artist"):
                    clip.source_artist = dl_result["artist"]

                await _update_job_processing(
                    job_id=job_id,
                    processed_clips=clip_index,
                    total_clips=total_clips,
                    clip_title=clip.source_title,
                    clip_artist=clip.source_artist,
                    step="Generating waveform analysis",
                    step_progress=0.5,
                )
                clip.status = ClipStatus.ANALYZING
                await db.commit()

                analysis = await analyze_audio(str(resolved_source))
                if not analysis.get("waveform") or float(analysis.get("duration", 0) or 0) <= 0:
                    raise RuntimeError("Audio analysis did not produce waveform data")

                suggested_start = float(analysis.get("suggested_start", 0) or 0)
                suggested_end = float(analysis.get("suggested_end", 0) or 0)
                if suggested_end <= suggested_start:
                    raise RuntimeError("AI analysis did not produce a valid suggested segment")

                await _update_job_processing(
                    job_id=job_id,
                    processed_clips=clip_index,
                    total_clips=total_clips,
                    clip_title=clip.source_title,
                    clip_artist=clip.source_artist,
                    step="Clipping recommended 60 seconds",
                    step_progress=0.82,
                )
                output_path = settings.clips_dir / f"{clip.youtube_id or f'clip_{clip.id}'}_{clip.id}.mp4"
                await extract_clip_segment(
                    source_path=str(resolved_source),
                    output_path=str(output_path),
                    start_time=suggested_start,
                    end_time=suggested_end,
                )

                unlink_managed_file(str(resolved_source), settings.media_dir)
                remove_clip_analysis(clip.id)

                clip.bpm = analysis.get("bpm")
                clip.energy = analysis.get("energy")
                clip.file_path = str(output_path)
                clip.duration = max(suggested_end - suggested_start, 0.0)
                clip.start_time = 0.0
                clip.end_time = clip.duration
                clip.suggested_start = None
                clip.status = ClipStatus.READY
                clip.error_message = ""
                await db.commit()
                await _update_job_processing(
                    job_id=job_id,
                    processed_clips=clip_index + 1,
                    total_clips=total_clips,
                    clip_title=clip.source_title,
                    clip_artist=clip.source_artist,
                    step="Clip ready",
                    step_progress=0.0,
                )
                return True
            except Exception as exc:
                logger.error("Auto-processing failed for clip %s: %s", clip_id, exc)
                clip.status = ClipStatus.ERROR
                clip.error_message = AUTO_PROCESS_FAILURE_MESSAGE
                await db.commit()
                await _update_job_processing(
                    job_id=job_id,
                    processed_clips=clip_index + 1,
                    total_clips=total_clips,
                    clip_title=clip.source_title,
                    clip_artist=clip.source_artist,
                    step="Skipped after processing error",
                    step_progress=0.0,
                )
                return False


def start_auto_process_queue(job_id: str, project_id: int, clip_ids: Iterable[int]) -> asyncio.Task:
    """Start sequential processing for a newly approved AI playlist."""

    async def _run() -> None:
        clip_list = list(clip_ids)
        ready_count = 0

        for clip_index, clip_id in enumerate(clip_list):
            success = await auto_process_clip(
                clip_id=clip_id,
                job_id=job_id,
                clip_index=clip_index,
                total_clips=len(clip_list),
            )
            if success:
                ready_count += 1

        if ready_count == 0:
            await _mark_job_error(job_id, "No clips finished processing, so rendering could not start.")
            return

        await _run_auto_render(job_id, project_id)

    task = asyncio.create_task(_run())
    _AUTO_PROCESS_TASKS.add(task)
    task.add_done_callback(_AUTO_PROCESS_TASKS.discard)
    return task


async def _build_resolved_items(prompt: str) -> list[AutoGenerateProposalItem]:
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
        )
        for candidate in planned:
            if len(resolved_items) >= PROPOSAL_SIZE:
                break
            item = await _resolve_candidates_to_item(
                slot_index=len(resolved_items),
                candidates=[candidate],
                used_song_keys=used_song_keys,
                used_youtube_ids=used_youtube_ids,
            )
            if not item:
                continue
            if item.status == "resolved":
                resolved_items.append(item)
                used_song_keys.add(_song_key(item.requested_artist, item.requested_title))
                if item.youtube_id:
                    used_youtube_ids.add(item.youtube_id)
            else:
                unresolved_candidates.append(candidate)

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

    return [
        item.model_copy(update={"slot_index": index})
        for index, item in enumerate(combined[:PROPOSAL_SIZE])
    ]


async def _resolve_candidates_to_item(
    slot_index: int,
    candidates: list[PlannedSong],
    used_song_keys: set[str],
    used_youtube_ids: set[str],
) -> AutoGenerateProposalItem | None:
    for candidate in candidates:
        key = _song_key(candidate.artist, candidate.title)
        if not candidate.title or key in used_song_keys:
            continue
        result = await _resolve_song(candidate)
        if not result or result.youtube_id in used_youtube_ids:
            continue
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
        )

    if candidates:
        fallback = candidates[0]
        return AutoGenerateProposalItem(
            slot_index=slot_index,
            requested_title=fallback.title,
            requested_artist=fallback.artist,
            reason=fallback.reason,
            status="unresolved",
        )

    return None


async def _resolve_song(candidate: PlannedSong) -> SearchResult | None:
    query = " - ".join(part for part in [candidate.artist.strip(), candidate.title.strip()] if part)
    results = await search_youtube(query, max_results=6, preferred_artists=[candidate.artist] if candidate.artist else None)
    for result in results:
        if not result.youtube_id:
            continue
        return result
    return None


async def _plan_playlist(prompt: str, exclude_song_keys: set[str], target_count: int) -> list[PlannedSong]:
    client = _get_openai_client()
    exclusion_text = _format_exclusions(exclude_song_keys)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a music supervisor building a 60-song power hour playlist. "
                    "Return only strict JSON shaped as {\"tracks\": [{\"title\": string, \"artist\": string, \"reason\": string}]}. "
                    "Favor recognizable songs with likely official music videos. Avoid duplicates, live versions, lyric videos, karaoke, remixes unless requested. "
                    "Do not cluster the same artist repeatedly in sequence unless the user explicitly asks for a narrow artist-focused mix."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Build {target_count} candidate songs for this power hour prompt: {prompt}\n"
                    "Keep variety unless the prompt explicitly asks for something narrow.\n"
                    "Mix artists across the running order so the same artist does not play back to back when possible.\n"
                    f"Avoid these already used songs: {exclusion_text}."
                ),
            },
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return _dedupe_planned_songs(payload.get("tracks", []))


async def _plan_replacements(
    prompt: str,
    original: AutoGenerateProposalItem,
    exclude_song_keys: set[str],
    count: int,
) -> list[PlannedSong]:
    client = _get_openai_client()
    exclusion_text = _format_exclusions(exclude_song_keys)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You return only strict JSON shaped as {\"tracks\": [{\"title\": string, \"artist\": string, \"reason\": string}]}. "
                    "Suggest replacements that preserve the same theme but are distinct songs."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Prompt: {prompt}\n"
                    f"Replace this song with {count} alternatives: {original.requested_artist} - {original.requested_title}\n"
                    f"Avoid these already selected songs: {exclusion_text}."
                ),
            },
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return _dedupe_planned_songs(payload.get("tracks", []))


def _get_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(api_key=settings.openai_api_key)


def _dedupe_planned_songs(raw_tracks: list[dict]) -> list[PlannedSong]:
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
        songs.append(PlannedSong(title=title, artist=artist, reason=reason))
    return songs


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


async def _run_auto_render(job_id: str, project_id: int) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.database import async_session
    from app.models.schemas import ClipDB, ClipStatus, ProjectDB, RenderDB, RenderRequest, RenderStatus
    from app.services.ffmpeg import RenderPipeline

    async with async_session() as db:
        result = await db.execute(
            select(ProjectDB)
            .options(selectinload(ProjectDB.clips))
            .where(ProjectDB.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            await _mark_job_error(job_id, "Project could not be found for final render.")
            return

        ready_clips = [
            clip
            for clip in project.clips
            if clip.status == ClipStatus.READY and clip.file_path and clip.end_time > clip.start_time
        ]
        if not ready_clips:
            await _mark_job_error(job_id, "No trimmed clips were ready for final render.")
            return

        ready_clips.sort(key=lambda clip: clip.position)

        request = RenderRequest()

        render = RenderDB(
            project_id=project_id,
            output_path="",
            resolution=request.resolution,
            status=RenderStatus.QUEUED,
        )
        db.add(render)
        await db.flush()
        await db.refresh(render)
        output_path = settings.render_dir / f"power_hour_{project.name.lower().replace(' ', '_')}_{project_id}_render_{render.id}.mp4"
        render.output_path = str(output_path)
        await db.commit()

        clip_data = [
            {
                "file_path": clip.file_path,
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "title": clip.source_title,
            }
            for clip in ready_clips
        ]

        # Interleave the project's changeover clip between songs, if one is ready.
        # No-op for a freshly generated project until the user configures one.
        clip_data = await apply_changeover_interleave(db, project_id, clip_data)

        await job_store.update(
            job_id,
            phase="rendering",
            progress=75.0,
            render_id=render.id,
            current_step="Rendering final power hour",
            current_title="",
            current_artist="",
        )

        try:
            render.status = RenderStatus.RENDERING
            render.started_at = datetime.utcnow()
            await db.commit()

            def progress_callback(pct: float) -> None:
                task = asyncio.create_task(
                    job_store.update(
                        job_id,
                        phase="rendering",
                        progress=min(100.0, 75.0 + (pct * 0.25)),
                        current_step="Rendering final power hour",
                        current_title="",
                        current_artist="",
                    )
                )
                _AUTO_PROCESS_TASKS.add(task)
                task.add_done_callback(_AUTO_PROCESS_TASKS.discard)

            def on_encoder_selected(gpu_active: bool) -> None:
                task = asyncio.create_task(job_store.update(job_id, gpu_active=gpu_active))
                _AUTO_PROCESS_TASKS.add(task)
                task.add_done_callback(_AUTO_PROCESS_TASKS.discard)

            pipeline = RenderPipeline(
                clips=clip_data,
                output_path=str(output_path),
                resolution=request.resolution,
                transition_type=request.transition_type,
                include_countdown=request.include_countdown,
                progress_callback=progress_callback,
                on_encoder_selected=on_encoder_selected,
            )
            await pipeline.render()

            render.status = RenderStatus.COMPLETE
            render.progress = 100.0
            render.completed_at = datetime.utcnow()
            await db.commit()

            await job_store.update(
                job_id,
                phase="complete",
                progress=100.0,
                current_step="Final render complete",
                output_path=str(output_path),
                error_message="",
            )
        except Exception as exc:
            logger.error("Auto-render failed for project %s: %s", project_id, exc)
            render.status = RenderStatus.ERROR
            render.error_message = AUTO_RENDER_FAILURE_MESSAGE
            await db.commit()
            await _mark_job_error(job_id, AUTO_RENDER_FAILURE_MESSAGE)
