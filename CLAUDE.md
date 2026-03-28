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
   - editable start/end selection
5. User chooses the exact range. It may be shorter or longer than 60 seconds.
6. "Save range" stores the user’s chosen timestamps as draft selection.
7. "Trim and discard full video" creates the final clip file and deletes the original full download.

Important:
- Do not reintroduce automatic final clip selection during download.
- Recommendations should guide the user, not decide for them.
- Rendering should only use clips that have a valid saved selection.

## Runtime Notes

This repo is being used on an older Mac.

Important environment constraints:
- Use Node 20 via `.nvmrc`
- `scripts/start.sh` is expected to auto-use the project Node version when `nvm` is available
- Newer Node builds may fail on this macOS version
- Python 3.10+ is required; `python3` is the safer command to use for verification

Useful commands:

```bash
nvm use
python3 -m compileall backend/app
bash scripts/start.sh
```

## Source of Truth

Key files:
- [`scripts/start.sh`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/scripts/start.sh)
- [`backend/app/main.py`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/backend/app/main.py)
- [`backend/app/api/downloads.py`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/backend/app/api/downloads.py)
- [`backend/app/api/clips.py`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/backend/app/api/clips.py)
- [`backend/app/api/clip_utils.py`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/backend/app/api/clip_utils.py)
- [`backend/app/api/render.py`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/backend/app/api/render.py)
- [`backend/app/services/audio_analysis.py`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/backend/app/services/audio_analysis.py)
- [`backend/app/services/ffmpeg.py`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/backend/app/services/ffmpeg.py)
- [`frontend/src/pages/ProjectPage.tsx`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/frontend/src/pages/ProjectPage.tsx)
- [`frontend/src/utils/api.ts`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/frontend/src/utils/api.ts)
- [`frontend/src/utils/types.ts`](/Users/Jake/Documents/GitHub_Projects/power-hour-generator/frontend/src/utils/types.ts)

## Data and Storage

Persistent DB:
- SQLite file at `backend/power_hour.db`

Media storage:
- Review-stage source downloads live under `backend/media`
- Final committed trimmed clips live under `backend/media/clips`
- Analysis sidecars live under `backend/media/analysis`
- Render outputs live under `backend/static/renders`

Behavior expectations:
- Restarting the backend should not wipe the database
- Deleting a clip should delete associated local media and analysis sidecars
- Deleting a project should clean up all of that project’s local media when possible

## Backend Guidance

When changing backend behavior:
- Keep API responses compatible with the current frontend review flow unless changing both sides together
- Prefer explicit endpoints for transitions in clip state:
  - download/analyze
  - update draft selection
  - use suggestion
  - commit trimmed clip
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
  - waveform
  - suggested regions
  - start/end controls
  - save draft
  - commit trim

UX expectations:
- Users should understand whether they are reviewing a full source video or an already-trimmed committed clip
- Saving a range should feel non-destructive
- Trimming should be the explicit destructive/storage-saving action

## Verification

Preferred lightweight verification:

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
