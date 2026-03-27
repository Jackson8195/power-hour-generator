# 🍺 Power Hour Studio

A local web application for creating Power Hour videos — the drinking game where you watch 60 one-minute music video clips with transitions between each.

## Features

- **Song Discovery** — Search YouTube for music videos, browse by genre/decade
- **Smart Clip Selection** — Audio analysis finds the best 60-second segment (chorus/drop detection)
- **Visual Timeline Editor** — Drag-and-drop clip ordering with waveform previews
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
- **Node.js 18+** and npm
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

## Project Structure

```
power-hour-studio/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── api/
│   │   │   ├── search.py        # YouTube/Spotify search endpoints
│   │   │   ├── downloads.py     # yt-dlp download management
│   │   │   ├── clips.py         # Clip CRUD + audio analysis
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
│   │       ├── audio_analysis.py# librosa beat/chorus detection
│   │       ├── ffmpeg.py        # FFmpeg render pipeline
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

## License

MIT — Personal use project. Be mindful of YouTube's Terms of Service.
