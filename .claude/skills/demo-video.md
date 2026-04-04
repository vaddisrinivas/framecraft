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

- `framecraft__get_scene_template` — Get a starter config to understand the schema
- `framecraft__create_scene_html` — Generate and preview a single scene's HTML
- `framecraft__preview_scene` — Render a single scene to PNG for quick visual check
- `framecraft__render_video` — Render the full demo video (main tool)
- `framecraft__generate_tts` — Generate voiceover audio from text
- `framecraft__list_voices` — List available macOS TTS voices

## Workflow

1. **Gather inputs**: Ask what screenshots/images the user has, what features to highlight, and desired tone
2. **Design scenes**: Plan 5-8 scenes — title card, feature highlights (one per scene), end card
3. **Preview first scene**: Use `preview_scene` to check the look before full render
4. **Render video**: Use `render_video` with the complete scenes JSON config
5. **Iterate**: If the user wants changes, modify the config and re-render

## Scene Design Guidelines

- **Title card**: Big product name, tagline, fade-in animation, 3-4 seconds
- **Feature scenes**: Title + screenshot + 2-3 bullet callouts, 4-6 seconds each
- **Keep narration concise**: 1-2 sentences per scene, ~15 words max
- **Use varied animations**: Alternate between `fade`, `slide-up`, `scale`
- **End card**: Product name + URL + CTA, fade animation, 4 seconds

## Config Schema

```json
{
  "scenes": [
    {
      "title": "Heading text",
      "subtitle": "Secondary text",
      "narration": "Voiceover text (spoken by TTS)",
      "screenshot": "/absolute/path/to/image.png",
      "bullets": ["Point 1", "Point 2", "Point 3"],
      "duration": 4.0,
      "bg_color": "#0d0e12",
      "title_color": "#c5d5ff",
      "accent_color": "#7c6af5",
      "animation": "fade",
      "screenshot_animation": "scale"
    }
  ],
  "output": "/absolute/path/to/output.mp4",
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "voice": "Samantha",
  "transition": "crossfade",
  "transition_duration": 0.5
}
```

## Important

- All file paths in the config must be **absolute paths**
- Screenshots should be high-res PNGs (1280x800 or larger)
- Voiceover requires macOS with `say` command
- Video rendering requires `ffmpeg` installed
- Each scene renders at the configured fps — a 5-second scene at 30fps = 150 frames
- Total render time is roughly 2-3x the video duration
