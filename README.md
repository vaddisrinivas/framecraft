# framecraft

An LLM skill & plugin for creating polished demo videos. You describe what you want — your LLM writes the HTML scenes, narration, and config, then framecraft renders everything.

**Not a framework.** A pipeline that gives your LLM the tools to produce real video.

[![framecraft demo](output/framecraft-demo-preview.gif)](https://github.com/vaddisrinivas/framecraft/releases/download/v0.5-demo/framecraft-demo.mp4)

> *This demo was made with framecraft itself — one prompt, zero screen recording. [Watch with audio](https://github.com/vaddisrinivas/framecraft/releases/download/v0.5-demo/framecraft-demo.mp4).*

## How it works

```
You: "Make a demo video for my tab organizer extension"

Your LLM:
  1. Writes custom HTML scenes (CSS animations, gradients, mockups)
  2. Writes narration for each scene
  3. Generates voiceover via edge-tts (free, no API key)
  4. Captures frames via Playwright
  5. Composites video + audio via ffmpeg
  6. Validates the output

You get: a polished 1920x1080 demo video with voiceover and transitions.
```

framecraft provides the pipeline, templates, and validation. Your LLM does the creative work.

## What's in the box

```
framecraft/
  SKILL.md              <- The brain. Tells your LLM how to produce demo videos.
  mcp.json              <- Wires: playwright-mcp, ffmpeg-mcp, edge-tts-mcp
  framecraft.py         <- Atomic pipeline + validator (fallback when MCPs aren't available)
  framecraft_mcp.py     <- MCP server exposing pipeline as tools
  templates/            <- Reusable HTML scene patterns (title card, browser mockup, etc.)
  examples/             <- Real example: gTabs v0.4 demo config
  scenes/               <- Self-demo: framecraft's own demo video scenes
  LEARNINGS.md          <- What we learned building this
```

## Quick start

### As an LLM skill or plugin (recommended)

1. Clone this repo
2. Add the MCPs from `mcp.json` to your LLM's settings
3. The skill auto-triggers when you say "make a demo video"

Your LLM reads `SKILL.md`, understands the scene format, writes everything, and calls the pipeline.

### As a CLI

```bash
git clone https://github.com/vaddisrinivas/framecraft.git
cd framecraft
uv sync
uv run playwright install chromium

# Render a demo
uv run python framecraft.py render scenes.json --auto-duration

# Render one scene (iterate fast)
uv run python framecraft.py render scenes.json --scene 2

# Scaffold a new project
uv run python framecraft.py init my-demo

# Validate output
uv run python framecraft.py validate output.mp4

# Preview a scene in browser
uv run python framecraft.py preview scenes/title.html

# Export to multiple platforms
uv run python framecraft.py export output.mp4
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

10 neural voices via edge-tts — free, no API key:

| Name | Accent | Best for |
|------|--------|----------|
| `andrew` | US | Warm, conversational — product demos (default) |
| `jenny` | US | Clear, upbeat — tutorials |
| `davis` | US | Deep, authoritative — serious tone |
| `brian` | US | Professional, measured |
| `emma` | US | Friendly, enthusiastic |
| `aria` | US | Expressive, natural |
| `guy` | US | Casual, relaxed |
| `amber` | US | Warm, approachable |
| `ryan` | British | Polished — premium positioning |
| `sonia` | British | Professional, clear |

## Validation

After rendering, framecraft auto-validates:
- Has video stream + audio stream
- Resolution >= 1280x720
- No black frames at boundaries
- File size reasonable

```bash
uv run python framecraft.py validate demo.mp4
```

## Self-demo

The `scenes/framecraft-demo/` directory contains the scenes used to create framecraft's own demo video — a working example of custom HTML scenes with portal animations, chat mockups, pipeline diagrams, and meta self-reference.

```bash
uv run python framecraft.py render scenes/framecraft-demo/scenes.json --auto-duration
```

## Origin

framecraft was built while creating the demo video for [gTabs v0.4](https://github.com/vaddisrinivas/gtabs). The `examples/` and `templates/` come from that project.

## License

MIT
