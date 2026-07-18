#!/bin/bash
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$PATH"
exec .venv/bin/python3 bot.py
