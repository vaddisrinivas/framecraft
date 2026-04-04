# framecraft

A Claude skill + MCP config for creating demo videos. Stitches together existing tools — Playwright, ffmpeg, edge-tts — with a scene config format and reusable HTML templates.

**Not a framework.** A recipe that wires things together so the skill just works.

## What's in the box

```
framecraft/
  SKILL.md              <- The brain. Tells Claude how to make demo videos.
  mcp.json              <- Wires: playwright-mcp, ffmpeg-mcp, edge-tts-mcp
  framecraft.py         <- Atomic pipeline + validator (fallback when MCPs aren't available)
  framecraft_mcp.py     <- MCP server exposing pipeline as tools
  templates/            <- Reusable HTML scene patterns (title card, browser mockup, etc.)
  examples/             <- Real example: gTabs v0.4 demo config
  LEARNINGS.md          <- What we learned building this (for future improvement)
```

## How it works

Claude uses the skill description to orchestrate existing MCPs:

```
SKILL.md tells Claude:
  1. Write HTML scenes (CSS animations, screenshots, callouts)
  2. Use edge-tts MCP to generate voiceover
  3. Use playwright MCP to render HTML to frames
  4. Use ffmpeg MCP to composite video + audio

  OR: call framecraft pipeline for atomic one-shot render
```

## Quick start

### As a Claude skill (recommended)

1. Clone this repo
2. Add the MCPs from `mcp.json` to your Claude settings
3. The skill auto-triggers when you say "make a demo video"

### As a CLI

```bash
git clone https://github.com/vaddisrinivas/framecraft.git
cd framecraft
uv sync
uv run playwright install chromium

# Render
uv run python framecraft.py examples/gtabs-demo.json --auto-duration

# Render one scene
uv run python framecraft.py examples/gtabs-demo.json --scene 2

# Validate output
uv run python framecraft.py --validate output.mp4
```

## MCP dependencies

framecraft composes these existing MCPs (see `mcp.json`):

| MCP | What it does | Install |
|-----|-------------|---------|
| [playwright-mcp](https://github.com/microsoft/playwright-mcp) | Renders HTML to screenshots | `npx @playwright/mcp@latest` |
| [ffmpeg-mcp-lite](https://github.com/kevinwatt/ffmpeg-mcp-lite) | Video compositing, audio mixing | `uvx ffmpeg-mcp-lite` |
| [edge-tts-mcp](https://github.com/yuiseki/edge_tts_mcp_server) | Neural voiceover (free, no API key) | `uvx edge_tts_mcp_server` |

The `framecraft` MCP server itself is the fallback pipeline — does everything in one atomic call.

## Templates

Real HTML scenes from the [gTabs](https://github.com/vaddisrinivas/gtabs) demo:

| Template | What it shows |
|----------|--------------|
| `title-card.html` | Product name + tagline + version badge, gradient background |
| `browser-mockup.html` | Fake Chrome window with 24 messy tabs piling up |
| `browser-groups.html` | Same Chrome window with color-coded tab groups appearing |
| `end-card.html` | Logo + GitHub URL + CTA badges |

Copy, edit, use as `custom_html` in your scenes.json.

## Voices

| Name | Best for |
|------|----------|
| `andrew` | Warm male — product demos (default) |
| `jenny` | Clear female — tutorials |
| `davis` | Deep male — serious tone |
| `brian` | Professional male |
| `emma` | Friendly female |
| `ryan` | British male |

## Validation

After rendering, framecraft auto-validates:
- Has video stream + audio stream
- Resolution >= 1280x720
- No black frames at boundaries
- File size reasonable

```bash
uv run python framecraft.py --validate demo.mp4
```

## Built with gTabs

This tool was built while creating the demo video for [gTabs v0.4](https://github.com/vaddisrinivas/gtabs) — an AI tab organizer for Chrome. The `examples/` and `templates/` are from that real project.

## License

MIT
