# framecraft

LLM skill & plugin for demo video creation. Install the plugin, say "make a demo video", done.

## Architecture

- `skills/demo-video/SKILL.md` — The brain. Teaches the LLM story structure, visuals, narration.
- `.mcp.json` — Auto-configures all 4 MCP servers on plugin install.
- `framecraft.py` — Everything: pipeline, MCP server, CLI, validation, export.
- `templates/` — Reusable HTML scenes. Copy and customize.
- `examples/` — Real working config: gTabs v0.4 demo.

## Plugin install

```bash
claude plugin install framecraft
```

## MCP server

```bash
uv run python framecraft.py serve    # starts MCP server (stdio)
```

## CLI

```bash
uv run python framecraft.py render scenes.json --auto-duration
uv run python framecraft.py render scenes.json --scene 2
uv run python framecraft.py validate output.mp4
uv run python framecraft.py init my-demo
uv run python framecraft.py export output.mp4
```

## Prerequisites

- ffmpeg, Python 3.11+, internet for edge-tts
- Playwright chromium: `uv run playwright install chromium`
