#!/usr/bin/env bash
cd "$(dirname "$0")"

PID=$(pgrep -f "python.*bot\.py")
if [ -n "$PID" ]; then
    echo "🟢 Status: Bot em execução (PID: $PID)"
else
    echo "🔴 Status: Bot está PARADO."
    echo "Para iniciar: ./run_bg.sh ou ./run.sh"
fi
