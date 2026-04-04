# framecraft

Create polished demo videos from screenshots and scene descriptions.

**HTML scenes + Playwright headless render + ffmpeg composite + edge-tts neural voiceover**

## Quick start

```bash
git clone https://github.com/vaddisrinivas/framecraft.git
cd framecraft
uv sync
uv run playwright install chromium
uv run python framecraft.py examples/gtabs-demo.json --auto-duration
```

## How it works

```
scenes.json
  |
  |-- Per scene: generate HTML (CSS animations, screenshots, callouts, zoom)
  |-- Per scene: generate voiceover (edge-tts neural voices)
  |-- Per scene: render frames (Playwright headless Chrome @ 24-30fps)
  |
  '-- Composite: ffmpeg (crossfade transitions + audio mix + optional subtitles)
       |
       '-- Output: demo.mp4
```

## Features

| Feature | How |
|---------|-----|
| **Neural voiceover** | edge-tts (Microsoft neural voices) — free, no API key |
| **Per-scene voice** | `"voice": "jenny"` overrides the global default |
| **Auto-duration** | `--auto-duration` sets scene length from TTS audio + buffer |
| **Single scene render** | `--scene 2` renders just one scene for fast iteration |
| **Custom HTML scenes** | `"custom_html": "path.html"` for complex animated scenes |
| **Screenshot zoom** | Smooth CSS zoom into a region |
| **Callout annotations** | Positioned labels on screenshots with colored dots |
| **Background music** | Mix ambient track under voiceover at configurable volume |
| **Subtitles** | Auto-generated SRT from edge-tts word boundaries |
| **Crossfade transitions** | Smooth fade between scenes via ffmpeg xfade |
| **Progress output** | Per-scene status + frame count during render |

## Voices

| Name | Voice | Best for |
|------|-------|----------|
| `andrew` | en-US-AndrewNeural | Warm male, product demos |
| `jenny` | en-US-JennyNeural | Clear female, tutorials |
| `davis` | en-US-DavisNeural | Deep male, serious tone |
| `brian` | en-US-BrianNeural | Professional male |
| `emma` | en-US-EmmaNeural | Friendly female |
| `ryan` | en-GB-RyanNeural | British male |
| `sonia` | en-GB-SoniaNeural | British female |

Falls back to macOS `say` when edge-tts is unavailable.

## CLI

```bash
uv run python framecraft.py scenes.json                    # render all scenes
uv run python framecraft.py scenes.json --scene 2          # render only scene 2
uv run python framecraft.py scenes.json --auto-duration    # auto-detect from TTS
uv run python framecraft.py scenes.json -o demo.mp4        # override output
```

## MCP server

6 tools for Claude integration:

| Tool | Purpose |
|------|---------|
| `get_scene_template` | Get example config with all fields |
| `create_scene_html` | Generate one scene's HTML |
| `preview_scene` | Render one scene to PNG preview |
| `render_video` | Render full video (or single scene) |
| `generate_tts` | Generate voiceover audio |
| `list_voices` | Show available voices |

```bash
uv run python framecraft_mcp.py
```

Add to `~/.claude/settings.json`:

```json
"mcpServers": {
  "framecraft": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/framecraft", "python", "framecraft_mcp.py"]
  }
}
```

## Prerequisites

- Python 3.11+, ffmpeg, internet for edge-tts

## License

MIT
