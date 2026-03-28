# 🍺 Power Hour Studio

A local web application for creating Power Hour videos from music video clips, with search, review, trimming, ordering, and final rendering in one place.

## Features

- **Song Discovery** — Search YouTube for music videos, browse by genre/decade
- **Recommended Clip Review** — Audio analysis suggests likely chorus/high-energy sections without auto-picking the final range
- **Waveform-Guided Selection** — Review a preview player, waveform/equalizer bars, and highlighted recommended regions before trimming
- **Flexible Clip Lengths** — Users choose the exact start/end range; clips do not have to be exactly 60 seconds
- **Timeline Editing** — Arrange saved clips into the final Power Hour sequence
- **Video Rendering** — FFmpeg-powered concatenation with transitions and countdown overlays
- **TV Casting** — Cast to Chromecast, AirPlay, or DLNA devices on your network
- **Project Management** — Save, load, and share Power Hour playlists

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  React Frontend                  │
│         (Vite + Tailwind, localhost:5173)         │
└──────────────────────┬──────────────────────────┘
                       │ REST + WebSocket
┌──────────────────────┴──────────────────────────┐
│                FastAPI Backend                    │
│              (Python, localhost:8000)             │
│                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ yt-dlp   │ │ librosa  │ │ FFmpeg           │ │
│  │ download │ │ analysis │ │ render pipeline  │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
│                                                  │
│  ┌──────────────────────────────────────────────┐│
│  │ SQLite — projects, clips, render jobs        ││
│  └──────────────────────────────────────────────┘│
└──────────────────────────────────────────────────┘
```

## Prerequisites

- **Python 3.10+** (3.11 recommended)
- **Node.js 18+** and npm (`.nvmrc` pins Node 20 for this project)
- **FFmpeg** — installed and on your PATH
- **yt-dlp** — installed via pip or standalone

### Install FFmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (via chocolatey)
choco install ffmpeg
```

## Quick Start

### Docker local share

For a casual local user, the easiest setup is Docker Desktop.

Prerequisite:
- Docker Desktop for Mac

Steps:

```bash
git clone <your-repo-url>
cd power-hour-generator
cp .env.example backend/.env
# Edit backend/.env and add any API keys you want to use
docker compose up --build
```

Then open **http://localhost:5173**.

Notes:
- Docker keeps the app local on the same machine.
- Project data persists in `backend/power_hour.db`.
- Media files persist in `backend/media`.
- Chromecast/network discovery may not behave reliably from Docker on macOS.
  Browser playback and system-level AirPlay are the safer fallback.

### Standard developer setup

### 1. Clone & install backend

```bash
cd power-hour-studio

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Install frontend

```bash
nvm use  # or: nvm install
cd frontend
npm install
cd ..
```

### 3. Set up environment

```bash
cp .env.example .env
# Edit .env and add your YouTube Data API key (optional but recommended)
```

### 4. Run the app

```bash
# Terminal 1 — Backend
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

## Clip Workflow

1. Search YouTube and add a track to a project.
2. The backend downloads the source video and analyzes the audio.
3. The app shows:
   - a preview player
   - waveform/equalizer bars
   - highlighted recommended sections
   - editable start and end controls
4. Save a draft range when you like the selection.
5. Use **Trim and discard full video** to create the final clip file and free disk space.

The recommendation system is intentionally advisory: it points you toward likely chorus or high-energy sections, but the user makes the final choice.

## Project Structure

```
power-hour-studio/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── api/
│   │   │   ├── search.py        # YouTube/Spotify search endpoints
│   │   │   ├── downloads.py     # yt-dlp download + analysis kickoff
│   │   │   ├── clips.py         # Clip review, draft selection, commit trim
│   │   │   ├── clip_utils.py    # Clip response + analysis sidecar helpers
│   │   │   ├── projects.py      # Project management
│   │   │   ├── render.py        # Render pipeline endpoints
│   │   │   └── cast.py          # Casting/playback endpoints
│   │   ├── core/
│   │   │   ├── config.py        # Settings & env vars
│   │   │   └── database.py      # SQLite connection
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic models
│   │   └── services/
│   │       ├── youtube.py       # YouTube Data API + yt-dlp
│   │       ├── audio_analysis.py# waveform + recommendation analysis
│   │       ├── ffmpeg.py        # FFmpeg trim + render pipeline
│   │       └── casting.py       # Chromecast/DLNA discovery
│   └── static/                  # Rendered videos served here
├── frontend/
│   ├── src/
│   │   ├── components/          # Reusable UI components
│   │   ├── pages/               # Route pages
│   │   ├── hooks/               # Custom React hooks
│   │   ├── utils/               # Helpers & API client
│   │   └── styles/              # Global styles
│   ├── index.html
│   ├── vite.config.ts
│   └── package.json
├── scripts/
│   └── start.sh                 # One-command launcher
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## API Documentation

Once running, visit **http://localhost:8000/docs** for the interactive Swagger UI.

## Storage Notes

- Project data persists in `backend/power_hour.db`
- Review-stage source downloads are stored in `backend/media/downloads`
- Final committed trimmed clips are stored in `backend/media/clips`
- Analysis sidecars are stored in `backend/media/analysis`
- Final renders are stored in `backend/media/renders`

## License

MIT — Personal use project. Be mindful of YouTube's Terms of Service.
