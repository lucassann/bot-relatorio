#!/usr/bin/env bash
cd "$(dirname "$0")"

PID=$(pgrep -f "python.*bot\.py")
if [ -n "$PID" ]; then
    echo "⚠️ O Bot já está em execução (PID: $PID)."
    echo "Para verificar status: ./status.sh"
    echo "Para parar: ./stop.sh"
    exit 0
fi

nohup ./venv/bin/python -u bot.py >> bot.log 2>&1 &
NEW_PID=$!
echo $NEW_PID > bot.pid

echo "✅ Bot iniciado com sucesso em segundo plano!"
echo "📌 PID: $NEW_PID"
echo "📜 Acompanhar logs: tail -f bot.log"
echo "🛑 Parar bot: ./stop.sh"
