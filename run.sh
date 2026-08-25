#!/bin/zsh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJECT_DIR/contentVenv"
MEDIA_PORT=8080

LOG_DIR="$PROJECT_DIR/logs"
MEDIA_LOG="$LOG_DIR/media_server.log"
TELEGRAM_LOG="$LOG_DIR/telegram_bot.log"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR" || exit 1

echo "========================================"
echo "🚀 CONTENT ENGINE"
echo "========================================"
echo ""
echo "Project: $PROJECT_DIR"
echo ""

# =========================================================
# VIRTUAL ENVIRONMENT
# =========================================================

if [ ! -d "$VENV" ]; then
    echo "❌ Virtual environment not found:"
    echo "   $VENV"
    exit 1
fi

source "$VENV/bin/activate"

echo "🐍 Python:"
echo "   $(which python3)"
echo "   $(python3 --version)"
echo ""

# =========================================================
# TAILSCALE
# =========================================================

echo "🌐 Checking Tailscale Funnel..."

if tailscale funnel status >/dev/null 2>&1; then
    echo "✅ Tailscale Funnel available."
else
    echo "❌ Tailscale Funnel is not available."
    exit 1
fi

echo ""

# =========================================================
# MEDIA SERVER
# =========================================================

echo "📡 Checking media server..."

MEDIA_PID=$(lsof -tiTCP:${MEDIA_PORT} -sTCP:LISTEN 2>/dev/null | head -1)

if [ -n "$MEDIA_PID" ]; then

    echo "✅ Media server already running."
    echo "   PID: $MEDIA_PID"

else

    echo "📡 Starting media server..."

    nohup "$VENV/bin/python3" -m app.media_server \
        >> "$MEDIA_LOG" 2>&1 &

    MEDIA_PID=$!

    sleep 2

    if kill -0 "$MEDIA_PID" 2>/dev/null; then
        echo "✅ Media server started."
        echo "   PID: $MEDIA_PID"
    else
        echo "❌ Media server failed to start."
        echo ""
        echo "Last log output:"
        tail -20 "$MEDIA_LOG"
        exit 1
    fi

fi

echo ""

# =========================================================
# TELEGRAM BOT
# =========================================================

echo "🤖 Checking Telegram bot..."

TELEGRAM_PID=$(pgrep -f "$VENV/bin/python3 -m app.telegram_bot" | head -1)

if [ -n "$TELEGRAM_PID" ]; then

    echo "✅ Telegram bot already running."
    echo "   PID: $TELEGRAM_PID"

else

    echo "🤖 Starting Telegram bot..."

    nohup "$VENV/bin/python3" -m app.telegram_bot \
        >> "$TELEGRAM_LOG" 2>&1 &

    TELEGRAM_PID=$!

    sleep 2

    if kill -0 "$TELEGRAM_PID" 2>/dev/null; then
        echo "✅ Telegram bot started."
        echo "   PID: $TELEGRAM_PID"
    else
        echo "❌ Telegram bot failed to start."
        echo ""
        echo "Last log output:"
        tail -20 "$TELEGRAM_LOG"
        exit 1
    fi

fi

echo ""

# =========================================================
# STATUS
# =========================================================

echo "========================================"
echo "✅ CONTENT ENGINE RUNNING"
echo "========================================"
echo ""
echo "Media server: PID $MEDIA_PID"
echo "Telegram bot: PID $TELEGRAM_PID"
echo ""
echo "Logs:"
echo "  $MEDIA_LOG"
echo "  $TELEGRAM_LOG"
echo ""
echo "Terminal is now free."
echo ""
