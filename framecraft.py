"""
framecraft — Create polished demo videos from screenshots + scene descriptions.

Pipeline: HTML scenes → Playwright headless render → ffmpeg composite + TTS voiceover

Usage as library:
    from framecraft import render_demo
    render_demo(scenes, output_path="demo.mp4")

Usage as CLI:
    uv run python framecraft.py scenes.json --output demo.mp4
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Callout:
    """An annotation arrow/label pointing at a region of the screenshot."""
    text: str = ""
    x: int = 0           # % from left (0-100)
    y: int = 0           # % from top (0-100)
    color: str = "#7c6af5"
    delay: float = 1.0   # seconds before appearing


@dataclass
class Scene:
    """A single scene in the demo video."""
    title: str = ""
    subtitle: str = ""
    narration: str = ""
    screenshot: str = ""               # path to screenshot image
    bullets: list[str] = field(default_factory=list)
    callouts: list[dict] = field(default_factory=list)  # list of Callout-like dicts
    duration: float = 4.0              # seconds
    bg_color: str = "#0d0e12"
    title_color: str = "#c5d5ff"
    subtitle_color: str = "#7c6af5"
    text_color: str = "#e2e4eb"
    accent_color: str = "#7c6af5"
    animation: str = "fade"            # fade | slide-up | scale | none
    screenshot_animation: str = "scale" # scale | fade | slide-up | none
    zoom_to: str = ""                  # CSS region to zoom into: "x% y% scale" e.g. "50% 30% 1.5"
    title_size: int = 48               # font-size for title
    layout: str = "center"             # center | left | split

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DemoConfig:
    """Full demo video configuration."""
    scenes: list[Scene] = field(default_factory=list)
    output: str = "demo.mp4"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    voice: str = "Samantha"            # macOS TTS voice
    transition: str = "crossfade"       # crossfade | cut
    transition_duration: float = 0.5    # seconds

    @classmethod
    def from_dict(cls, d: dict) -> "DemoConfig":
        scenes = [Scene.from_dict(s) for s in d.get("scenes", [])]
        cfg = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "scenes"}
        return cls(scenes=scenes, **cfg)

    @classmethod
    def from_json(cls, path: str) -> "DemoConfig":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# HTML scene generator
# ---------------------------------------------------------------------------

def generate_scene_html(scene: Scene, width: int, height: int) -> str:
    """Generate a self-contained HTML file for one scene."""

    screenshot_html = ""
    if scene.screenshot:
        abs_path = os.path.abspath(scene.screenshot)
        screenshot_html = f'''
        <div class="screenshot-container">
            <img class="screenshot {scene.screenshot_animation}" src="file://{abs_path}" />
        </div>'''

    bullets_html = ""
    if scene.bullets:
        items = "".join(
            f'<span class="bullet bullet-{i}">{b}</span>'
            for i, b in enumerate(scene.bullets)
        )
        bullets_html = f'<div class="bullets">{items}</div>'

    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    width: {width}px;
    height: {height}px;
    overflow: hidden;
    background: {scene.bg_color};
    background-image:
      radial-gradient(ellipse at 20% 20%, rgba(124,106,245,0.15) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 80%, rgba(79,139,255,0.1) 0%, transparent 50%);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    padding-top: 60px;
  }}

  .title {{
    font-size: 48px;
    font-weight: 800;
    color: {scene.title_color};
    text-align: center;
    opacity: 0;
    animation: {scene.animation} 0.8s ease forwards;
    animation-delay: 0.1s;
  }}

  .subtitle {{
    font-size: 28px;
    font-weight: 400;
    color: {scene.subtitle_color};
    text-align: center;
    margin-top: 12px;
    opacity: 0;
    animation: {scene.animation} 0.8s ease forwards;
    animation-delay: 0.4s;
  }}

  .screenshot-container {{
    margin-top: 30px;
    display: flex;
    justify-content: center;
  }}

  .screenshot {{
    max-width: {int(width * 0.75)}px;
    max-height: {int(height * 0.65)}px;
    border-radius: 12px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.08);
    opacity: 0;
  }}

  .screenshot.scale {{
    animation: scale-in 1s cubic-bezier(0.16,1,0.3,1) forwards;
    animation-delay: 0.3s;
  }}
  .screenshot.fade {{
    animation: fade 1s ease forwards;
    animation-delay: 0.3s;
  }}
  .screenshot.slide-up {{
    animation: slide-up 1s cubic-bezier(0.16,1,0.3,1) forwards;
    animation-delay: 0.3s;
  }}
  .screenshot.none {{
    opacity: 1;
  }}

  .bullets {{
    display: flex;
    gap: 40px;
    margin-top: 30px;
    flex-wrap: wrap;
    justify-content: center;
    padding: 0 80px;
  }}

  .bullet {{
    font-size: 20px;
    font-weight: 600;
    color: {scene.accent_color};
    padding: 10px 24px;
    background: rgba(124,106,245,0.1);
    border: 1px solid rgba(124,106,245,0.2);
    border-radius: 10px;
    opacity: 0;
    animation: slide-up 0.6s cubic-bezier(0.16,1,0.3,1) forwards;
  }}

  .bullet-0 {{ animation-delay: 0.8s; color: #4ade80; background: rgba(74,222,128,0.1); border-color: rgba(74,222,128,0.2); }}
  .bullet-1 {{ animation-delay: 1.0s; color: #f28b82; background: rgba(242,139,130,0.1); border-color: rgba(242,139,130,0.2); }}
  .bullet-2 {{ animation-delay: 1.2s; color: #7c6af5; background: rgba(124,106,245,0.1); border-color: rgba(124,106,245,0.2); }}
  .bullet-3 {{ animation-delay: 1.4s; color: #4f8bff; background: rgba(79,139,255,0.1); border-color: rgba(79,139,255,0.2); }}

  @keyframes fade {{
    from {{ opacity: 0; }}
    to {{ opacity: 1; }}
  }}

  @keyframes slide-up {{
    from {{ opacity: 0; transform: translateY(30px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  @keyframes scale-in {{
    from {{ opacity: 0; transform: scale(0.92); }}
    to {{ opacity: 1; transform: scale(1); }}
  }}
</style>
</head>
<body>
  {"<h1 class='title'>" + scene.title + "</h1>" if scene.title else ""}
  {"<p class='subtitle'>" + scene.subtitle + "</p>" if scene.subtitle else ""}
  {screenshot_html}
  {bullets_html}
</body>
</html>'''


# ---------------------------------------------------------------------------
# Renderer — Playwright headless → PNG frames
# ---------------------------------------------------------------------------

def render_scene_frames(
    html_path: str,
    output_dir: str,
    duration: float,
    width: int,
    height: int,
    fps: int,
    scene_index: int,
) -> int:
    """Render an HTML scene to PNG frames using Playwright. Returns frame count."""
    from playwright.sync_api import sync_playwright

    total_frames = int(duration * fps)
    # We take snapshots at intervals, letting CSS animations play in real time
    interval_ms = 1000 / fps

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"file://{os.path.abspath(html_path)}")

        # Wait a tick for fonts to load
        page.wait_for_timeout(200)

        for frame in range(total_frames):
            frame_path = os.path.join(output_dir, f"scene{scene_index:02d}-frame{frame:04d}.png")
            page.screenshot(path=frame_path)
            page.wait_for_timeout(int(interval_ms))

        browser.close()

    return total_frames


# ---------------------------------------------------------------------------
# TTS — edge-tts (natural neural voices) with macOS `say` fallback
# ---------------------------------------------------------------------------

# Best edge-tts voices for demo narration
EDGE_TTS_VOICES = {
    # Natural, warm, professional
    "guy": "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
    "davis": "en-US-DavisNeural",
    "amber": "en-US-AmberNeural",
    "andrew": "en-US-AndrewNeural",
    "emma": "en-US-EmmaNeural",
    "brian": "en-US-BrianNeural",
    # British
    "ryan": "en-GB-RyanNeural",
    "sonia": "en-GB-SoniaNeural",
}

DEFAULT_VOICE = "en-US-AndrewNeural"


def _resolve_voice(voice: str) -> str:
    """Resolve a short voice name to a full edge-tts voice ID."""
    if voice in EDGE_TTS_VOICES:
        return EDGE_TTS_VOICES[voice]
    # If it looks like a full edge-tts voice ID, use as-is
    if "-" in voice and "Neural" in voice:
        return voice
    # Default
    return DEFAULT_VOICE


def generate_voiceover(text: str, voice: str, output_path: str) -> str:
    """Generate voiceover audio. Uses edge-tts (neural voices) with macOS say fallback."""
    if not text.strip():
        return ""

    # Try edge-tts first (natural neural voices)
    try:
        return _generate_edge_tts(text, voice, output_path)
    except Exception:
        pass

    # Fallback to macOS say
    try:
        return _generate_macos_say(text, voice, output_path)
    except Exception:
        return ""


def _generate_edge_tts(text: str, voice: str, output_path: str) -> str:
    """Generate voiceover using edge-tts (Microsoft neural voices)."""
    import asyncio
    import edge_tts

    resolved_voice = _resolve_voice(voice)
    mp3_path = output_path.replace(".wav", ".mp3")

    async def _run():
        communicate = edge_tts.Communicate(text, resolved_voice)
        await communicate.save(mp3_path)

    asyncio.run(_run())

    # Convert mp3 to wav for consistent ffmpeg pipeline
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "1", output_path],
        check=True, capture_output=True,
    )
    os.remove(mp3_path)
    return output_path


def _generate_macos_say(text: str, voice: str, output_path: str) -> str:
    """Fallback: generate voiceover using macOS say."""
    aiff_path = output_path.replace(".wav", ".aiff")
    # Map edge-tts voice names to macOS voices
    mac_voice = "Samantha"
    if "guy" in voice.lower() or "andrew" in voice.lower() or "davis" in voice.lower():
        mac_voice = "Daniel"

    subprocess.run(
        ["say", "-v", mac_voice, "-o", aiff_path, text],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", aiff_path, "-ar", "44100", "-ac", "1", output_path],
        check=True, capture_output=True,
    )
    os.remove(aiff_path)
    return output_path


# ---------------------------------------------------------------------------
# Compositor — ffmpeg
# ---------------------------------------------------------------------------

def composite_video(
    frame_dirs: list[str],
    scene_frame_counts: list[int],
    audio_files: list[str],
    output_path: str,
    fps: int,
    width: int,
    height: int,
    transition: str = "crossfade",
    transition_duration: float = 0.5,
) -> str:
    """Stitch scene frames + audio into final MP4."""

    # Step 1: Render each scene's frames into individual scene videos
    scene_videos = []
    tmp_dir = tempfile.mkdtemp(prefix="framecraft-")

    for i, (fdir, fcount) in enumerate(zip(frame_dirs, scene_frame_counts)):
        scene_mp4 = os.path.join(tmp_dir, f"scene{i:02d}.mp4")
        pattern = os.path.join(fdir, f"scene{i:02d}-frame%04d.png")
        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", pattern,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-vf", f"scale={width}:{height}",
            scene_mp4,
        ], check=True, capture_output=True)
        scene_videos.append(scene_mp4)

    # Step 2: Concat scenes (with crossfade transitions if configured)
    if len(scene_videos) == 1 or transition == "cut":
        # Simple concat
        concat_list = os.path.join(tmp_dir, "concat.txt")
        with open(concat_list, "w") as f:
            for v in scene_videos:
                f.write(f"file '{v}'\n")
        video_only = os.path.join(tmp_dir, "video_only.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            video_only,
        ], check=True, capture_output=True)
    else:
        # Build xfade filter chain
        video_only = os.path.join(tmp_dir, "video_only.mp4")
        inputs = []
        for v in scene_videos:
            inputs += ["-i", v]

        # Build complex filter for crossfade
        filter_parts = []
        current = "[0:v]"
        for i in range(1, len(scene_videos)):
            # Calculate offset: sum of previous scene durations minus transition overlap
            offset = sum(
                scene_frame_counts[j] / fps for j in range(i)
            ) - transition_duration * i
            offset = max(0, offset)
            next_label = f"[v{i}]"
            filter_parts.append(
                f"{current}[{i}:v]xfade=transition=fade:duration={transition_duration}:offset={offset:.3f}{next_label}"
            )
            current = next_label

        filter_str = ";".join(filter_parts)
        subprocess.run([
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", current,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            video_only,
        ], check=True, capture_output=True)

    # Step 3: Concat audio tracks if any
    valid_audio = [a for a in audio_files if a and os.path.exists(a)]
    if valid_audio:
        audio_concat = os.path.join(tmp_dir, "audio.wav")
        if len(valid_audio) == 1:
            shutil.copy(valid_audio[0], audio_concat)
        else:
            audio_list = os.path.join(tmp_dir, "audio_list.txt")
            with open(audio_list, "w") as f:
                for a in valid_audio:
                    f.write(f"file '{a}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", audio_list, audio_concat,
            ], check=True, capture_output=True)

        # Step 4: Mux video + audio
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_only,
            "-i", audio_concat,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            output_path,
        ], check=True, capture_output=True)
    else:
        shutil.copy(video_only, output_path)

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return output_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def render_demo(config: DemoConfig) -> str:
    """Full pipeline: HTML → frames → voiceover → composite → MP4."""
    work_dir = tempfile.mkdtemp(prefix="framecraft-work-")
    html_dir = os.path.join(work_dir, "html")
    frame_dir = os.path.join(work_dir, "frames")
    audio_dir = os.path.join(work_dir, "audio")
    os.makedirs(html_dir)
    os.makedirs(frame_dir)
    os.makedirs(audio_dir)

    frame_counts = []
    audio_files = []

    for i, scene in enumerate(config.scenes):
        # 1. Generate HTML
        html_content = generate_scene_html(scene, config.width, config.height)
        html_path = os.path.join(html_dir, f"scene{i:02d}.html")
        with open(html_path, "w") as f:
            f.write(html_content)

        # 2. Render frames
        count = render_scene_frames(
            html_path, frame_dir,
            scene.duration, config.width, config.height, config.fps, i,
        )
        frame_counts.append(count)

        # 3. Generate voiceover
        if scene.narration:
            audio_path = os.path.join(audio_dir, f"scene{i:02d}.wav")
            generate_voiceover(scene.narration, config.voice, audio_path)
            audio_files.append(audio_path)
        else:
            audio_files.append("")

    # 4. Composite
    output = os.path.abspath(config.output)
    composite_video(
        [frame_dir] * len(config.scenes),
        frame_counts,
        audio_files,
        output,
        config.fps,
        config.width,
        config.height,
        config.transition,
        config.transition_duration,
    )

    # Cleanup work dir
    shutil.rmtree(work_dir, ignore_errors=True)

    return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="framecraft — demo video from screenshots")
    parser.add_argument("config", help="Path to scenes.json config file")
    parser.add_argument("--output", "-o", help="Override output path")
    args = parser.parse_args()

    cfg = DemoConfig.from_json(args.config)
    if args.output:
        cfg.output = args.output

    print(f"Rendering {len(cfg.scenes)} scenes at {cfg.width}x{cfg.height} @ {cfg.fps}fps...")
    result = render_demo(cfg)
    print(f"Done: {result}")
