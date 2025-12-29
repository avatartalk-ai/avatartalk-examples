#!/bin/bash

# Infinite restart script for AvatarTalk YouTube Streamer
# Usage: ./run_streamer.sh <video_id> <language> [background_url]
#
# This script will automatically restart the streamer if it crashes,
# with intelligent welcome message detection to prevent duplicate greetings.

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
if [ $# -lt 2 ]; then
    log_error "Usage: $0 <video_id> <language> [background_url]"
    echo ""
    echo "Arguments:"
    echo "  video_id       - YouTube video ID (required)"
    echo "  language       - Stream language code, e.g., 'en', 'es', 'fr' (required)"
    echo "  background_url - Optional background image URL"
    echo ""
    echo "Example:"
    echo "  $0 dQw4w9WgXcQ en"
    echo "  $0 dQw4w9WgXcQ es https://example.com/background.png"
    exit 2
fi

VIDEO_ID="$1"
LANGUAGE="$2"
BACKGROUND_URL="${3:-}"

# Validate inputs
if [ -z "$VIDEO_ID" ]; then
    log_error "Video ID cannot be empty"
    exit 2
fi

if [ -z "$LANGUAGE" ]; then
    log_error "Language cannot be empty"
    exit 2
fi

log_info "Starting AvatarTalk YouTube Streamer in infinite restart mode"
log_info "Video ID: $VIDEO_ID"
log_info "Language: $LANGUAGE"
if [ -n "$BACKGROUND_URL" ]; then
    log_info "Background URL: $BACKGROUND_URL"
fi

# Counter for restarts
RESTART_COUNT=0
TOTAL_CRASHES=0

# Trap Ctrl+C to exit gracefully
trap 'log_warning "Received SIGINT (Ctrl+C), shutting down..."; exit 130' INT
trap 'log_warning "Received SIGTERM, shutting down..."; exit 143' TERM

# Main loop
while true; do
    # Build command with optional background URL
    CMD_ARGS=("$VIDEO_ID" "--language" "$LANGUAGE")

    if [ -n "$BACKGROUND_URL" ]; then
        CMD_ARGS+=("--background-url" "$BACKGROUND_URL")
    fi

    # Log restart info
    if [ $RESTART_COUNT -eq 0 ]; then
        log_success "Starting streamer for the first time..."
    else
        log_warning "Restart #$RESTART_COUNT (Total crashes: $TOTAL_CRASHES)"
        log_info "Auto-detection enabled - welcome messages will be skipped if already posted"
    fi

    # Start time for this run
    START_TIME=$(date +%s)

    # Run the streamer (auto-detection handles welcome skip)
    # Note: We don't use --skip-welcome flag here because auto-detection is smarter
    set +e
    uv run main.py "${CMD_ARGS[@]}"
    EXIT_CODE=$?
    set -e

    # Calculate runtime
    END_TIME=$(date +%s)
    RUNTIME=$((END_TIME - START_TIME))

    # Handle exit codes
    case $EXIT_CODE in
        0)
            log_success "Streamer exited normally (runtime: ${RUNTIME}s)"
            log_info "Restarting in 5 seconds..."
            ;;
        130)
            log_info "Streamer was interrupted by user (Ctrl+C)"
            log_info "Exiting restart loop"
            exit 0
            ;;
        2)
            log_error "Configuration error (exit code 2)"
            log_error "Check your video ID, language, and config files"
            log_info "Exiting - fix configuration and try again"
            exit 2
            ;;
        1)
            TOTAL_CRASHES=$((TOTAL_CRASHES + 1))
            log_error "Streamer crashed with error (runtime: ${RUNTIME}s, exit code: 1)"

            # If crash happened very quickly, wait longer before restart
            if [ $RUNTIME -lt 30 ]; then
                log_warning "Crash occurred within 30 seconds - waiting 30s before restart"
                sleep 30
            else
                log_info "Restarting in 10 seconds..."
                sleep 10
            fi
            ;;
        *)
            TOTAL_CRASHES=$((TOTAL_CRASHES + 1))
            log_error "Streamer exited with unexpected code: $EXIT_CODE (runtime: ${RUNTIME}s)"
            log_info "Restarting in 10 seconds..."
            sleep 10
            ;;
    esac

    RESTART_COUNT=$((RESTART_COUNT + 1))

#    # Safety check - if too many crashes in a row, something is very wrong
#    if [ $TOTAL_CRASHES -ge 10 ]; then
#        log_error "Too many crashes ($TOTAL_CRASHES) - there may be a persistent issue"
#        log_error "Please check logs and fix the underlying problem"
#        log_info "Exiting restart loop for safety"
#        exit 1
#    fi

    echo ""
    log_info "=========================================="
    echo ""
done
