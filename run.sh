#!/bin/zsh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJECT_DIR/contentVenv"
MEDIA_LOG="/tmp/content-engine-media-server.log"
TELEGRAM_LOG="/tmp/content-engine-telegram-bot.log"
SCHEDULER_LOG="/tmp/content-engine-scheduler.log"
SCHEDULER_PID_FILE="/tmp/content-engine-scheduler.pid"

process_pids() {
    ps -axo pid=,command= | awk -v module="$1" '
        {
            for (field = 2; field < NF; field++) {
                if ($field == "-m" && $(field + 1) == module) {
                    print $1
                }
            }
        }
    '
}

wait_for_process() {
    local pid="$1"

    for attempt in {1..20}; do
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done

    return 1
}

next_schedule() {
    local now target epoch best_epoch=0 best_label=""
    now=$(date +%s)
    local today=$(date +%Y-%m-%d)
    local tomorrow=$(date -v+1d +%Y-%m-%d)

    for spec in "04:00|single" "10:00|batch" "16:00|single" "22:00|single"; do
        local time="${spec%%|*}"
        local label="${spec##*|}"

        target="$today $time:00"
        epoch=$(date -j -f "%Y-%m-%d %H:%M:%S" "$target" +%s 2>/dev/null)

        if [ "$epoch" -le "$now" ]; then
            if [ "$time" = "04:00" ]; then
                target="$tomorrow $time:00"
                epoch=$(date -j -f "%Y-%m-%d %H:%M:%S" "$target" +%s)
            else
                continue
            fi
        fi

        if [ "$best_epoch" -eq 0 ] || [ "$epoch" -lt "$best_epoch" ]; then
            best_epoch="$epoch"
            best_label="$label"
        fi
    done

    NEXT_EPOCH="$best_epoch"
    NEXT_LABEL="$best_label"
}

notify_latest_run() {
    local label="$1"
    local latest_run=""

    if [ "$label" = "batch" ]; then
        latest_run=$(ls -td "$PROJECT_DIR"/output/runs/*_batch 2>/dev/null | head -1)
    else
        latest_run=$(ls -td "$PROJECT_DIR"/output/runs/* 2>/dev/null | grep -v '_batch$' | head -1)
    fi

    if [ -z "$latest_run" ]; then
        echo "   ⚠️ No production run directory found for Telegram notification."
        return 0
    fi

    echo "   📲 Sending Telegram publication report..."

    "$VENV/bin/python3" -m app.telegram_notify "$latest_run" \
        || echo "   ⚠️ Telegram publication notification failed."
}

run_scheduled_pipeline() {
    local label="$1"

    echo ""
    echo "========================================"

    if [ "$label" = "batch" ]; then
        echo "⏰ SCHEDULED 10:00 — MORNING BATCH"
        echo "========================================"
        echo "$(date '+%Y-%m-%d %H:%M:%S') — starting pipeline_batch..."
        "$VENV/bin/python3" -m app.pipeline_batch
    else
        echo "⏰ SCHEDULED — SINGLE VIDEO"
        echo "========================================"
        echo "$(date '+%Y-%m-%d %H:%M:%S') — starting pipeline..."
        "$VENV/bin/python3" -m app.pipeline
    fi

    local exit_code=$?

    echo ""
    echo "$(date '+%Y-%m-%d %H:%M:%S') — scheduled $label run finished with exit code $exit_code."

    notify_latest_run "$label"
}

cleanup() {
    rm -f "$SCHEDULER_PID_FILE"
    echo ""
    echo "🛑 Scheduler stopped. Media server and Telegram bot were left running."
    exit 0
}

cd "$PROJECT_DIR" || exit 1

# =========================================================
# TAILSCALE FUNNEL
# =========================================================

echo "========================================"
echo "🚀 CONTENT ENGINE SERVICES + SCHEDULER"
echo "========================================"
echo ""

echo "🌐 Checking Tailscale Funnel..."

if tailscale funnel status >/dev/null 2>&1; then
    echo "   ✅ Tailscale Funnel available."
else
    echo "   ❌ Tailscale Funnel is not available."
    exit 1
fi

echo ""

# =========================================================
# MEDIA SERVER
# =========================================================

echo "📡 Checking media server..."

MEDIA_PIDS=$(process_pids "app.media_server")
MEDIA_COUNT=$(printf '%s\n' "$MEDIA_PIDS" | sed '/^$/d' | wc -l | tr -d ' ')

if [ "$MEDIA_COUNT" -gt 1 ]; then
    echo "❌ Multiple content-engine media servers detected:"
    printf '   PID %s\n' $MEDIA_PIDS
    exit 1

elif [ "$MEDIA_COUNT" -eq 1 ]; then
    MEDIA_PID="$MEDIA_PIDS"
    echo "   ✅ Media server already running."
    echo "      PID: $MEDIA_PID"

else
    echo "📡 Starting media server..."

    nohup "$VENV/bin/python3" -m app.media_server \
        >> "$MEDIA_LOG" 2>&1 &

    MEDIA_PID=$!

    if wait_for_process "$MEDIA_PID"; then
        echo "   ✅ Media server started."
        echo "      PID: $MEDIA_PID"
    else
        echo "   ❌ Media server failed to start."
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

TELEGRAM_PIDS=$(process_pids "app.telegram_bot")
TELEGRAM_COUNT=$(printf '%s\n' "$TELEGRAM_PIDS" | sed '/^$/d' | wc -l | tr -d ' ')

if [ "$TELEGRAM_COUNT" -gt 1 ]; then
    echo "❌ Multiple Telegram bot instances detected:"
    printf '   PID %s\n' $TELEGRAM_PIDS
    echo "   Stop the duplicates manually before rerunning ./run.sh."
    exit 1

elif [ "$TELEGRAM_COUNT" -eq 1 ]; then
    TELEGRAM_PID="$TELEGRAM_PIDS"
    echo "   ✅ Telegram bot already running."
    echo "      PID: $TELEGRAM_PID"

else
    echo "🤖 Starting Telegram bot..."

    nohup "$VENV/bin/python3" -m app.telegram_bot \
        >> "$TELEGRAM_LOG" 2>&1 &

    TELEGRAM_PID=$!

    if wait_for_process "$TELEGRAM_PID"; then
        echo "   ✅ Telegram bot started."
        echo "      PID: $TELEGRAM_PID"
    else
        echo "   ❌ Telegram bot failed to start."
        echo ""
        echo "Last log output:"
        tail -20 "$TELEGRAM_LOG"
        exit 1
    fi
fi

# =========================================================
# SCHEDULER
# =========================================================

if [ -f "$SCHEDULER_PID_FILE" ]; then
    EXISTING_PID=$(cat "$SCHEDULER_PID_FILE" 2>/dev/null)

    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo ""
        echo "⚠️ Scheduler already running (PID $EXISTING_PID)."
        echo "   Do not start a second ./run.sh instance."
        exit 1
    fi

    rm -f "$SCHEDULER_PID_FILE"
fi

echo $$ > "$SCHEDULER_PID_FILE"
trap cleanup INT TERM
trap 'rm -f "$SCHEDULER_PID_FILE"' EXIT

next_schedule

NEXT_DATE=$(date -r "$NEXT_EPOCH" '+%Y-%m-%d %H:%M:%S')

echo ""
echo "========================================"
echo "⏰ CONTENT ENGINE SCHEDULER ACTIVE"
echo "========================================"
echo "10:00  → pipeline_batch (4 videos)"
echo "16:00  → pipeline (1 video)"
echo "22:00  → pipeline (1 video)"
echo "04:00  → pipeline (1 video)"
echo ""
echo "Next scheduled run: $NEXT_DATE ($NEXT_LABEL)"
echo "Scheduler PID: $$"
echo ""
echo "Press Ctrl-C to stop the scheduler."
echo "Services will remain running."
echo ""

while true; do
    next_schedule

    now=$(date +%s)
    sleep_seconds=$((NEXT_EPOCH - now))

    if [ "$sleep_seconds" -gt 0 ]; then
        sleep "$sleep_seconds"
    fi

    run_scheduled_pipeline "$NEXT_LABEL"

    next_schedule
    echo "Next scheduled run: $(date -r "$NEXT_EPOCH" '+%Y-%m-%d %H:%M:%S') ($NEXT_LABEL)"
done
