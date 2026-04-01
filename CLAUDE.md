# framecraft

Claude skill + MCP config for demo video creation. Not a framework — stitches existing tools together.

## Architecture

- `SKILL.md` — The brain. Tells Claude the workflow, scene format, and voice options.
- `mcp.json` — Declares MCP dependencies: playwright, ffmpeg, edge-tts.
- `framecraft.py` — Atomic pipeline + validator. Fallback when MCPs aren't available.
- `framecraft_mcp.py` — MCP server wrapping the pipeline as tools.
- `templates/` — Reusable HTML scenes (from gTabs demo). Copy and customize.
- `examples/` — Real working config: gTabs v0.4 demo.

## Two modes

1. **Claude-driven**: Skill tells Claude to orchestrate playwright-mcp + ffmpeg-mcp + edge-tts-mcp directly.
2. **Pipeline fallback**: `uv run python framecraft.py scenes.json --auto-duration` does everything atomically.

## CLI

```bash
uv run python framecraft.py scenes.json                  # render all
uv run python framecraft.py scenes.json --scene 2        # one scene
uv run python framecraft.py scenes.json --auto-duration  # duration from TTS
uv run python framecraft.py --validate output.mp4        # check quality
```

## Prerequisites

- ffmpeg, Python 3.11+, internet for edge-tts
- Playwright chromium: `uv run playwright install chromium`
