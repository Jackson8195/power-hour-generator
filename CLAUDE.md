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
- The AI Auto Generate flow may auto-SELECT ranges after the user approves a playlist, but never auto-trims or auto-renders: every build stops in a "review" phase with the AI picks saved as editable draft ranges on the full sources, and the user renders from the project page

## Versioning

The repo-root `VERSION` file is the only place the version lives (currently 2.0.0). The backend reads it in `app/core/version.py` (API metadata and `/api/health`), and the frontend bakes it in at build time as `__APP_VERSION__` (`vite.config.ts`, shown in the footer). Both Dockerfiles copy it. `frontend/package.json` must match it (`tests/test_version.py` checks). Release tags follow `power-hour-vX.Y`.

## Runtime Notes

This repo is developed on WSL2 (Linux) and also run on an older Mac, so keep it portable.

Important environment constraints:
- Use Node 20 via `.nvmrc`
- `scripts/start.sh` is expected to auto-use the project Node version when `nvm` is available
- Newer Node builds may fail on this macOS version
- Python 3.10+ is required; `python3` is the safer command to use for verification
- GPU encoding is automatic: `USE_NVENC` defaults on, but each render does a real NVENC test encode and falls back to libx264, so CPU-only machines (Mac) just use the CPU; `USE_NVENC=0` forces CPU. In Docker the GPU must also be passed through, so start with `scripts/docker-up.sh` (or `.ps1`), which detects an NVIDIA GPU + Docker NVIDIA runtime and adds `docker-compose.gpu.yml`; a plain `docker compose up` has no GPU
- Docker publishes the API on port 8000 to the LAN (needed for casting) and there is no auth; only run it on a trusted network
- `librosa` is deliberately not in `requirements.txt` (conda on Mac via `start.sh`, pip in the Dockerfile). It is pinned to `1.0.1` in both, the version the tests run on; 1.0 needs Python 3.12+, so the Docker image is `python:3.12-slim`. Upgrade by bumping both pins and rerunning `backend/tests`
- `backend/.env` must use an async DB URL (`sqlite+aiosqlite:///...`); the test suite overrides env vars so it is unaffected

**Running the project:** when the user asks to run/start/rebuild the project, use `bash scripts/docker-up.sh` (it picks the GPU compose file automatically when an NVIDIA GPU is usable). Do not run plain `docker compose up`, which recreates the containers without GPU access. `scripts/start.sh` is only for running without Docker.

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
- **Tape downloads**: each tape on the shelf has DOWNLOAD (`GET /api/render/{id}/download`, an attachment; nginx streams it unbuffered) and COPY LINK, which copies that download link for another device on the Wi-Fi. A page opened at localhost swaps in the PC's LAN address: `scripts/docker-up` sets `PH_LAN_HOST`, compose passes it as `LAN_HOST` (`settings.lan_host`), and `/api/health` returns it with `frontend_port`. The casting service is still unwired (no `pychromecast`, no UI)

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
- Commit refuses with 409 a clip that is already trimmed (its file is in `clips_dir`) or being trimmed (`_trims_in_progress`), checked before range clamping, so a second device or stale tab can't re-trim a trimmed clip with full-source timestamps or run ffmpeg over its own input. The project page shows the message on the clip and refreshes
- On startup, clips stuck in DOWNLOADING/ANALYZING and renders stuck in QUEUED/RENDERING are marked ERROR (`core/recovery.py`)
- Render output filenames are slugified from the project name
- Render overlays (`mark_song_positions` in `services/ffmpeg.py`): every song gets a top-right `12 / 60` counter (`song_counter_filter`, songs only, transitions never counted; `include_counter` on `RenderRequest`). A song followed by a transition skips the old center 5-4-3-2-1 + DRINK! (the transition does its own corner 3·2·1 + call word); songs with no transition after them keep it
- Every rendered clip (songs, video clips, transitions) gets a very quick edge "breath" in `_normalize_clip`: `edge_fades` dips the picture to black (0.15s in / 0.25s out, applied after the countdown overlay) and fades the sound (0.2s in / 0.4s out). The fades eat into each clip, so no time is added; short clips get proportionally shorter fades. `transition_type` is still only a label (the final join is a plain concat)
- Downloads are limited by `max_concurrent_downloads` (semaphore in `api/downloads.py`)
- Starting a render returns `clips_included` / `clips_skipped` so the UI can warn about clips left out
- Cancelling a render waits for the render task to unwind before deleting its DB row
- Highlight analysis blends song scoring (loudness + onsets, beat snap) with a non-music activity score (presence + modulation, pause snap) by `music_likeness`; at likeness 1.0 it must reproduce the original song picks exactly. `beat_track` must keep using `y=` (its own median-aggregated onset envelope). `test_audio_analysis.py` skips if librosa isn't installed
- AI proposals have a `mode` (`music` | `videos` | `mixed`) and each item a `kind` (`song` | `clip`). Songs resolve with music search/ranking, clips with plain search; in mixed mode the AI picks the kind per slot and replacing a slot keeps its kind. The legacy `music` boolean is still accepted when `mode` is omitted
- Changeovers: a project has at most one `origin="manual"` row (all `/api/changeover` endpoints touch only that one) and any number of `origin="ai"` rows. Render cycles through all ready rows in `position` order. AI text goes to ffmpeg only via files (`build_text_card`, `expansion=none`), colors only from `PALETTE`, and an AI YouTube transition that fails falls back to a card (logged with the reason) only in the cards + videos mix. A manual changeover always wins over `ai_transition_count`
- Transition style (`services/transition_fx.py`): every generated transition has a small corner 3·2·1 countdown and real audio. Cards are drink art (`build_art_card`, 5.5s): a still image drifts while the countdown ticks, then flash/shake/call word on the cue. The art is per-transition AI art (`generate_art`, `openai_image_model`, default `gpt-image-2`; the prompt always gets `ART_RULES`: no text, no real people) or the bundled fallback set in `app/assets/transitions/art` (also used by the default SHOT! card). Video transitions are a highlight moment (`_pick_moment`, 4s by default, user-trimmable 1-20s) ending with the call word over the video's held last frame (`build_video_transition`, 1.8s tail); no art card. Empty call word = just the held frame and cue. In "videos only" mode (and when the user asks for a video) a slot that finds no usable video errors instead of falling back to an art card; only the cards + videos mix falls back. The build keeps the WHOLE download (`{stem}_src.mp4` in `raw_video_path`, used range in `trim_start`/`trim_end` as seconds into it; color/word/cue plus the source's `waveform` and `source_seconds` in the `style` JSON column) so the review's TRIM shows the whole video with its waveform and can rebuild any 1-20s range (`trim_ai_transition`) without downloading again; it is deleted after the power hour renders (`finalize_project_media`) or when the transition is trashed. The old text card / freeze-frame builders remain only as no-art fallbacks. Cues are recordings only, picked by the user: `can` (default, `DEFAULT_SOUND`), `clink`, `pop`, `pour`, `cheer`, `bell` (`SOUNDS` / `RECORDED_SOUNDS`, files and their sources/licenses in `app/assets/transitions/sounds/SOURCES.md`). The synthesized horn/buzzer/bell were scrapped by the user; don't bring them back. A cue is offered only when its file exists (`available_sounds`), unknown names fall back via `usable_sound`, and every builder (art card, text card, video transition) mixes the recording in through `_cue_audio`; the generated layer is only the thump on the hit and the countdown ticks. Overlays blend in RGB (`format=rgba`) so darkening doesn't desaturate. ffmpeg runs with `cwd` = the temp dir holding the text files, so the graph has bare file names only (no Windows drive colons). The call word is the user's own text (`drink_text`, cleaned by `clean_drink_text`, max 24 chars, only ever written to a file for ffmpeg): set for a whole generated set, per transition via `/text` (rebuilds cards and videos) or with a trim; without one the AI picks from `HIT_WORDS`. The DB row `duration` is the real built length (render trims to it). The test suite blanks the image model so tests never call the paid image API
- Manual (builder) transitions accept `countdown` (default on) plus an optional `drink_ending` (cue name, "" = none), `drink_art` (bundled art file name) and `drink_word`, validated by `_wrap_options` against fixed lists and applied after the build with `build_clip_with_stinger`. `drink_art="none"` (`HOLD_FRAME_ART`, the builder default) is the video-only ending: no art card, the call word + cue land on the clip's own held last frame (`hold_frame`, `video_filter`), like an AI video transition. The manual transition reuses fixed file names (`project_{id}_raw.*`, `project_{id}_changeover.mp4`), so `ChangeoverBuilder` versions their URLs (`freshMedia`) or the browser replays a cached old video; replacing or deleting it uses `delete_manual_changeover_files`, never the full `delete_changeover_media_files` (which also wipes `project_{id}_ai_*` and is only for project deletion)
- AI transition review (`api/ai_transitions.py`): choosing AI transitions pre-creates the project; `/api/ai-transitions/{project_id}` generates a set (given the power hour prompt plus the user's transition prompt) and regenerates / adds / trashes single ones (placeholder rows with status `building`, a fresh file name per build, old files removed only from the changeover dir, never the bundled art). Approving with `ai_transitions_reviewed` keeps the ready rows instead of generating during the build. `_sync_pending_clips` rebuilds a pre-created project's still-PENDING clips from the proposal, so swapping songs after the project exists is safe
- AI transitions with `sources="both"` alternate video/card (video first) regardless of the AI's `kind`; YouTube picks skip the playlist's own video ids, earlier transitions' ids, results whose title matches a playlist song, and sources over 10 min. Video picks are filtered like playlist clips: `search_plan` tries the planner's short `query`, its broader `fallback_query`, then `broaden_query` (drops season/episode numbers and years); `choose_youtube_candidates` ranks by title relevance to the search before length; `review_transition_results` (one AI call per search, against the power hour prompt + transition direction in `spec.context`) rejects wrong show/era, songs and reaction videos and fails open. The moment is picked as speech (`analyze_audio(..., music_likeness=0.0)`, `MOMENT_MUSIC_LIKENESS`) Transitions are built at `render_resolution()` (the `RenderRequest` default); the render still rescales every clip
- Schema changes that `create_all` can't apply go in `core/migrations.py` (idempotent, run before `create_all`); the changeover-table rebuild is the example. New columns on existing tables go in `ADDED_COLUMNS` (`add_missing_columns`, run after `create_all`)
- `_measure_loudnorm` must treat non-finite stats (silent audio) as a failed measurement, so silent cards render with single-pass loudnorm
- Fire-and-forget `asyncio.create_task` calls must keep a reference (see `_spawn` in `api/changeover.py`)
- AI compilations: a planned clip may carry `segments` (2-5). It fills that many proposal slots sharing one `youtube_id` (labelled via `segment_index`/`segment_count`, spread apart by `_space_artists`). The AI queue groups clips by `youtube_id`, downloads/analyzes once and saves non-overlapping ranges (`analysis["segments"]`) as each part's draft; the shared source stays for review. This is AI-flow only; the manual per-clip download rule above is unchanged. Single-clip slots avoid sources over 20 min; nothing over 90 min is picked (`_pick_clip_source`)
- Review flow storage: `auto_process_source` saves each clip's pick as `start_time`/`end_time` on the full source (`duration` = source length, per-clip analysis sidecar with `suggested_start/end` = its own range) and keeps the source; compilation parts share ONE source file. Trims and clip deletes go through `services/clip_media.py` (`trim_clip`, `release_source`), which only delete a source when no other clip still uses it. Rendering with `finalize_sources` (sent by the project page whenever clips are still on their sources, after a confirm) trims every such clip to its range and releases the sources ONLY after a successful render (`finalize_project_media`), and drops the AI transitions' kept sources
- AI proposals filter off-prompt results: clip results must share >=25% of the request's meaningful words (`_shares_query_terms`), then each resolved batch (and each replacement) goes through one AI review call (`_review_results`, model `OPENAI_REVIEW_MODEL` or `OPENAI_MODEL`) that rejects off-topic/wrong-show/wrong-era videos. Review fails open (an error rejects nothing); batches resolve a small surplus so rejections don't leave slots short. A rejected slot first tries the other results of its own search (re-reviewed, `REVIEW_FALLBACK_ROUNDS`) before the planner is asked again
- Playlist revision (no full redo): REVISE (`POST /proposals/{id}/revise`, `revise_playlist`) makes ONE planner call that returns only the slots to change (`_plan_revision` drops locked, out-of-range and repeated slots; length is fixed, compilations may claim 2-5 slots); only those are searched and reviewed, a failed one gets an ordinary steered swap, and a slot with nothing usable keeps its old pick. `apply_revision` tags changed slots `revised` (NEW), appends the comment to `notes` and keeps one-step `undo` (`/undo` restores items + notes but keeps current locks). Every later swap and review follows the notes (`_steered_prompt`). `/lock` slots are never changed by REVISE or REPLACE (replace answers 409; a lock set mid-swap wins in `replace_item`). REPLACE takes an optional `note`: a YouTube link is used as-is (`parse_youtube_id` + `lookup_video`), an entry the planner flags `exact` skips the off-topic review, anything else steers the planner. The running revise job id is shared in the AI session (`revise_job_id`) so both devices follow it
- Proposal speed: clips search with the planner's short `query` phrase (`_clean_query`; songs keep `artist - title`), and a batch's searches run `SEARCH_CONCURRENCY` at a time but are claimed in plan order
- AI-flow downloads that fail with a network error (DNS, connection, timeout) are retried with backoff (`NETWORK_RETRY_DELAYS`, ~15 min total) instead of erroring the clip. Every build ends in phase `review` (not "running": `job_store.active()` skips it); below `MIN_READY_FRACTION_TO_RENDER` (80%) ready the step text says how many failed so the user replaces them first
- Phone + desktop in tandem (one responsive frontend, same URLs; Docker serves it on the LAN at `:5173` and `docker-up` prints the address): all shared state lives on the backend. The AI generator's draft (prompt, mode, proposal, transition settings, a generating proposal job) is the in-memory `ai_session_store` (`GET/PUT/DELETE /api/auto-generate/session`, version-bumped, last write wins, cleared on approve); the running build is `GET /api/auto-generate/jobs/active` (declared before `/jobs/{job_id}`). The project page polls while visible and keeps an unsaved local draft range unless the server value changed since the last load (the merge must stay a pure state updater: StrictMode runs updaters twice)
- Downloads prefer H.264 + AAC (`[vcodec^=avc1]` + `m4a`, falling back to any codec) because the review preview plays the source file directly and iPhones can't play VP9/AV1
- Audio analysis loads via `_load_audio`: librosa first, else an ffmpeg decode to float PCM. librosa 1.0 dropped its audioread fallback and can't open MP4/M4A at all, and the Dockerfile installs librosa unpinned
- Non-music analysis snaps starts to content changes (`_find_content_boundaries`, within 6s) before pauses, and damps intros/end screens; none of this runs at music likeness 1.0

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
- AI auto-generate pre-selects ranges (drafts on the full source) for the user to review; the project page shows a CHECK THE PICKS notice while clips are still on their sources and an AI TRANSITIONS panel when the project has them

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
- Every screen except the landing menu renders inside `Layout` (`StudioNav`: HOME, breadcrumbs from `utils/nav.ts`, BACK that falls back to the parent route) and wraps its content in `StudioPage` (eyebrow, title, actions). Pages name themselves in the breadcrumbs with `usePageCrumb`
- Type scale: `type-display` (VT323, titles), `type-label` / `type-eyebrow` (VT323, never under 18px, tracking ≤ 0.2em), `type-body` (Space Mono 15px, ≥ 80% opacity), `type-data` (tabular numbers). Use the Tailwind color tokens (`phosphor`, `magenta`, `crt`, `status`) rather than hex values
- Shared controls: `retro-button-primary|secondary|danger|warn|ghost`, `SegmentedControl`, `Spinner` (VU bars), `RingProgress`, `osd-notice`, and `useConfirm()` for any delete or destructive action (no native `confirm()`)
- Finished renders live on the VHS tape shelf (`TapeShelfPage`); every animation must stop under `prefers-reduced-motion`
- Phones: below `md` the `MobileTabBar` replaces the footer, breadcrumbs collapse to the current page and the project header stops pinning. Touch targets are 44px under `(pointer: coarse)`, inputs 16px (no iOS focus zoom), hover CRT effects are off under `(hover: none)`, and every `<video>` has `playsInline`. Stacked grids need `grid-cols-[minmax(0,1fr)]` or wide children (the tape row) widen the page
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
