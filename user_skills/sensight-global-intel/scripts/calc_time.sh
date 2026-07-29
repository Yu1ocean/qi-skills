#!/usr/bin/env bash
# Sensight Skill — timestamp helper
#
# Usage:
#   bash scripts/calc_time.sh [date]
#
# Date format: YYYY-MM-DD (defaults to today)
#
# Output formats used by different interfaces:
#   START_MS   — millisecond timestamp at 00:00:00 (ListPapers / ListBlogs)
#   END_MS     — millisecond timestamp at 23:59:59 (ListPapers / ListBlogs)
#   START_UNIX — Unix timestamp in seconds at 00:00:00 (social_search start_time)
#   END_UNIX   — Unix timestamp in seconds at 23:59:59 (social_search end_time)
#   START_FMT  — "YYYY-MM-DD 00:00:00" (retrieve start_time)
#   END_FMT    — "YYYY-MM-DD 23:59:59" (retrieve end_time)

set -euo pipefail

DATE="${1:-$(date +%Y-%m-%d)}"

# Compatible with macOS (BSD date) and Linux (GNU date)
if date --version &>/dev/null 2>&1; then
  START_UNIX=$(date -d "${DATE} 00:00:00" +%s)
else
  START_UNIX=$(date -j -f "%Y-%m-%d %H:%M:%S" "${DATE} 00:00:00" +%s)
fi

END_UNIX=$((START_UNIX + 86399))
START_MS=$((START_UNIX * 1000))
END_MS=$((END_UNIX * 1000))
START_FMT="${DATE} 00:00:00"
END_FMT="${DATE} 23:59:59"

cat <<EOF
Date: ${DATE}

ListPapers / ListBlogs (millisecond timestamps):
  start_time: ${START_MS}
  end_time:   ${END_MS}

social_search (Unix timestamps in seconds):
  start_time: ${START_UNIX}
  end_time:   ${END_UNIX}

retrieve (string format):
  start_time: "${START_FMT}"
  end_time:   "${END_FMT}"
EOF
