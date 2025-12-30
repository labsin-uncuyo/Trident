#!/bin/bash
# Monitoring script to track data exfiltration progress
# Run this inside the router container to monitor when exfiltration completes

# Don't exit on error - we want to keep monitoring
set +e

OUTPUT_FILE="${1:-/tmp/exfil/monitoring.json}"
EXFIL_FILE="/tmp/exfil/labdb_dump.sql"
SAMPLE_INTERVAL=1  # Check every second

# Initialize monitoring
echo "{\"start_time\":\"$(date -Iseconds)\",\"status\":\"monitoring\"}" > "$OUTPUT_FILE"

last_size=0
stable_count=0
no_data_count=0
max_stable_count=30  # 30 seconds of no growth = complete
max_no_data=60  # 60 seconds with no data at all = timeout

log() {
    local key="$1"
    local value="$2"
    local timestamp=$(date -Iseconds)
    echo "{\"timestamp\":\"$timestamp\",\"$key\":\"$value\"}" >> "$OUTPUT_FILE"
}

log "monitor_start" "true"

echo "Monitoring exfiltration to: $EXFIL_FILE"
echo "Output file: $OUTPUT_FILE"
echo "Checking every ${SAMPLE_INTERVAL}s, will declare complete after ${max_stable_count}s of no growth"

while true; do
    if [[ -f "$EXFIL_FILE" ]]; then
        current_size=$(stat -c%s "$EXFIL_FILE" 2>/dev/null || echo "0")

        if [[ "$current_size" -gt 0 ]]; then
            # We have data, check for growth
            if [[ "$current_size" -eq "$last_size" ]]; then
                ((stable_count++))
                echo "Size stable at ${current_size} bytes for ${stable_count}s..."
                log "size_stable" "$current_size"

                if [[ $stable_count -ge $max_stable_count ]]; then
                    echo "Exfiltration appears complete (no growth for ${stable_count}s)"
                    log "exfil_complete" "$current_size"
                    log "end_time" "$(date -Iseconds)"
                    log "final_status" "success"
                    break
                fi
            else
                # File is still growing
                echo "File growing: ${last_size} -> ${current_size} bytes (+$((current_size - last_size)))"
                log "file_growing" "$current_size"
                stable_count=0  # Reset stable counter
                no_data_count=0  # Reset no data counter
            fi

            last_size=$current_size
        else
            # File exists but is empty
            ((no_data_count++))
            echo "Waiting for data... (${no_data_count}s)"
            log "waiting_for_data" "true"

            if [[ $no_data_count -ge $max_no_data ]]; then
                echo "Timeout: No data received after ${no_data_count}s"
                log "end_time" "$(date -Iseconds)"
                log "final_status" "timeout_no_data"
                break
            fi
        fi
    else
        ((no_data_count++))
        echo "Waiting for exfil file... (${no_data_count}s)"
        log "waiting_for_file" "true"

        if [[ $no_data_count -ge $max_no_data ]]; then
            echo "Timeout: Exfil file not created after ${no_data_count}s"
            log "end_time" "$(date -Iseconds)"
            log "final_status" "timeout_no_file"
            break
        fi
    fi

    sleep $SAMPLE_INTERVAL
done

# Write final summary
echo ""
echo "=== Exfiltration Monitoring Summary ==="
echo "Final file size: ${current_size:-0} bytes"
echo "Status: $(tail -1 "$OUTPUT_FILE" | grep -o 'final_status[^,}]*' | cut -d: -f2 | tr -d '"')"

exit 0
