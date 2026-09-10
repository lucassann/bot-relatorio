#!/usr/bin/env bash
cd "$(dirname "$0")"

PID=$(pgrep -f "python.*bot\.py")
if [ -n "$PID" ]; then
    kill $PID
    rm -f bot.pid
    echo "🛑 Bot encerrado (PID: $PID)."
else
    echo "⚠️ O bot não está em execução."
    rm -f bot.pid
fi
