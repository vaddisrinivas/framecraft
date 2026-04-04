#!/bin/bash
# framecraft plugin — end-to-end test suite (MCP-only)
# Generates demos via Claude + MCPs, reviews via separate LLM session.
#
# Usage: bash test-plugin.sh
# Requires: claude CLI with framecraft plugin installed

set -uo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_DIR="$PLUGIN_DIR/.test-runs/$(date +%Y%m%d-%H%M%S)"
export PATH="/opt/homebrew/bin:/opt/homebrew/Cellar/ffmpeg/8.0_1/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
CLAUDE="$HOME/.local/bin/claude"
RESULTS_FILE="$TEST_DIR/results.md"
PASS=0
FAIL=0

mkdir -p "$TEST_DIR"

# ─── Colors ───
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[$1]${NC} $2"; }
pass() { echo -e "${GREEN}  ✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  ✗${NC} $1"; FAIL=$((FAIL + 1)); }

# ─── Test scenarios ───
# Each: NAME|PROMPT
SCENARIOS=(
  "password-manager|Make a 30-second demo video for a password manager browser extension called VaultKey. Show the autofill feature, password generator, and security dashboard. End with a GitHub CTA."
  "weather-app|Make a 20-second teaser video for a weather app called SkyPulse. Show the radar view, hourly forecast, and severe weather alerts. Modern dark UI."
  "cli-tool|Make a 30-second demo for a CLI tool called turbotest that runs tests 10x faster using parallel execution. Show before/after terminal comparisons and a speed benchmark."
  "note-taking|Make a 25-second demo for a note-taking app called ThinkPad. Show markdown editing, tag organization, and instant search. Minimal clean aesthetic."
  "api-monitor|Make a 20-second teaser for an API monitoring tool called PingCraft. Show the uptime dashboard, latency graphs, and alert configuration. Developer-focused."
)

cat > "$RESULTS_FILE" << 'HEADER'
# framecraft plugin test results

| # | Product | Generated | Validated | Duration | Size | Review Score | Notes |
|---|---------|-----------|-----------|----------|------|-------------|-------|
HEADER

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  framecraft plugin test suite (MCP-only)"
echo "  $(date)"
echo "  Output: $TEST_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── Step 1: Check prerequisites ───
log "SETUP" "Checking prerequisites..."

if [ ! -f "$CLAUDE" ]; then
  CLAUDE=$(which claude 2>/dev/null || echo "")
  if [ -z "$CLAUDE" ]; then
    fail "claude CLI not found"
    exit 1
  fi
fi
pass "claude CLI: $CLAUDE"

# ─── Step 2: Check plugin structure ───
log "PLUGIN" "Checking plugin files..."

for f in ".claude-plugin/plugin.json" ".mcp.json" "skills/demo-video/SKILL.md" "framecraft.py"; do
  if [ -f "$PLUGIN_DIR/$f" ]; then
    pass "$f"
  else
    fail "$f MISSING"
  fi
done

echo ""

# ─── Step 3: Generate + validate demos via Claude + MCPs ───
for i in "${!SCENARIOS[@]}"; do
  IFS='|' read -r NAME PROMPT <<< "${SCENARIOS[$i]}"
  NUM=$((i + 1))
  SCENE_DIR="$TEST_DIR/$NAME"
  OUTPUT="$SCENE_DIR/demo.mp4"

  mkdir -p "$SCENE_DIR"

  echo ""
  log "TEST $NUM/5" "Generating demo: $NAME"
  echo ""

  # Claude orchestrates everything via MCPs:
  # - framecraft skill triggers from the prompt
  # - LLM writes HTML scenes, narration, scenes.json
  # - Uses framecraft MCP to render_video (which uses playwright + edge-tts + ffmpeg internally)
  # - Uses framecraft MCP to validate_video_output
  GENERATION_PROMPT="$PROMPT

Save the output video to: $OUTPUT
After rendering, validate it using the framecraft validate_video_output tool.
At the very end, print a single line: RESULT: <PASS or FAIL> | <duration in seconds> | <file size in MB>
Do NOT ask questions. Just build it."

  if "$CLAUDE" -p \
    --no-session-persistence \
    --max-budget-usd 3 \
    --permission-mode bypassPermissions \
    --plugin-dir "$PLUGIN_DIR" \
    "$GENERATION_PROMPT" \
    > "$SCENE_DIR/generation.log" 2>&1; then
    pass "Claude session completed"
  else
    fail "Claude session failed — see $SCENE_DIR/generation.log"
    echo "| $NUM | $NAME | ✗ | - | - | - | - | Session failed |" >> "$RESULTS_FILE"
    continue
  fi

  # Parse the RESULT line from Claude's output
  RESULT_LINE=$(grep "RESULT:" "$SCENE_DIR/generation.log" | tail -1 || echo "")

  if [ -z "$RESULT_LINE" ]; then
    # Fallback: check if video file exists
    if [ -f "$OUTPUT" ]; then
      pass "Video file exists (no RESULT line parsed)"
      DURATION="?"
      SIZE_MB="?"
      VALID="?"
    else
      # Search for any mp4 in the scene dir
      FOUND_MP4=$(find "$SCENE_DIR" -name "*.mp4" -type f 2>/dev/null | head -1)
      if [ -n "$FOUND_MP4" ]; then
        OUTPUT="$FOUND_MP4"
        pass "Video found at: $(basename "$OUTPUT")"
        DURATION="?"
        SIZE_MB="?"
        VALID="?"
      else
        fail "No video output found"
        echo "| $NUM | $NAME | ✗ | - | - | - | - | No video output |" >> "$RESULTS_FILE"
        continue
      fi
    fi
  else
    # Parse: RESULT: PASS | 46 | 2.3
    VALID=$(echo "$RESULT_LINE" | cut -d'|' -f1 | sed 's/RESULT: //' | tr -d ' ')
    DURATION=$(echo "$RESULT_LINE" | cut -d'|' -f2 | tr -d ' ')
    SIZE_MB=$(echo "$RESULT_LINE" | cut -d'|' -f3 | tr -d ' ')

    if [ "$VALID" = "PASS" ]; then
      pass "Generated & validated: ${DURATION}s, ${SIZE_MB}MB"
      VALID="✓"
    else
      fail "Generated but validation failed"
      VALID="✗"
    fi
  fi

  # ─── Step 4: LLM review in separate session ───
  log "REVIEW" "Getting LLM review for $NAME..."

  # Send the generation log (which contains scene descriptions, narration, etc.) for review
  REVIEW_PROMPT="You are a video production reviewer. A demo video was generated for a product called '$NAME'.

Here is the full generation log showing what was built:

$(tail -200 "$SCENE_DIR/generation.log" 2>/dev/null)

The video is ${DURATION}s long, ${SIZE_MB}MB, 1920x1080 with voiceover.

Score this demo on a scale of 1-10 for each criterion. Be honest and critical.
Consider: Does the story arc make sense? Is the pacing right for the duration? Are the visuals creative or generic? Does the narration sound natural?

Respond in EXACTLY this format (no other text):
VISUAL: <1-10>
STORY: <1-10>
PACING: <1-10>
NARRATION: <1-10>
OVERALL: <1-10>
NOTES: <one line summary>"

  REVIEW=$("$CLAUDE" -p \
    --no-session-persistence \
    --model sonnet \
    --max-budget-usd 0.5 \
    "$REVIEW_PROMPT" 2>/dev/null || echo "OVERALL: ?
NOTES: Review failed")

  # Parse scores
  OVERALL=$(echo "$REVIEW" | grep -o 'OVERALL: [0-9]*' | grep -o '[0-9]*' || echo "?")
  NOTES=$(echo "$REVIEW" | grep 'NOTES:' | sed 's/NOTES: //' | tr -d '\n' || echo "No review")

  echo "$REVIEW" > "$SCENE_DIR/review.txt"

  if [ "$OVERALL" != "?" ]; then
    pass "Review score: $OVERALL/10 — $NOTES"
  else
    fail "Review failed — see $SCENE_DIR/review.txt"
    OVERALL="?"
    NOTES="Review failed"
  fi

  # Write results row
  echo "| $NUM | $NAME | ✓ | $VALID | ${DURATION}s | ${SIZE_MB}MB | $OVERALL/10 | $NOTES |" >> "$RESULTS_FILE"
done

# ─── Summary ───
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
echo "  Report: $RESULTS_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat "$RESULTS_FILE"
