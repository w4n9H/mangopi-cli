#!/bin/bash
# Simulate a single FlashExtServer request with tool_schema
# Usage: ./test_flash_ext_curl.sh [host] [port]
#   Requires FlashExtServer running: python mangopi_cli.py --flash-ext --debug

HOST="${1:-127.0.0.1}"
PORT="${2:-8080}"

curl -s "${HOST}:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 123456" \
  -d '{
  "model": "MiniMax-M3",
  "messages": [
    {"role": "system", "content": "You are a CLI assistant. Use tools when needed."},
    {"role": "user", "content": "list files in current directory"}
  ],
  "tools": [{
    "type": "function",
    "function": {
      "name": "bash",
      "description": "Execute a shell command",
      "parameters": {
        "type": "object",
        "properties": {
          "cmd": {"type": "string", "description": "The shell command to execute"}
        },
        "required": ["cmd"]
      }
    }
  }],
  "stream": false
}' | python3 -m json.tool
