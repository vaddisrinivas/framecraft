"""
framecraft MCP server — expose demo video creation tools to Claude.

Run:
    uv run python framecraft_mcp.py

Configure in Claude settings.json:
    "mcpServers": {
        "framecraft": {
            "command": "uv",
            "args": ["run", "--directory", "/path/to/framecraft", "python", "framecraft_mcp.py"]
        }
    }
"""

from __future__ import annotations

import json
import os
import tempfile

from mcp.server.fastmcp import FastMCP

from framecraft import (
    DemoConfig,
    Scene,
    EDGE_TTS_VOICES,
    generate_scene_html,
    generate_voiceover,
    get_audio_duration,
    render_demo,
    render_scene_frames,
)

mcp = FastMCP(
    "framecraft",
    description="Create polished demo videos from screenshots and scene descriptions",
)


@mcp.tool()
def create_scene_html(
    title: str = "",
    subtitle: str = "",
    screenshot: str = "",
    bullets: list[str] | None = None,
    callouts: list[dict] | None = None,
    zoom: dict | None = None,
    bg_color: str = "#0d0e12",
    animation: str = "fade",
    title_size: int = 48,
    width: int = 1920,
    height: int = 1080,
    output_path: str = "",
) -> str:
    """Generate a single HTML scene file with CSS animations.

    Use this to preview a scene before rendering the full video.

    Args:
        title: Main heading text
        subtitle: Secondary text below the title
        screenshot: Absolute path to a screenshot image to embed
        bullets: List of short text bullets displayed below the screenshot
        callouts: List of callout dicts with keys: text, x (%), y (%), color, delay (s)
        zoom: Zoom target dict with keys: x (%), y (%), scale, delay (s), duration (s)
        bg_color: Background color (hex)
        animation: Text animation type: fade, slide-up, scale, none
        title_size: Title font size in pixels
        width: Scene width in pixels
        height: Scene height in pixels
        output_path: Where to save the HTML file (auto-generated if empty)
    """
    scene = Scene(
        title=title, subtitle=subtitle, screenshot=screenshot,
        bullets=bullets or [], callouts=callouts or [], zoom=zoom,
        bg_color=bg_color, animation=animation, title_size=title_size,
    )
    html = generate_scene_html(scene, width, height)

    if not output_path:
        fd, output_path = tempfile.mkstemp(suffix=".html", prefix="framecraft-scene-")
        os.close(fd)

    with open(output_path, "w") as f:
        f.write(html)

    return f"Scene HTML saved to: {output_path}"


@mcp.tool()
def preview_scene(
    title: str = "",
    subtitle: str = "",
    screenshot: str = "",
    bullets: list[str] | None = None,
    callouts: list[dict] | None = None,
    zoom: dict | None = None,
    duration: float = 3.0,
    width: int = 1920,
    height: int = 1080,
    output_path: str = "",
) -> str:
    """Render a single scene to a PNG image (final frame) for quick preview.

    Use this to check how a scene looks before committing to a full video render.

    Args:
        title: Main heading text
        subtitle: Secondary text
        screenshot: Absolute path to a screenshot image
        bullets: List of bullet text items
        callouts: List of callout annotation dicts
        zoom: Zoom target dict
        duration: Seconds to let CSS animations play before capture
        width: Scene width in pixels
        height: Scene height in pixels
        output_path: Where to save the preview PNG (auto-generated if empty)
    """
    scene = Scene(
        title=title, subtitle=subtitle, screenshot=screenshot,
        bullets=bullets or [], callouts=callouts or [], zoom=zoom,
        duration=duration,
    )
    html = generate_scene_html(scene, width, height)

    tmp_html = tempfile.mktemp(suffix=".html", prefix="framecraft-")
    with open(tmp_html, "w") as f:
        f.write(html)

    if not output_path:
        fd, output_path = tempfile.mkstemp(suffix=".png", prefix="framecraft-preview-")
        os.close(fd)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"file://{os.path.abspath(tmp_html)}")
        page.wait_for_timeout(int(duration * 1000))
        page.screenshot(path=output_path)
        browser.close()

    os.remove(tmp_html)
    return f"Preview saved to: {output_path}"


@mcp.tool()
def render_video(
    scenes_json: str,
    output_path: str = "",
    scene_index: int = -1,
    auto_duration: bool = False,
) -> str:
    """Render a full demo video from a scenes configuration.

    This is the main tool. Pass a JSON string describing all scenes.

    Args:
        scenes_json: JSON string with the full demo config. Schema:
            {
                "scenes": [
                    {
                        "title": "Heading",
                        "subtitle": "Optional subtitle",
                        "narration": "Voiceover text",
                        "voice": "andrew",
                        "screenshot": "/path/to/image.png",
                        "bullets": ["Point 1", "Point 2"],
                        "callouts": [{"text": "Look here", "x": 50, "y": 30, "color": "#4ade80", "delay": 1.0}],
                        "zoom": {"x": 50, "y": 30, "scale": 1.8, "delay": 1.5, "duration": 1.0},
                        "duration": 0,
                        "custom_html": "/path/to/custom.html",
                        "animation": "fade"
                    }
                ],
                "voice": "andrew",
                "background_music": "/path/to/music.mp3",
                "music_volume": 0.15,
                "subtitle_format": "srt",
                "transition": "crossfade",
                "transition_duration": 0.5
            }

            Duration 0 = auto-detect from TTS length when auto_duration is true.
            Per-scene voice overrides the global voice.
            custom_html overrides all visual fields for that scene.

        output_path: Override the output path from the config
        scene_index: If >= 0, render only this scene (0-based). -1 = all scenes.
        auto_duration: Set scene duration automatically from TTS audio length + buffer
    """
    config = DemoConfig.from_dict(json.loads(scenes_json))
    if output_path:
        config.output = output_path

    sf = scene_index if scene_index >= 0 else None
    result = render_demo(config, scene_filter=sf, auto_duration=auto_duration)

    file_size = os.path.getsize(result)
    size_mb = file_size / (1024 * 1024)
    duration = sum(s.duration for s in config.scenes)

    return (
        f"Video rendered successfully!\n"
        f"  Output: {result}\n"
        f"  Scenes: {len(config.scenes)}\n"
        f"  Duration: ~{duration:.0f}s\n"
        f"  Resolution: {config.width}x{config.height}\n"
        f"  Size: {size_mb:.1f}MB"
    )


@mcp.tool()
def generate_tts(
    text: str,
    voice: str = "andrew",
    output_path: str = "",
) -> str:
    """Generate voiceover audio from text using edge-tts neural voices.

    Args:
        text: The narration text to speak
        voice: Voice name — short names: andrew, jenny, davis, brian, emma, aria, guy, ryan, sonia.
               Or full edge-tts ID like en-US-AndrewNeural.
        output_path: Where to save the .wav file (auto-generated if empty)
    """
    if not output_path:
        fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="framecraft-tts-")
        os.close(fd)

    generate_voiceover(text, voice, output_path)
    duration = get_audio_duration(output_path)
    file_size = os.path.getsize(output_path)
    return f"Voiceover saved to: {output_path} ({file_size / 1024:.0f}KB, {duration:.1f}s)"


@mcp.tool()
def list_voices() -> str:
    """List available TTS voices for voiceover generation.

    Returns edge-tts neural voice shortnames and their full IDs, plus macOS say voices.
    """
    lines = ["Edge-TTS neural voices (recommended):"]
    for short, full in EDGE_TTS_VOICES.items():
        lines.append(f"  {short:12s} -> {full}")

    lines.append("\nMacOS say voices (fallback, robotic):")
    import subprocess
    result = subprocess.run(["say", "--voice=?"], capture_output=True, text=True)
    for line in result.stdout.strip().split("\n")[:10]:
        parts = line.split()
        if len(parts) >= 2:
            lines.append(f"  {parts[0]:12s} {parts[1]}")

    return "\n".join(lines)


@mcp.tool()
def get_scene_template() -> str:
    """Get a complete example scenes.json config to get started.

    Shows all available fields including callouts, zoom, per-scene voice,
    background music, and subtitle generation.
    """
    template = {
        "scenes": [
            {
                "title": "Your Product",
                "subtitle": "Tagline goes here",
                "narration": "Introducing Your Product. The best way to do X.",
                "duration": 0,
                "animation": "fade",
                "_comment": "duration 0 = auto-detect from TTS with --auto-duration",
            },
            {
                "title": "Feature Highlight",
                "screenshot": "/absolute/path/to/screenshot.png",
                "narration": "This feature does something amazing.",
                "voice": "jenny",
                "bullets": ["Fast", "Reliable", "Free"],
                "callouts": [
                    {"text": "Click here", "x": 40, "y": 55, "color": "#4ade80", "delay": 1.5},
                ],
                "zoom": {"x": 40, "y": 55, "scale": 1.8, "delay": 2.0, "duration": 1.0},
                "duration": 6.0,
                "animation": "slide-up",
                "screenshot_animation": "scale",
            },
            {
                "custom_html": "/absolute/path/to/custom-scene.html",
                "narration": "Custom scenes let you use any HTML/CSS.",
                "duration": 5.0,
                "_comment": "custom_html overrides all visual fields",
            },
            {
                "title": "Get Started",
                "subtitle": "github.com/you/project",
                "narration": "Try it now. Open source.",
                "duration": 4.0,
                "animation": "fade",
            },
        ],
        "output": "/absolute/path/to/output.mp4",
        "width": 1920,
        "height": 1080,
        "fps": 24,
        "voice": "andrew",
        "transition": "crossfade",
        "transition_duration": 0.4,
        "background_music": "",
        "music_volume": 0.15,
        "subtitle_format": "",
    }
    return json.dumps(template, indent=2)


@mcp.tool()
def validate_video_output(video_path: str) -> str:
    """Validate a rendered video file for quality issues.

    Checks: video/audio streams exist, resolution, black frames, file size.

    Args:
        video_path: Absolute path to the MP4 file to validate
    """
    from framecraft import validate_video
    checks = validate_video(video_path)
    lines = []
    for k, v in checks.items():
        if k == "passed":
            continue
        lines.append(f"  {k}: {v}")
    passed = checks.get("passed", False)
    lines.append(f"\n  {'PASSED' if passed else 'FAILED'}")
    return "\n".join(lines)


@mcp.tool()
def init_project(
    directory: str,
    product: str = "My Product",
    tagline: str = "",
    url: str = "",
) -> str:
    """Scaffold a new framecraft demo project with scenes.json template.

    Creates directory structure with placeholder scenes.json, screenshots/ folder,
    and scene.css reference.

    Args:
        directory: Path to create the project in
        product: Product name (used in template)
        tagline: Product tagline
        url: Product URL (GitHub, website, etc.)
    """
    from framecraft import init_project as _init
    path = _init(directory, product, tagline, url)
    return (
        f"Project scaffolded: {directory}/\n"
        f"  scenes.json: {path}\n"
        f"  screenshots/  — drop your PNGs here\n"
        f"  scenes/       — custom HTML scenes go here\n"
        f"\nNext: edit scenes.json, add screenshots, then render."
    )


@mcp.tool()
def export_all_formats(video_path: str, output_dir: str = "") -> str:
    """Export a rendered video to multiple platform-optimized formats.

    Generates: GitHub GIF (640x360), Twitter MP4 (1280x720), LinkedIn MP4, thumbnail PNG.

    Args:
        video_path: Path to the rendered MP4
        output_dir: Directory for outputs (defaults to same as input)
    """
    from framecraft import export_all_formats as _export
    outputs = _export(video_path, output_dir)
    lines = ["Exported formats:"]
    for platform, path in outputs.items():
        import os
        size = os.path.getsize(path) / 1024
        lines.append(f"  {platform}: {path} ({size:.0f}KB)")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
