#!/bin/bash
# Resilient eval runner — auto-restarts on hangs
# Monitors process CPU activity and restarts if dead for 8 minutes

OUTPUT_FILE="eval_results_run9.json"
MAX_STALL_SECONDS=720  # 12 minutes with no CPU activity (matches 600s API timeout)

while true; do
    echo "[$(date)] Starting eval (--resume)..."
    PYTHONUNBUFFERED=1 python3 eval_harness.py --output "$OUTPUT_FILE" --resume &
    EVAL_PID=$!

    STALL_COUNT=0

    while kill -0 $EVAL_PID 2>/dev/null; do
        sleep 30

        # Check if process has any CPU activity or open TCP connections
        CPU=$(ps -p $EVAL_PID -o %cpu= 2>/dev/null | tr -d ' ')
        TCP=$(lsof -p $EVAL_PID 2>/dev/null | grep -c TCP || echo 0)

        if [ "${CPU:-0}" = "0.0" ] && [ "${TCP:-0}" = "0" ]; then
            STALL_COUNT=$((STALL_COUNT + 30))
            echo "[$(date)] Idle: CPU=${CPU}, TCP=${TCP}, stall=${STALL_COUNT}s"
        else
            if [ $STALL_COUNT -gt 0 ]; then
                echo "[$(date)] Resumed: CPU=${CPU}, TCP=${TCP}"
            fi
            STALL_COUNT=0
        fi

        if [ $STALL_COUNT -ge $MAX_STALL_SECONDS ]; then
            echo "[$(date)] Dead for ${MAX_STALL_SECONDS}s — killing PID $EVAL_PID"
            kill $EVAL_PID 2>/dev/null
            sleep 2
            kill -9 $EVAL_PID 2>/dev/null
            break
        fi
    done

    wait $EVAL_PID 2>/dev/null
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] Eval completed successfully!"
        break
    fi

    DONE=$(python3 -c "
import json
with open('$OUTPUT_FILE') as f:
    d = json.load(f)
t = d.get('task_results', {})
done = sum(1 for v in t.values() if v.get('harness'))
print(done)
" 2>/dev/null)

    echo "[$(date)] Tasks complete: ${DONE}/25 (exit code: $EXIT_CODE)"

    if [ "$DONE" = "25" ]; then
        echo "[$(date)] All tasks done!"
        break
    fi

    echo "[$(date)] Restarting in 5s..."
    sleep 5
done
