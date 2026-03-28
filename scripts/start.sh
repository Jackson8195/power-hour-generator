#!/usr/bin/env bash
# Power Hour Studio — One-command launcher
# Usage: ./scripts/start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  🍺 Power Hour Studio"
echo "  ────────────────────"
echo -e "${NC}"

# ─── Check prerequisites ──────────────────────────────────

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}✗ $1 is not installed.${NC} $2"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} $1 found"
}

echo "Checking prerequisites..."
check_command python3 "Install Python 3.10+ from https://python.org"
check_command node "Install Node.js 18+ from https://nodejs.org"
check_command npm "Comes with Node.js"
check_command ffmpeg "Install via: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"

# Check for yt-dlp (warn but don't fail)
if ! command -v yt-dlp &> /dev/null; then
    echo -e "${YELLOW}⚠ yt-dlp not found globally. Will use pip-installed version.${NC}"
fi

echo ""

# ─── Set up Python virtual environment ────────────────────

cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    echo -e "${CYAN}Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

source venv/bin/activate
echo -e "${GREEN}✓${NC} Virtual environment activated"

# Install/update Python deps
echo -e "${CYAN}Installing Python dependencies...${NC}"
pip install -q -r requirements.txt
echo -e "${GREEN}✓${NC} Python dependencies installed"

# ─── Set up frontend ──────────────────────────────────────

cd "$PROJECT_DIR/frontend"

if [ ! -d "node_modules" ]; then
    echo -e "${CYAN}Installing frontend dependencies...${NC}"
    npm install
fi
echo -e "${GREEN}✓${NC} Frontend dependencies ready"

cd "$PROJECT_DIR"

# ─── Copy .env if needed ──────────────────────────────────

if [ ! -f "backend/.env" ]; then
    cp .env.example backend/.env
    echo -e "${YELLOW}⚠ Created backend/.env from template. Edit it to add API keys.${NC}"
fi

# ─── Launch both servers ──────────────────────────────────

echo ""
echo -e "${CYAN}Starting servers...${NC}"
echo -e "  Backend:  ${GREEN}http://localhost:8000${NC}  (API docs: http://localhost:8000/docs)"
echo -e "  Frontend: ${GREEN}http://localhost:5173${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop both servers${NC}"
echo ""

# Trap Ctrl+C to kill both processes
cleanup() {
    echo ""
    echo -e "${CYAN}Shutting down...${NC}"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo -e "${GREEN}Done.${NC}"
    exit 0
}
trap cleanup INT TERM

# Start backend
cd "$PROJECT_DIR/backend"
python -m uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

# Start frontend
cd "$PROJECT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

# Wait for either to exit
wait $BACKEND_PID $FRONTEND_PID
