#!/bin/zsh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJECT_DIR/contentVenv"
MEDIA_LOG="/tmp/content-engine-media-server.log"
TELEGRAM_LOG="/tmp/content-engine-telegram-bot.log"
SCHEDULER_LOG="$PROJECT_DIR/logs/scheduler.log"
SCHEDULER_PID_FILE="/tmp/content-engine-scheduler.pid"
SCHEDULER_STATE_FILE="$PROJECT_DIR/output/.scheduler_state"

mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/output"
touch "$SCHEDULER_LOG"

log() {
    local message="$1"
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$message" | tee -a "$SCHEDULER_LOG"
}

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

pacific_now() {
    TZ="America/Los_Angeles" date +%s
}

pacific_datetime() {
    local epoch="$1"
    TZ="America/Los_Angeles" date -r "$epoch" '+%Y-%m-%d %H:%M:%S %Z'
}

scheduled_epoch() {
    local date_value="$1"
    local time_value="$2"
    TZ="America/Los_Angeles" date -j -f "%Y-%m-%d %H:%M:%S" "$date_value $time_value:00" +%s 2>/dev/null
}

next_schedule_after() {
    local reference_epoch="$1"
    local base_date candidate_date epoch
    local best_epoch=0 best_label=""

    base_date=$(TZ="America/Los_Angeles" date -r "$reference_epoch" '+%Y-%m-%d')

    for day_offset in 0 1 2; do
        candidate_date=$(TZ="America/Los_Angeles" date -j -v+${day_offset}d -f "%Y-%m-%d" "$base_date" '+%Y-%m-%d')
        for spec in "04:00|single" "10:00|batch" "16:00|single" "22:00|single"; do
            local time_value="${spec%%|*}"
            local label="${spec##*|}"
            epoch=$(scheduled_epoch "$candidate_date" "$time_value")
            [ -z "$epoch" ] && continue

            if [ "$epoch" -le "$reference_epoch" ]; then
                continue
            fi

            if [ "$best_epoch" -eq 0 ] || [ "$epoch" -lt "$best_epoch" ]; then
                best_epoch="$epoch"
                best_label="$label"
            fi
        done
    done

    NEXT_EPOCH="$best_epoch"
    NEXT_LABEL="$best_label"
}

load_last_handled() {
    if [ -f "$SCHEDULER_STATE_FILE" ]; then
        local value
        value=$(cat "$SCHEDULER_STATE_FILE" 2>/dev/null | tr -d '[:space:]')
        if [[ "$value" =~ '^[0-9]+$' ]]; then
            LAST_HANDLED_EPOCH="$value"
            return
        fi
    fi
    LAST_HANDLED_EPOCH=0
}

save_last_handled() {
    printf '%s\n' "$1" > "$SCHEDULER_STATE_FILE"
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
        log "WARNING: No production run directory found for Telegram notification."
        return 0
    fi

    log "Sending Telegram publication report..."
    "$VENV/bin/python3" -m app.telegram_notify "$latest_run" \
        || log "WARNING: Telegram publication notification failed."
}

run_scheduled_pipeline() {
    local label="$1"
    local exit_code

    echo ""
    echo "========================================"

    if [ "$label" = "batch" ]; then
        echo "⏰ SCHEDULED 10:00 — MORNING BATCH"
        echo "========================================"
        echo "$(date '+%Y-%m-%d %H:%M:%S') — starting pipeline_batch..."
        "$VENV/bin/python3" -m app.pipeline_batch 2>&1 | tee -a "$SCHEDULER_LOG"
        exit_code=${pipestatus[1]}
    else
        echo "⏰ SCHEDULED — SINGLE VIDEO"
        echo "========================================"
        echo "$(date '+%Y-%m-%d %H:%M:%S') — starting pipeline..."
        "$VENV/bin/python3" -m app.pipeline 2>&1 | tee -a "$SCHEDULER_LOG"
        exit_code=${pipestatus[1]}
    fi

    echo ""
    log "Scheduled $label run finished with exit code $exit_code."
    notify_latest_run "$label"
    return "$exit_code"
}

cleanup() {
    rm -f "$SCHEDULER_PID_FILE"
    echo ""
    log "🛑 Scheduler stopped. Media server and Telegram bot were left running."
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
    nohup "$VENV/bin/python3" -m app.media_server >> "$MEDIA_LOG" 2>&1 &
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
    nohup "$VENV/bin/python3" -m app.telegram_bot >> "$TELEGRAM_LOG" 2>&1 &
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

# =========================================================
# WALL-CLOCK SCHEDULER
# =========================================================

load_last_handled
NOW=$(pacific_now)
CUTOFF=$((NOW - 86400))
LAST_ANNOUNCED_NEXT=""

if [ "$LAST_HANDLED_EPOCH" -gt 0 ]; then
    log "Scheduler state: last handled slot $(pacific_datetime "$LAST_HANDLED_EPOCH")"
else
    log "Scheduler state: no previously handled slot recorded."
fi

log "Pacific wall-clock scheduler active."
log "Schedule: 04:00 single | 10:00 batch (4) | 16:00 single | 22:00 single"
log "Catch-up window: 24 hours"

# Repeatedly inspect the wall clock. We never sleep until a calculated
# timestamp, so a macOS sleep/wake cycle cannot permanently throw off cadence.
while true; do
    NOW=$(pacific_now)
    CUTOFF=$((NOW - 86400))
    START_FROM="$LAST_HANDLED_EPOCH"

    if [ "$START_FROM" -lt "$CUTOFF" ]; then
        START_FROM="$CUTOFF"
    fi

    DUE_EPOCH=0
    DUE_LABEL=""
    BASE_DATE=$(TZ="America/Los_Angeles" date -r "$START_FROM" '+%Y-%m-%d')

    # Search the recent past/future for the earliest unhandled slot that is
    # both inside the 24-hour catch-up window and already due.
    for day_offset in 0 1 2; do
        CANDIDATE_DATE=$(TZ="America/Los_Angeles" date -j -v+${day_offset}d -f "%Y-%m-%d" "$BASE_DATE" '+%Y-%m-%d')

        for spec in "04:00|single" "10:00|batch" "16:00|single" "22:00|single"; do
            TIME_VALUE="${spec%%|*}"
            LABEL="${spec##*|}"
            EPOCH=$(scheduled_epoch "$CANDIDATE_DATE" "$TIME_VALUE")
            [ -z "$EPOCH" ] && continue

            if [ "$EPOCH" -le "$START_FROM" ] || [ "$EPOCH" -gt "$NOW" ] || [ "$EPOCH" -lt "$CUTOFF" ]; then
                continue
            fi

            if [ "$DUE_EPOCH" -eq 0 ] || [ "$EPOCH" -lt "$DUE_EPOCH" ]; then
                DUE_EPOCH="$EPOCH"
                DUE_LABEL="$LABEL"
            fi
        done
    done

    if [ "$DUE_EPOCH" -gt 0 ]; then
        log "Scheduled slot due: $(pacific_datetime "$DUE_EPOCH") ($DUE_LABEL)"
        log "Running scheduled $DUE_LABEL pipeline."

        run_scheduled_pipeline "$DUE_LABEL"
        RUN_EXIT=$?

        # Mark attempted slots as handled regardless of pipeline exit status.
        # This prevents a failed job from being retried every 30 seconds.
        LAST_HANDLED_EPOCH="$DUE_EPOCH"
        save_last_handled "$LAST_HANDLED_EPOCH"

        if [ "$RUN_EXIT" -eq 0 ]; then
            log "Slot handled successfully: $(pacific_datetime "$DUE_EPOCH") ($DUE_LABEL)"
        else
            log "WARNING: Slot handled with pipeline exit code $RUN_EXIT: $(pacific_datetime "$DUE_EPOCH") ($DUE_LABEL)"
        fi

        # Clear the idle announcement cache so the next newly calculated
        # future slot is announced once after this run completes.
        LAST_ANNOUNCED_NEXT=""

        # Immediately inspect again so multiple missed slots can be caught up
        # sequentially after a sleep/wake cycle.
        continue
    fi

    next_schedule_after "$NOW"

    if [ "$NEXT_EPOCH" -eq 0 ]; then
        log "ERROR: Could not calculate next scheduled run. Retrying in 30 seconds."
        sleep 30
        continue
    fi

    NEXT_KEY="${NEXT_EPOCH}|${NEXT_LABEL}"

    if [ "$NEXT_KEY" != "$LAST_ANNOUNCED_NEXT" ]; then
        log "Next scheduled run: $(pacific_datetime "$NEXT_EPOCH") ($NEXT_LABEL)"
        LAST_ANNOUNCED_NEXT="$NEXT_KEY"
    fi

    sleep 30
done
