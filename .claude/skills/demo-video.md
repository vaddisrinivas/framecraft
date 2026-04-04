---
name: demo-video
description: Create polished demo videos from screenshots and scene descriptions using framecraft MCP tools
trigger: |
  When the user asks to create a demo video, product walkthrough, feature showcase,
  animated presentation, or marketing video from screenshots or UI captures.
  Trigger phrases: "make a video", "create a demo", "product video", "demo video",
  "animated walkthrough", "feature showcase", "record a demo".
---

# Demo Video Creation with framecraft

You have access to the `framecraft` MCP server with these tools:

## Tools

| Tool | When to use |
|------|-------------|
| `framecraft__get_scene_template` | Start here — get the full config schema with all fields |
| `framecraft__create_scene_html` | Generate and save a scene's HTML for manual inspection |
| `framecraft__preview_scene` | Render one scene to PNG — quick visual check before full render |
| `framecraft__render_video` | Render the full video (or a single scene with `scene_index`) |
| `framecraft__generate_tts` | Generate just the voiceover audio to test voice/pacing |
| `framecraft__list_voices` | Show available voices (edge-tts neural + macOS fallback) |

## Workflow

1. **Gather inputs**: What screenshots exist? What features to highlight? What tone?
2. **Get the template**: Call `get_scene_template` to see all available fields
3. **Design scenes**: Plan 5-8 scenes. For complex scenes, write custom HTML files.
4. **Preview key scenes**: Use `preview_scene` on the trickiest scene to check layout
5. **Render with auto-duration**: Use `render_video` with `auto_duration: true` so scenes match TTS length
6. **Iterate**: Use `scene_index` to re-render just the scene that needs fixing

## Scene Design Rules

- **Title card**: Product name + tagline, `animation: "fade"`, 3-4s
- **Problem scene**: Use `custom_html` with animated mockup showing the pain point
- **Feature scenes**: `title` + `screenshot` + `bullets` + optional `callouts` and `zoom`
- **End card**: Product name + URL + CTA, `animation: "fade"`, 4s

## Narration Rules

- 1-2 sentences per scene, max ~20 words
- Lead with benefit: "your tabs organize themselves" not "AI-powered tab grouping"
- Use `voice: "andrew"` (warm male) or `voice: "jenny"` (clear female)
- Per-scene `voice` overrides the global voice

## Key Features

- **Auto-duration**: Set `duration: 0` in scenes, pass `auto_duration: true` — framecraft generates TTS first, measures length, sets scene duration = audio + 1.5s buffer
- **Per-scene voice**: Different narrator per scene for variety
- **Custom HTML**: For complex animated scenes (browser mockups, animated diagrams), write standalone HTML files and reference via `custom_html`
- **Callouts**: Positioned annotation labels on screenshots: `{"text": "Click here", "x": 40, "y": 55, "color": "#4ade80", "delay": 1.5}`
- **Zoom**: Smooth zoom into a screenshot region: `{"x": 40, "y": 55, "scale": 1.8, "delay": 2.0, "duration": 1.0}`
- **Subtitles**: Set `subtitle_format: "srt"` to auto-generate subtitles from edge-tts word boundaries
- **Background music**: Set `background_music` path + `music_volume` (0.0-1.0)
- **Single scene render**: `scene_index: 2` renders just that scene for fast iteration

## Prerequisites

- ffmpeg installed
- Internet connection (for edge-tts neural voices)
- Playwright chromium (installed with `uv run playwright install chromium`)
