# CLAUDE.md

This file gives project-specific guidance for working in this repository.

## Project

Power Hour Studio is a local web app for building a "power hour" video from music video clips.

Tech stack:
- Frontend: React + TypeScript + Vite + Tailwind
- Backend: FastAPI + SQLAlchemy + SQLite
- Media pipeline: `yt-dlp`, `librosa`, `ffmpeg`

## Current Product Behavior

The clip workflow is review-first, not auto-trim-first.

Current intended flow:
1. User searches YouTube and adds a track.
2. Backend downloads the full source video temporarily.
3. Backend analyzes the source audio and stores:
   - waveform bars
   - recommended highlight regions
   - suggested start/end range
4. Frontend shows a review UI with:
   - video preview
   - equalizer-style waveform
   - highlighted recommended sections
   - a draggable selection window on the waveform
5. User chooses the exact range. It may be shorter or longer than 60 seconds.
6. "Save range" stores the user’s chosen timestamps as draft selection.
7. "Trim and discard full video" creates the final clip file and deletes the original full download.

Important:
- Do not reintroduce automatic final clip selection during download.
- Recommendations should guide the user, not decide for them.
- Rendering should only use clips that have a valid saved selection.
- Exception: the AI Auto Generate flow is allowed to auto-select and auto-trim clips after the user explicitly approves an AI-proposed playlist.

## Runtime Notes

This repo is developed on WSL2 (Linux) and also run on an older Mac, so keep it portable.

Important environment constraints:
- Use Node 20 via `.nvmrc`
- `scripts/start.sh` is expected to auto-use the project Node version when `nvm` is available
- Newer Node builds may fail on this macOS version
- Python 3.10+ is required; `python3` is the safer command to use for verification
- GPU encoding is automatic: `USE_NVENC` defaults on, but each render does a real NVENC test encode and falls back to libx264, so CPU-only machines (Mac) just use the CPU; `USE_NVENC=0` forces CPU. In Docker the GPU must also be passed through, so start with `scripts/docker-up.sh` (or `.ps1`), which detects an NVIDIA GPU + Docker NVIDIA runtime and adds `docker-compose.gpu.yml`; a plain `docker compose up` has no GPU
- Docker publishes the API on port 8000 to the LAN (needed for casting) and there is no auth; only run it on a trusted network
- `librosa` is deliberately not in `requirements.txt` (conda on Mac via `start.sh`, pip in the Dockerfile)
- `backend/.env` must use an async DB URL (`sqlite+aiosqlite:///...`); the test suite overrides env vars so it is unaffected

Useful commands:

```bash
nvm use
python3 -m compileall backend/app
bash scripts/start.sh
```

Docker notes:
- A Docker-based local-share path now exists via [`docker-compose.yml`](docker-compose.yml)
- Docker persistence uses `backend/data/power_hour.db` plus `backend/media`
- Docker is intended for easier sharing to a newer Mac, not as the primary verified workflow on this machine

## Other Features

- **Changeover clip**: one optional per-project clip (video or audio, `api/changeover.py`, `services/changeover.py`) that render interleaves between songs. It has its own storage under `backend/media/changeover`.
- **Render library / mixtape binder**: completed renders are listed via `/api/render/library`.
- **Casting**: only rendered files served by this app may be cast (`core/security.py`).

## Source of Truth

Key files:
- [`scripts/start.sh`](scripts/start.sh)
- [`backend/app/main.py`](backend/app/main.py)
- [`backend/app/api/downloads.py`](backend/app/api/downloads.py)
- [`backend/app/api/clips.py`](backend/app/api/clips.py)
- [`backend/app/api/clip_utils.py`](backend/app/api/clip_utils.py)
- [`backend/app/api/render.py`](backend/app/api/render.py)
- [`backend/app/services/audio_analysis.py`](backend/app/services/audio_analysis.py)
- [`backend/app/services/ffmpeg.py`](backend/app/services/ffmpeg.py)
- [`frontend/src/pages/ProjectPage.tsx`](frontend/src/pages/ProjectPage.tsx)
- [`frontend/src/utils/api.ts`](frontend/src/utils/api.ts)
- [`frontend/src/utils/types.ts`](frontend/src/utils/types.ts)

## Data and Storage

Persistent DB:
- SQLite file at `backend/power_hour.db`
- Docker path: `backend/data/power_hour.db`

Media storage:
- Review-stage source downloads live under `backend/media/downloads`
- Final committed trimmed clips live under `backend/media/clips`
- Analysis sidecars live under `backend/media/analysis`
- Render outputs live under `backend/media/renders`

Behavior expectations:
- Restarting the backend should not wipe the database
- Deleting a clip should delete associated local media and analysis sidecars
- Deleting a project should clean up all of that project’s local media when possible

## Backend Guidance

Invariants the tests in `backend/tests` pin down (keep them true):
- Each clip downloads to its own file (`{youtube_id}_{clip_id}.mp4`) so clips of the same video never share or delete each other's source
- Draft ranges are clamped to the media duration; empty ranges are rejected
- Commit only deletes the source after ffmpeg succeeds
- On startup, clips stuck in DOWNLOADING/ANALYZING and renders stuck in QUEUED/RENDERING are marked ERROR (`core/recovery.py`)
- Render output filenames are slugified from the project name
- Downloads are limited by `max_concurrent_downloads` (semaphore in `api/downloads.py`)
- Starting a render returns `clips_included` / `clips_skipped` so the UI can warn about clips left out
- Cancelling a render waits for the render task to unwind before deleting its DB row
- Highlight analysis blends song scoring (loudness + onsets, beat snap) with a non-music activity score (presence + modulation, pause snap) by `music_likeness`; at likeness 1.0 it must reproduce the original song picks exactly. `beat_track` must keep using `y=` (its own median-aggregated onset envelope). `test_audio_analysis.py` skips if librosa isn't installed
- AI proposals have a `mode` (`music` | `videos` | `mixed`) and each item a `kind` (`song` | `clip`). Songs resolve with music search/ranking, clips with plain search; in mixed mode the AI picks the kind per slot and replacing a slot keeps its kind. The legacy `music` boolean is still accepted when `mode` is omitted
- Changeovers: a project has at most one `origin="manual"` row (all `/api/changeover` endpoints touch only that one) and any number of `origin="ai"` rows. Render cycles through all ready rows in `position` order. AI text goes to ffmpeg only via files (`build_text_card`, `expansion=none`), colors only from `PALETTE`, and an AI YouTube transition that fails falls back to a card. A manual changeover always wins over `ai_transition_count`
- Schema changes that `create_all` can't apply go in `core/migrations.py` (idempotent, run before `create_all`); the changeover-table rebuild is the example
- `_measure_loudnorm` must treat non-finite stats (silent audio) as a failed measurement, so silent cards render with single-pass loudnorm
- Fire-and-forget `asyncio.create_task` calls must keep a reference (see `_spawn` in `api/changeover.py`)

When changing backend behavior:
- Keep API responses compatible with the current frontend review flow unless changing both sides together
- Prefer explicit endpoints for transitions in clip state:
  - download/analyze
  - update draft selection
  - use suggestion
  - commit trimmed clip
- AI auto-generate should stay on its own additive API path and should not silently change the manual review-first endpoints
- Avoid silently mutating storage semantics in render code
- Keep render validation strict: no render if a clip has no valid selected range

Be careful about:
- deleting source files too early
- writing ffmpeg output over an input file
- stale analysis data after a clip is committed and the source file is gone

## Frontend Guidance

When changing the frontend:
- Preserve the review-first UX
- Show recommendation data as guidance, not authority
- Keep the clip review controls obvious:
  - preview
  - waveform editor
  - suggested regions
  - draggable selection window
  - visible selected duration
  - save draft
  - commit trim

UX expectations:
- Users should understand whether they are reviewing a full source video or an already-trimmed committed clip
- Saving a range should feel non-destructive
- Trimming should be the explicit destructive/storage-saving action
- AI auto-generate may create already-trimmed clips after approval, but that should remain visually and behaviorally distinct from the manual review flow

## Styling Guidance

Visual direction:
- Lean into a CRT/VHS-inspired interface rather than a generic dark dashboard
- Prefer neon-accented typography, phosphor-like glow, subtle bloom, and layered overlays
- Motion should feel analog and imperfect: flicker, scan passes, glow pulses, and small instability are good when used intentionally

Landing page guidance:
- The main title should feel alive with restrained CRT behavior, not constant chaos
- Static titles should use the ambient/randomized CRT treatment:
  - low-level text flicker
  - occasional scan-line sweep across the title
  - slight channel separation or ghosting only in short bursts
- Interactive text controls should use triggered CRT feedback on hover/focus:
  - a brief flicker first
  - then a scan-line pass
- Keep menu interactions crisp and readable even when the title is animated

Implementation notes:
- Prefer shared CSS classes in [`frontend/src/styles/globals.css`](frontend/src/styles/globals.css) for reusable retro effects
- Use React state/effects only when timing needs to feel irregular or event-driven
- Preserve readability first: effects should decorate text, not obscure it
- If adding motion, consider reducing intensity on dense workflow screens compared with the landing screen

## Verification

Backend tests (use `uv`; system Python on WSL has no venv/pip):

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest
```

Lightweight verification:

```bash
python3 -m compileall backend/app
```

If Node is working on the machine, also use:

```bash
cd frontend
npm run build
```

If the frontend build cannot run because of local Node/macOS compatibility, say so clearly instead of guessing.

## Avoid

Avoid these regressions:
- auto-selecting and committing clips immediately after download
- assuming every clip is exactly 60 seconds
- deleting full source media before the user commits a trim
- rendering clips with empty or invalid selections
- relying on a too-new Node version for local startup
