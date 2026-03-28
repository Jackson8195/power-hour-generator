#!/usr/bin/env bash
# Power Hour Studio — One-command launcher
# Usage: ./scripts/start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
NVMRC_PATH="$PROJECT_DIR/.nvmrc"

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

load_nvm() {
    if command -v nvm &> /dev/null; then
        return 0
    fi

    if [ -s "$HOME/.nvm/nvm.sh" ]; then
        # shellcheck disable=SC1090
        source "$HOME/.nvm/nvm.sh"
        return 0
    fi

    return 1
}

ensure_project_node() {
    if [ ! -f "$NVMRC_PATH" ]; then
        return 0
    fi

    local desired_node
    desired_node="$(tr -d '[:space:]' < "$NVMRC_PATH")"
    if [ -z "$desired_node" ]; then
        return 0
    fi

    if ! load_nvm; then
        echo -e "${YELLOW}⚠ nvm not found in this shell. Using whatever Node is already on PATH.${NC}"
        return 0
    fi

    if ! nvm use "$desired_node" >/dev/null 2>&1; then
        echo -e "${CYAN}Installing Node.js ${desired_node} via nvm for this project...${NC}"
        nvm install "$desired_node"
        nvm use "$desired_node" >/dev/null
    fi

    echo -e "${GREEN}✓${NC} Using Node.js $(node -v) from .nvmrc"
}

check_node_runtime() {
    local node_output
    if ! node_output=$(node -v 2>&1); then
        echo -e "${RED}✗ node is installed but could not start.${NC}"
        echo "$node_output"
        echo -e "${YELLOW}This usually means the selected Node binary is incompatible with your macOS version.${NC}"
        echo -e "${YELLOW}Switch to a compatible Node version (Node 20 LTS is a safe choice) and try again.${NC}"
        exit 1
    fi

    local node_major="${node_output#v}"
    node_major="${node_major%%.*}"
    if [ "$node_major" -lt 18 ]; then
        echo -e "${RED}✗ Node.js ${node_output} is too old for this frontend.${NC}"
        echo -e "${YELLOW}Vite 5 requires Node.js 18+.${NC} Install or switch to Node 20 LTS and rerun the script."
        exit 1
    fi

    echo -e "${GREEN}✓${NC} node runtime OK (${node_output})"
}

check_npm_runtime() {
    local npm_output
    if ! npm_output=$(npm -v 2>&1); then
        echo -e "${RED}✗ npm is installed but could not start.${NC}"
        echo "$npm_output"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} npm runtime OK (${npm_output})"
}

echo "Checking prerequisites..."
ensure_project_node
check_command python3 "Install Python 3.10+ from https://python.org"
check_command node "Install Node.js 18+ from https://nodejs.org"
check_command npm "Comes with Node.js"
check_command ffmpeg "Download from https://evermeet.cx/ffmpeg/ and place in /usr/local/bin/"
check_node_runtime
check_npm_runtime

# Check for yt-dlp (warn but don't fail)
if ! command -v yt-dlp &> /dev/null; then
    echo -e "${YELLOW}⚠ yt-dlp not found globally. Will use pip-installed version.${NC}"
fi

echo ""

# ─── Set up Python (conda) ───────────────────────────────

cd "$PROJECT_DIR"

CONDA_ENV_NAME="powerhour"

# Find conda
if command -v conda &> /dev/null; then
    echo -e "${GREEN}✓${NC} conda found"
else
    echo -e "${RED}✗ conda not found. Install miniforge or anaconda first.${NC}"
    exit 1
fi

# Initialize conda for this shell session
eval "$(conda shell.bash hook)"

# Create env if it doesn't exist
if ! conda env list | grep -q "^${CONDA_ENV_NAME} "; then
    echo -e "${CYAN}Creating conda environment '${CONDA_ENV_NAME}'...${NC}"
    conda create -n "$CONDA_ENV_NAME" python=3.12 -y
    conda activate "$CONDA_ENV_NAME"
    echo -e "${CYAN}Installing librosa via conda (avoids llvmlite build issues)...${NC}"
    conda install librosa -c conda-forge -y
else
    conda activate "$CONDA_ENV_NAME"
fi

echo -e "${GREEN}✓${NC} conda env '${CONDA_ENV_NAME}' activated ($(python --version))"

# Install/update pip deps
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
