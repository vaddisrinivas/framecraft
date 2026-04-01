# framecraft

Demo video creation tool. HTML scenes + headless Chrome + ffmpeg + macOS TTS.

## Architecture

- `framecraft.py` — Core engine: HTML generation, Playwright frame rendering, ffmpeg compositing, TTS
- `framecraft_mcp.py` — MCP server exposing tools for Claude integration
- `.claude/skills/demo-video.md` — Claude skill for triggering video creation

## Running the MCP server

```bash
uv run python framecraft_mcp.py
```

## Running as CLI

```bash
uv run python framecraft.py scenes.json --output demo.mp4
```

## Prerequisites

- Python 3.11+
- ffmpeg (brew install ffmpeg)
- macOS `say` for TTS
- Playwright chromium (installed via `uv run playwright install chromium`)

## Pipeline

HTML scenes (CSS animations) → Playwright screenshots at 30fps → ffmpeg concat + crossfade → mix TTS audio → MP4
