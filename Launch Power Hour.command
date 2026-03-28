#!/bin/bash

PROJECT_DIR="/Users/Jake/Documents/GitHub_Projects/power-hour-generator"

cd "$PROJECT_DIR" || exit 1
bash scripts/start.sh

echo
echo "Press Enter to close this window..."
read -r
