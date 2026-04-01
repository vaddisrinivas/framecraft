---
name: framecraft
description: Create polished demo videos from screenshots and scene descriptions. Orchestrates playwright, ffmpeg, and edge-tts MCPs — or falls back to an atomic pipeline.
trigger: |
  When the user asks to create a demo video, product walkthrough, feature showcase,
  animated presentation, or marketing video from screenshots or UI captures.
  Phrases: "make a video", "create a demo", "product video", "demo video",
  "animated walkthrough", "feature showcase", "record a demo", "make a GIF".
---

# framecraft — Demo Video Skill

You create polished demo videos by orchestrating three things:
1. **HTML scenes** with CSS animations (you write these)
2. **Voiceover** from text (edge-tts neural voices)
3. **Video compositing** (ffmpeg stitches frames + audio)

## Available MCPs

Check which of these are available in your session. Use what's there, skip what's not.

| MCP | Tools you'd use | Purpose |
|-----|-----------------|---------|
| **playwright** | `browser_navigate`, `browser_screenshot` | Render HTML scenes to PNG frames |
| **ffmpeg** | `ffmpeg_convert`, `ffmpeg_merge`, `ffmpeg_extract_frames` | Composite frames into video, mix audio |
| **edge-tts** | TTS generation tools | Generate voiceover audio from text |
| **framecraft** | `render_video`, `preview_scene`, `generate_tts` | Atomic pipeline fallback — does everything in one call |

## Two Modes

### Mode A: MCP Orchestration (preferred when MCPs are available)
You call each MCP tool directly, giving you scene-by-scene control:

1. Write HTML scene file → save to disk
2. Use playwright MCP to open the HTML and take timed screenshots
3. Use edge-tts MCP to generate voiceover .mp3/.wav
4. Use ffmpeg MCP to stitch frames into video + mix audio

### Mode B: Pipeline Fallback (when framecraft MCP is available)
One call does everything:
```
framecraft.render_video(scenes_json, auto_duration=true)
```
Use this when you want reliability or the other MCPs aren't available.

### Mode C: CLI (always available via Bash)
```bash
cd /path/to/framecraft
uv run python framecraft.py scenes.json --auto-duration
uv run python framecraft.py scenes.json --scene 2        # one scene only
uv run python framecraft.py scenes.json --validate        # check output quality
```

## Workflow

1. **Gather inputs**: What screenshots exist? What features to highlight? What tone?
2. **Design 5-8 scenes**: Title card → problem → solution → features → CTA
3. **For each scene**: Write HTML (use templates below) OR provide a screenshot
4. **Generate voiceover**: 1-2 sentences per scene, max ~20 words each
5. **Render**: Either orchestrate MCPs or use the pipeline
6. **Validate**: Check output — has audio? correct duration? no black frames?

## Scene Config Format

```json
{
  "scenes": [
    {
      "title": "Heading text",
      "subtitle": "Secondary text",
      "narration": "Voiceover text spoken by TTS",
      "voice": "andrew",
      "screenshot": "/absolute/path/to/image.png",
      "bullets": ["Point 1", "Point 2"],
      "callouts": [{"text": "Look here", "x": 40, "y": 55, "color": "#4ade80", "delay": 1.5}],
      "zoom": {"x": 40, "y": 55, "scale": 1.8, "delay": 2.0, "duration": 1.0},
      "duration": 0,
      "animation": "fade",
      "custom_html": "/path/to/custom-scene.html"
    }
  ],
  "voice": "andrew",
  "fps": 24,
  "transition": "crossfade",
  "transition_duration": 0.4,
  "background_music": "/path/to/music.mp3",
  "music_volume": 0.15,
  "subtitle_format": "srt"
}
```

- `duration: 0` → auto-detect from TTS audio length + 1.5s buffer
- `custom_html` → overrides all visual fields, you provide the full HTML
- `voice` per scene → overrides global voice
- `callouts` → positioned annotation labels on screenshots
- `zoom` → smooth CSS zoom into a screenshot region

## Voice Options

| Name | ID | Best for |
|------|----|----------|
| `andrew` | en-US-AndrewNeural | Warm male — product demos (default) |
| `jenny` | en-US-JennyNeural | Clear female — tutorials |
| `davis` | en-US-DavisNeural | Deep male — serious tone |
| `brian` | en-US-BrianNeural | Professional male |
| `emma` | en-US-EmmaNeural | Friendly female |
| `ryan` | en-GB-RyanNeural | British male |
| `sonia` | en-GB-SoniaNeural | British female |

## HTML Scene Templates

The `templates/` directory has reusable HTML patterns. Copy and customize them:

### `templates/title-card.html`
Big centered title + subtitle + optional version badge. Dark gradient background.
- Edit: title text, subtitle, colors, badge text

### `templates/screenshot-scene.html`
Title + screenshot + optional bullet callouts below. Screenshot has box-shadow and entrance animation.
- Edit: title, screenshot path, bullets, colors

### `templates/browser-mockup.html`
Fake Chrome window with animated tab groups. Tabs appear in staggered colored groups.
- Edit: group names, colors, tab names, timing

### `templates/end-card.html`
Logo + URL + CTA + stat badges. Centered, minimal.
- Edit: product name, URL, badge text

## Scene Design Rules

- **Title card**: Product name + tagline, `fade` animation, 3-4s
- **Problem scene**: Use `custom_html` with animated mockup showing the pain point
- **Solution scene**: Use `custom_html` with animated result (e.g., organized tabs)
- **Feature scenes**: `title` + `screenshot` + `bullets`, 5-7s each
- **End card**: Product name + URL + CTA, 4s

## Narration Rules

- 1-2 sentences per scene, max ~20 words
- Lead with benefit: "your tabs organize themselves" not "AI-powered tab grouping"
- Use pauses naturally — commas and periods matter for TTS pacing
- Match scene duration to narration length (or use `duration: 0` for auto)

## Validation

After rendering, verify:
- `ffprobe output.mp4` — has video AND audio streams
- Audio duration roughly matches video duration
- No black frames at scene boundaries
- File size is reasonable (1-5MB for 30s 1080p)

Use `framecraft.py --validate output.mp4` or check manually with ffprobe.
