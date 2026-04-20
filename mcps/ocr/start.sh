#!/bin/bash
set -e

python main_api.py &
API_PID=$!

python main_mcp.py &
MCP_PID=$!

trap "kill $API_PID $MCP_PID 2>/dev/null; wait" EXIT INT TERM

wait