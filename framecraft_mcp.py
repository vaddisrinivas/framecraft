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
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from framecraft import (
    DemoConfig,
    Scene,
    generate_scene_html,
    generate_voiceover,
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
    bg_color: str = "#0d0e12",
    animation: str = "fade",
    width: int = 1920,
    height: int = 1080,
    output_path: str = "",
) -> str:
    """Generate a single HTML scene file with CSS animations.

    Use this to preview a scene before rendering the full video.
    Returns the path to the generated HTML file.

    Args:
        title: Main heading text
        subtitle: Secondary text below the title
        screenshot: Absolute path to a screenshot image to embed
        bullets: List of short text bullets displayed below the screenshot
        bg_color: Background color (hex)
        animation: Text animation type: fade, slide-up, scale, none
        width: Scene width in pixels
        height: Scene height in pixels
        output_path: Where to save the HTML file (auto-generated if empty)
    """
    scene = Scene(
        title=title,
        subtitle=subtitle,
        screenshot=screenshot,
        bullets=bullets or [],
        bg_color=bg_color,
        animation=animation,
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
    duration: float = 3.0,
    width: int = 1920,
    height: int = 1080,
    output_path: str = "",
) -> str:
    """Render a single scene to a PNG image (last frame) for quick preview.

    Use this to check how a scene looks before committing to a full video render.

    Args:
        title: Main heading text
        subtitle: Secondary text below the title
        screenshot: Absolute path to a screenshot image
        bullets: List of bullet text items
        duration: How long to let CSS animations play before capture (seconds)
        width: Scene width in pixels
        height: Scene height in pixels
        output_path: Where to save the preview PNG (auto-generated if empty)
    """
    scene = Scene(
        title=title, subtitle=subtitle, screenshot=screenshot,
        bullets=bullets or [], duration=duration,
    )
    html = generate_scene_html(scene, width, height)

    tmp_html = tempfile.mktemp(suffix=".html", prefix="framecraft-")
    with open(tmp_html, "w") as f:
        f.write(html)

    if not output_path:
        fd, output_path = tempfile.mkstemp(suffix=".png", prefix="framecraft-preview-")
        os.close(fd)

    # Render just the last frame
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
def render_video(scenes_json: str, output_path: str = "") -> str:
    """Render a full demo video from a scenes configuration.

    This is the main tool. Pass a JSON string describing all scenes, and it
    renders the complete video with animations, transitions, and voiceover.

    Args:
        scenes_json: JSON string with the full demo config. Schema:
            {
                "scenes": [
                    {
                        "title": "Your Title",
                        "subtitle": "Optional subtitle",
                        "narration": "Text that will be spoken as voiceover",
                        "screenshot": "/absolute/path/to/screenshot.png",
                        "bullets": ["Point 1", "Point 2"],
                        "duration": 4.0,
                        "bg_color": "#0d0e12",
                        "animation": "fade"
                    }
                ],
                "output": "demo.mp4",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "voice": "Samantha",
                "transition": "crossfade",
                "transition_duration": 0.5
            }
        output_path: Override the output path from the config
    """
    config = DemoConfig.from_dict(json.loads(scenes_json))
    if output_path:
        config.output = output_path

    result = render_demo(config)
    file_size = os.path.getsize(result)
    size_mb = file_size / (1024 * 1024)
    duration = sum(s.duration for s in config.scenes)

    return (
        f"Video rendered successfully!\n"
        f"  Output: {result}\n"
        f"  Scenes: {len(config.scenes)}\n"
        f"  Duration: {duration:.1f}s\n"
        f"  Resolution: {config.width}x{config.height}\n"
        f"  Size: {size_mb:.1f}MB"
    )


@mcp.tool()
def generate_tts(
    text: str,
    voice: str = "Samantha",
    output_path: str = "",
) -> str:
    """Generate voiceover audio from text using macOS TTS.

    Args:
        text: The narration text to speak
        voice: macOS voice name (Samantha, Daniel, etc.)
        output_path: Where to save the .wav file (auto-generated if empty)
    """
    if not output_path:
        fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="framecraft-tts-")
        os.close(fd)

    generate_voiceover(text, voice, output_path)
    file_size = os.path.getsize(output_path)
    return f"Voiceover saved to: {output_path} ({file_size / 1024:.0f}KB)"


@mcp.tool()
def list_voices() -> str:
    """List available macOS TTS voices for voiceover generation."""
    import subprocess
    result = subprocess.run(["say", "--voice=?"], capture_output=True, text=True)
    voices = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            lang = parts[1]
            voices.append(f"  {name:20s} {lang}")

    # Show first 30 voices
    return "Available voices:\n" + "\n".join(voices[:30])


@mcp.tool()
def get_scene_template() -> str:
    """Get a template scenes.json config to help you get started.

    Returns a complete example config that you can modify for your demo.
    """
    template = {
        "scenes": [
            {
                "title": "Your Product Name",
                "subtitle": "Tagline goes here",
                "narration": "Introducing Your Product. The best way to do X.",
                "duration": 4.0,
                "animation": "fade",
            },
            {
                "title": "Feature One",
                "screenshot": "/absolute/path/to/screenshot1.png",
                "narration": "Feature one does something amazing.",
                "bullets": ["Fast", "Reliable", "Free"],
                "duration": 5.0,
                "animation": "slide-up",
            },
            {
                "title": "Get Started",
                "subtitle": "github.com/you/project",
                "narration": "Try it now. Open source.",
                "duration": 4.0,
                "animation": "fade",
            },
        ],
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "voice": "Samantha",
        "transition": "crossfade",
        "transition_duration": 0.5,
    }
    return json.dumps(template, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
