#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"
exec /home/pghpgh01/work/agent/my-gemini-chat/.venv/bin/python3 server.py
