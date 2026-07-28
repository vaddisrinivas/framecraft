"""
framecraft — Create polished demo videos from screenshots + scene descriptions.

Pipeline: HTML scenes -> Playwright headless render -> ffmpeg composite + TTS voiceover

Usage as library:
    from framecraft import render_demo
    render_demo(config)

Usage as CLI:
    uv run python framecraft.py scenes.json
    uv run python framecraft.py scenes.json --scene 2        # render one scene only
    uv run python framecraft.py scenes.json --output demo.mp4
    uv run python framecraft.py scenes.json --auto-duration   # set duration from TTS length
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    x: int = 50          # % from left (0-100)
    y: int = 50          # % from top (0-100)
    color: str = "#7c6af5"
    delay: float = 1.0   # seconds before appearing
    side: str = "top"    # top | bottom | left | right — label position relative to point


@dataclass
class ZoomTarget:
    """Region to zoom into on a screenshot."""
    x: float = 50        # % from left (0-100)
    y: float = 50        # % from top (0-100)
    scale: float = 1.8   # zoom factor
    delay: float = 1.5   # seconds before zoom starts
    duration: float = 1.0 # zoom animation duration

    @classmethod
    def from_dict(cls, d: dict) -> "ZoomTarget":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Scene:
    """A single scene in the demo video."""
    title: str = ""
    subtitle: str = ""
    narration: str = ""
    voice: str = ""                    # per-scene voice override (empty = use config default)
    screenshot: str = ""               # path to screenshot image
    bullets: list[str] = field(default_factory=list)
    callouts: list[dict] = field(default_factory=list)  # list of Callout-like dicts
    duration: float = 0.0              # 0 = auto-detect from TTS, else fixed seconds
    bg_color: str = "#0d0e12"
    title_color: str = "#c5d5ff"
    subtitle_color: str = "#7c6af5"
    text_color: str = "#e2e4eb"
    accent_color: str = "#7c6af5"
    animation: str = "fade"            # fade | slide-up | scale | none
    screenshot_animation: str = "scale" # scale | fade | slide-up | none
    zoom: dict | None = None           # ZoomTarget-like dict, or None
    title_size: int = 48               # font-size for title
    layout: str = "center"             # center | left | split
    custom_html: str = ""              # path to custom HTML file (overrides all other visual fields)
    background_music: str = ""         # path to background music file for this scene

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
    voice: str = "andrew"              # default TTS voice
    transition: str = "crossfade"       # crossfade | cut
    transition_duration: float = 0.5
    background_music: str = ""          # global background music path
    music_volume: float = 0.15          # 0.0-1.0, relative to voiceover
    subtitle_format: str = ""           # "" = none, "srt" or "vtt"

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
        return asdict(self)


# ---------------------------------------------------------------------------
# Progress output
# ---------------------------------------------------------------------------

def _log(msg: str):
    print(f"  {msg}", flush=True)


def _progress(scene_idx: int, total_scenes: int, scene_name: str, detail: str = ""):
    label = f"[{scene_idx + 1}/{total_scenes}]"
    extra = f" — {detail}" if detail else ""
    print(f"  {label} {scene_name}{extra}", flush=True)


# ---------------------------------------------------------------------------
# HTML scene generator
# ---------------------------------------------------------------------------

def generate_scene_html(scene: Scene, width: int, height: int) -> str:
    """Generate a self-contained HTML file for one scene."""

    screenshot_html = ""
    if scene.screenshot:
        abs_path = os.path.abspath(scene.screenshot)

        zoom_css = ""
        if scene.zoom:
            z = ZoomTarget.from_dict(scene.zoom)
            zoom_css = f"""
            .screenshot-container {{
                animation: zoom-pan {z.duration}s cubic-bezier(0.25,1,0.5,1) {z.delay}s forwards;
                transform-origin: {z.x}% {z.y}%;
            }}
            @keyframes zoom-pan {{
                from {{ transform: scale(1); }}
                to {{ transform: scale({z.scale}); }}
            }}"""

        screenshot_html = f'''
        <div class="screenshot-container">
            <img class="screenshot {scene.screenshot_animation}" src="file://{abs_path}" />
        </div>
        <style>{zoom_css}</style>'''

    bullets_html = ""
    if scene.bullets:
        items = "".join(
            f'<span class="bullet bullet-{i}">{b}</span>'
            for i, b in enumerate(scene.bullets)
        )
        bullets_html = f'<div class="bullets">{items}</div>'

    callouts_html = ""
    callouts_css = ""
    if scene.callouts:
        parts_html = []
        parts_css = []
        for i, c in enumerate(scene.callouts):
            co = Callout(**{k: v for k, v in c.items() if k in Callout.__dataclass_fields__})
            # Position the callout label
            parts_html.append(
                f'<div class="callout callout-{i}" style="left:{co.x}%;top:{co.y}%">'
                f'<div class="callout-dot" style="background:{co.color}"></div>'
                f'<div class="callout-label" style="border-color:{co.color};color:{co.color}">{co.text}</div>'
                f'</div>'
            )
            parts_css.append(
                f'.callout-{i} {{ animation: callout-in 0.5s cubic-bezier(0.16,1,0.3,1) {co.delay}s forwards; }}'
            )
        callouts_html = '<div class="callouts-layer">' + ''.join(parts_html) + '</div>'
        callouts_css = '\n'.join(parts_css)

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
    position: relative;
  }}

  .title {{
    font-size: {scene.title_size}px;
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

  /* ── Callouts ── */
  .callouts-layer {{
    position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    pointer-events: none;
  }}
  .callout {{
    position: absolute; display: flex; align-items: center; gap: 8px;
    opacity: 0; transform: translateY(8px);
  }}
  .callout-dot {{
    width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
    box-shadow: 0 0 12px currentColor;
  }}
  .callout-label {{
    font-size: 14px; font-weight: 600; padding: 4px 12px;
    border: 1px solid; border-radius: 6px;
    background: rgba(0,0,0,0.7); backdrop-filter: blur(8px);
    white-space: nowrap;
  }}
  {callouts_css}

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
  @keyframes callout-in {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
</style>
</head>
<body>
  {"<h1 class='title'>" + scene.title + "</h1>" if scene.title else ""}
  {"<p class='subtitle'>" + scene.subtitle + "</p>" if scene.subtitle else ""}
  {screenshot_html}
  {bullets_html}
  {callouts_html}
</body>
</html>'''


# ---------------------------------------------------------------------------
# Renderer — Playwright headless -> PNG frames
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
    interval_ms = 1000 / fps

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"file://{os.path.abspath(html_path)}")

        # Wait for fonts + initial paint
        page.wait_for_timeout(300)

        for frame in range(total_frames):
            frame_path = os.path.join(output_dir, f"scene{scene_index:02d}-frame{frame:04d}.png")
            page.screenshot(path=frame_path)
            page.wait_for_timeout(int(interval_ms))

            # Progress every 30 frames
            if frame > 0 and frame % 30 == 0:
                _log(f"  frame {frame}/{total_frames}")

        browser.close()

    return total_frames


# ---------------------------------------------------------------------------
# TTS — edge-tts (natural neural voices) with macOS `say` fallback
# ---------------------------------------------------------------------------

EDGE_TTS_VOICES = {
    "guy": "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
    "davis": "en-US-DavisNeural",
    "amber": "en-US-AmberNeural",
    "andrew": "en-US-AndrewNeural",
    "emma": "en-US-EmmaNeural",
    "brian": "en-US-BrianNeural",
    "ryan": "en-GB-RyanNeural",
    "sonia": "en-GB-SoniaNeural",
}

DEFAULT_VOICE = "en-US-AndrewNeural"


def _resolve_voice(voice: str) -> str:
    """Resolve a short voice name to a full edge-tts voice ID."""
    if voice in EDGE_TTS_VOICES:
        return EDGE_TTS_VOICES[voice]
    if "-" in voice and "Neural" in voice:
        return voice
    return DEFAULT_VOICE


def get_audio_duration(path: str) -> float:
    """Get duration of an audio file in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def generate_voiceover(text: str, voice: str, output_path: str) -> str:
    """Generate voiceover audio. Uses edge-tts (neural voices) with macOS say fallback."""
    if not text.strip():
        return ""

    try:
        return _generate_edge_tts(text, voice, output_path)
    except Exception:
        pass

    try:
        return _generate_macos_say(text, voice, output_path)
    except Exception:
        return ""


def generate_voiceover_with_subtitles(
    text: str, voice: str, audio_path: str, subtitle_path: str, subtitle_format: str = "srt",
) -> str:
    """Generate voiceover + subtitle file using edge-tts word boundary events."""
    if not text.strip():
        return ""

    try:
        import asyncio
        import edge_tts

        resolved_voice = _resolve_voice(voice)
        mp3_path = audio_path.replace(".wav", ".mp3")

        async def _run():
            communicate = edge_tts.Communicate(text, resolved_voice)
            subs = edge_tts.SubMaker()
            with open(mp3_path, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        subs.feed(chunk)

            # Write subtitle file
            fmt = "srt" if subtitle_format == "srt" else "vtt"
            with open(subtitle_path, "w") as f:
                f.write(subs.generate_subs())

        asyncio.run(_run())

        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "1", audio_path],
            check=True, capture_output=True,
        )
        os.remove(mp3_path)
        return audio_path

    except Exception:
        # Fallback: generate audio without subtitles
        return generate_voiceover(text, voice, audio_path)


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

    subprocess.run(
        ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "1", output_path],
        check=True, capture_output=True,
    )
    os.remove(mp3_path)
    return output_path


def _generate_macos_say(text: str, voice: str, output_path: str) -> str:
    """Fallback: generate voiceover using macOS say."""
    aiff_path = output_path.replace(".wav", ".aiff")
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
    background_music: str = "",
    music_volume: float = 0.15,
    subtitle_file: str = "",
) -> str:
    """Stitch scene frames + audio into final MP4."""

    scene_videos = []
    tmp_dir = tempfile.mkdtemp(prefix="framecraft-")

    # Step 1: Render each scene's frames into individual scene videos
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

    # Step 2: Concat scenes
    if len(scene_videos) == 1 or transition == "cut":
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
        video_only = os.path.join(tmp_dir, "video_only.mp4")
        inputs = []
        for v in scene_videos:
            inputs += ["-i", v]

        filter_parts = []
        current = "[0:v]"
        for i in range(1, len(scene_videos)):
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

    # Step 3: Pad each voiceover to its rendered scene duration, then concat.
    # Raw narration is shorter than the visual scene because auto-duration adds
    # breathing room. Concatenating raw files makes `-shortest` truncate later
    # scenes during the final mux.
    valid_audio = [a for a in audio_files if a and os.path.exists(a)]
    narration_audio = ""
    if valid_audio:
        padded_audio = []
        for i, (audio, frame_count) in enumerate(zip(audio_files, scene_frame_counts)):
            scene_duration = frame_count / fps
            if transition != "cut" and i < len(scene_frame_counts) - 1:
                scene_duration = max(0.001, scene_duration - transition_duration)
            padded_path = os.path.join(tmp_dir, f"audio{i:02d}.wav")
            if audio and os.path.exists(audio):
                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", audio,
                    "-af", "apad",
                    "-t", f"{scene_duration:.6f}",
                    "-ar", "44100", "-ac", "1",
                    padded_path,
                ], check=True, capture_output=True)
            else:
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                    "-t", f"{scene_duration:.6f}",
                    padded_path,
                ], check=True, capture_output=True)
            padded_audio.append(padded_path)

        narration_audio = os.path.join(tmp_dir, "narration.wav")
        if len(padded_audio) == 1:
            shutil.copy(padded_audio[0], narration_audio)
        else:
            audio_list = os.path.join(tmp_dir, "audio_list.txt")
            with open(audio_list, "w") as f:
                for a in padded_audio:
                    f.write(f"file '{a}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", audio_list, narration_audio,
            ], check=True, capture_output=True)

    # Step 4: Mix background music if provided
    final_audio = ""
    if narration_audio and background_music and os.path.exists(background_music):
        final_audio = os.path.join(tmp_dir, "mixed_audio.wav")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", narration_audio,
            "-i", background_music,
            "-filter_complex",
            f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[out]",
            "-map", "[out]",
            final_audio,
        ], check=True, capture_output=True)
    elif narration_audio:
        final_audio = narration_audio

    # Step 5: Mux video + audio + optional subtitles
    if final_audio:
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", video_only,
            "-i", final_audio,
        ]
        if subtitle_file and os.path.exists(subtitle_file):
            mux_cmd += ["-i", subtitle_file]
            mux_cmd += [
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-c:s", "mov_text",
                "-shortest",
                output_path,
            ]
        else:
            mux_cmd += [
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                output_path,
            ]
        subprocess.run(mux_cmd, check=True, capture_output=True)
    else:
        shutil.copy(video_only, output_path)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return output_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

DEFAULT_SCENE_DURATION = 4.0
DURATION_BUFFER = 1.5  # seconds added to TTS duration


def render_demo(
    config: DemoConfig,
    scene_filter: int | None = None,
    auto_duration: bool = False,
) -> str:
    """Full pipeline: HTML -> frames -> voiceover -> composite -> MP4.

    Args:
        config: The full demo configuration
        scene_filter: If set, only render this scene index (0-based)
        auto_duration: If True, set scene duration from TTS audio length + buffer
    """
    start_time = time.time()
    work_dir = tempfile.mkdtemp(prefix="framecraft-work-")
    html_dir = os.path.join(work_dir, "html")
    frame_dir = os.path.join(work_dir, "frames")
    audio_dir = os.path.join(work_dir, "audio")
    sub_dir = os.path.join(work_dir, "subs")
    os.makedirs(html_dir)
    os.makedirs(frame_dir)
    os.makedirs(audio_dir)
    os.makedirs(sub_dir)

    scenes = config.scenes
    if scene_filter is not None:
        if scene_filter < 0 or scene_filter >= len(scenes):
            raise ValueError(f"Scene index {scene_filter} out of range (0-{len(scenes) - 1})")
        scenes = [scenes[scene_filter]]
        _log(f"Rendering scene {scene_filter} only")

    total = len(scenes)
    frame_counts = []
    audio_files = []
    all_subtitle_files = []

    for i, scene in enumerate(scenes):
        scene_idx = i  # always 0-based for frame file naming
        original_idx = scene_filter if scene_filter is not None else i
        scene_name = scene.title or (scene.custom_html.split("/")[-1] if scene.custom_html else f"Scene {original_idx}")

        # Resolve voice: per-scene override > config default
        voice = scene.voice or config.voice

        # 1. Generate voiceover FIRST (so we can measure duration)
        audio_path = ""
        subtitle_path = ""
        if scene.narration:
            _progress(i, total, scene_name, "generating voiceover")
            audio_path = os.path.join(audio_dir, f"scene{scene_idx:02d}.wav")
            subtitle_path = os.path.join(sub_dir, f"scene{scene_idx:02d}.srt")

            if config.subtitle_format:
                generate_voiceover_with_subtitles(
                    scene.narration, voice, audio_path, subtitle_path, config.subtitle_format,
                )
            else:
                generate_voiceover(scene.narration, voice, audio_path)

        # 2. Determine duration
        if auto_duration and audio_path and os.path.exists(audio_path):
            audio_dur = get_audio_duration(audio_path)
            if audio_dur > 0:
                scene.duration = audio_dur + DURATION_BUFFER
                _log(f"  auto-duration: {scene.duration:.1f}s (audio {audio_dur:.1f}s + {DURATION_BUFFER}s buffer)")
        if scene.duration <= 0:
            scene.duration = DEFAULT_SCENE_DURATION

        # 3. Generate HTML
        _progress(i, total, scene_name, "generating HTML")
        if scene.custom_html and os.path.exists(scene.custom_html):
            html_path = os.path.abspath(scene.custom_html)
        else:
            html_content = generate_scene_html(scene, config.width, config.height)
            html_path = os.path.join(html_dir, f"scene{scene_idx:02d}.html")
            with open(html_path, "w") as f:
                f.write(html_content)

        # 4. Render frames
        _progress(i, total, scene_name, f"rendering {int(scene.duration * config.fps)} frames")
        count = render_scene_frames(
            html_path, frame_dir,
            scene.duration, config.width, config.height, config.fps, scene_idx,
        )
        frame_counts.append(count)
        audio_files.append(audio_path if audio_path and os.path.exists(audio_path) else "")
        all_subtitle_files.append(subtitle_path if subtitle_path and os.path.exists(subtitle_path) else "")

    # 5. Composite
    _log("Compositing video...")
    output = os.path.abspath(config.output)

    # Merge subtitle files if any
    merged_subs = ""
    valid_subs = [s for s in all_subtitle_files if s]
    if valid_subs and config.subtitle_format:
        merged_subs = os.path.join(work_dir, f"subtitles.{config.subtitle_format}")
        # Simple concat — not time-aligned, but good enough for now
        with open(merged_subs, "w") as out:
            for s in valid_subs:
                with open(s) as f:
                    out.write(f.read())
                    out.write("\n")

    composite_video(
        [frame_dir] * len(scenes),
        frame_counts,
        audio_files,
        output,
        config.fps,
        config.width,
        config.height,
        config.transition,
        config.transition_duration,
        config.background_music,
        config.music_volume,
        merged_subs,
    )

    elapsed = time.time() - start_time
    duration = sum(s.duration for s in scenes)
    size_mb = os.path.getsize(output) / (1024 * 1024)
    _log(f"Done in {elapsed:.1f}s — {duration:.0f}s video, {size_mb:.1f}MB")

    shutil.rmtree(work_dir, ignore_errors=True)
    return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Init — scaffold a demo project from description
# ---------------------------------------------------------------------------

INIT_TEMPLATE = {
    "scenes": [
        {"title": "{{PRODUCT}}", "subtitle": "{{TAGLINE}}", "narration": "Introducing {{PRODUCT}}. {{TAGLINE}}.", "duration": 0, "animation": "fade"},
        {"title": "The Problem", "narration": "Describe the problem your users face.", "duration": 0, "animation": "slide-up"},
        {"title": "The Solution", "narration": "{{PRODUCT}} solves this by...", "screenshot": "./screenshots/feature1.png", "duration": 0, "animation": "scale"},
        {"title": "How It Works", "narration": "Here's how it works in practice.", "screenshot": "./screenshots/feature2.png", "bullets": ["Fast", "Simple", "Free"], "duration": 0, "animation": "slide-up"},
        {"title": "{{PRODUCT}}", "subtitle": "{{URL}}", "narration": "Try {{PRODUCT}} now. Open source and free.", "duration": 0, "animation": "fade"},
    ],
    "voice": "andrew", "fps": 24, "transition": "crossfade", "transition_duration": 0.4,
}


def init_project(directory: str, product: str = "My Product", tagline: str = "", url: str = "") -> str:
    """Scaffold a framecraft demo project directory."""
    os.makedirs(directory, exist_ok=True)
    os.makedirs(os.path.join(directory, "screenshots"), exist_ok=True)
    os.makedirs(os.path.join(directory, "scenes"), exist_ok=True)
    os.makedirs(os.path.join(directory, "output"), exist_ok=True)

    # Generate scenes.json with substituted values
    config = json.loads(json.dumps(INIT_TEMPLATE))
    config["output"] = os.path.join(directory, "output", "demo.mp4")

    raw = json.dumps(config, indent=2)
    raw = raw.replace("{{PRODUCT}}", product)
    raw = raw.replace("{{TAGLINE}}", tagline or f"The best way to do what {product} does")
    raw = raw.replace("{{URL}}", url or f"github.com/you/{product.lower().replace(' ', '-')}")

    scenes_path = os.path.join(directory, "scenes.json")
    with open(scenes_path, "w") as f:
        f.write(raw)

    # Copy scene.css for reference
    css_src = os.path.join(os.path.dirname(__file__), "assets", "scene.css")
    if os.path.exists(css_src):
        shutil.copy(css_src, os.path.join(directory, "scene.css"))

    return scenes_path


# ---------------------------------------------------------------------------
# Multi-format export
# ---------------------------------------------------------------------------

def export_all_formats(
    input_mp4: str,
    output_dir: str = "",
    width: int = 1920,
    height: int = 1080,
) -> dict[str, str]:
    """Export to multiple platform-optimized formats from a rendered MP4."""
    if not output_dir:
        output_dir = os.path.dirname(input_mp4) or "."

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_mp4))[0]
    outputs = {}

    # GitHub README GIF (640x360, 12fps, looped)
    gif_path = os.path.join(output_dir, f"{base}-github.gif")
    subprocess.run([
        "ffmpeg", "-y", "-i", input_mp4,
        "-vf", "fps=12,scale=640:360:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer",
        "-an", gif_path,
    ], check=True, capture_output=True)
    outputs["github_gif"] = gif_path

    # Twitter/X optimized (1280x720, max 60s, h264 baseline)
    twitter_path = os.path.join(output_dir, f"{base}-twitter.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", input_mp4,
        "-vf", f"scale=1280:720",
        "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.1",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        twitter_path,
    ], check=True, capture_output=True)
    outputs["twitter_mp4"] = twitter_path

    # LinkedIn (1920x1080, with burned-in subtitles if SRT exists)
    srt_path = input_mp4.replace(".mp4", ".srt")
    linkedin_path = os.path.join(output_dir, f"{base}-linkedin.mp4")
    if os.path.exists(srt_path):
        subprocess.run([
            "ffmpeg", "-y", "-i", input_mp4,
            "-vf", f"subtitles={srt_path}:force_style='FontSize=22,PrimaryColour=&HFFFFFF,BackColour=&H80000000,BorderStyle=4'",
            "-c:v", "libx264", "-crf", "20", "-c:a", "copy",
            linkedin_path,
        ], check=True, capture_output=True)
    else:
        shutil.copy(input_mp4, linkedin_path)
    outputs["linkedin_mp4"] = linkedin_path

    # Thumbnail (first frame after 2 seconds)
    thumb_path = os.path.join(output_dir, f"{base}-thumb.png")
    subprocess.run([
        "ffmpeg", "-y", "-i", input_mp4,
        "-ss", "2", "-frames:v", "1",
        thumb_path,
    ], check=True, capture_output=True)
    outputs["thumbnail"] = thumb_path

    return outputs


# ---------------------------------------------------------------------------
# Preview — open scene HTML in browser
# ---------------------------------------------------------------------------

def preview_scene_in_browser(html_path: str, width: int = 1920, height: int = 1080) -> None:
    """Open a scene HTML file in the default browser for preview."""
    abs_path = os.path.abspath(html_path)
    import webbrowser
    webbrowser.open(f"file://{abs_path}")


# ---------------------------------------------------------------------------
# Validator — check output video quality
# ---------------------------------------------------------------------------

def validate_video(path: str) -> dict:
    """Validate a rendered video. Returns dict with checks and overall pass/fail."""
    checks = {}

    if not os.path.exists(path):
        return {"exists": False, "passed": False, "checks": {}}

    checks["exists"] = True
    size = os.path.getsize(path)
    checks["size_bytes"] = size
    checks["size_ok"] = size > 10000  # > 10KB

    # Check video stream
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration,codec_name",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        video = json.loads(result.stdout).get("streams", [{}])[0]
        checks["has_video"] = bool(video.get("codec_name"))
        checks["video_codec"] = video.get("codec_name", "none")
        checks["width"] = int(video.get("width", 0))
        checks["height"] = int(video.get("height", 0))
        checks["video_duration"] = float(video.get("duration", 0))
        checks["resolution_ok"] = checks["width"] >= 1280 and checks["height"] >= 720
    except (json.JSONDecodeError, IndexError, ValueError):
        checks["has_video"] = False

    # Check audio stream
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,duration",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        audio = json.loads(result.stdout).get("streams", [{}])[0]
        checks["has_audio"] = bool(audio.get("codec_name"))
        checks["audio_codec"] = audio.get("codec_name", "none")
        checks["audio_duration"] = float(audio.get("duration", 0))
    except (json.JSONDecodeError, IndexError, ValueError):
        checks["has_audio"] = False

    # Check for black frames at start
    result = subprocess.run(
        ["ffmpeg", "-i", path, "-vf", "blackdetect=d=0.5:pix_th=0.1",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    black_frames = "black_start" in result.stderr
    checks["has_black_frames"] = black_frames

    # Overall pass
    checks["passed"] = all([
        checks.get("has_video"),
        checks.get("has_audio"),
        checks.get("size_ok"),
        checks.get("resolution_ok"),
        not checks.get("has_black_frames"),
    ])

    return checks


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

def _build_mcp_server():
    """Build and return the FastMCP server with all tools."""
    from mcp.server.fastmcp import FastMCP

    mcp_server = FastMCP(
        "framecraft",
        description="Create polished demo videos from screenshots and scene descriptions",
    )

    @mcp_server.tool()
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

    @mcp_server.tool()
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

    @mcp_server.tool()
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
        duration_total = sum(s.duration for s in config.scenes)

        return (
            f"Video rendered successfully!\n"
            f"  Output: {result}\n"
            f"  Scenes: {len(config.scenes)}\n"
            f"  Duration: ~{duration_total:.0f}s\n"
            f"  Resolution: {config.width}x{config.height}\n"
            f"  Size: {size_mb:.1f}MB"
        )

    @mcp_server.tool()
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
        dur = get_audio_duration(output_path)
        file_size = os.path.getsize(output_path)
        return f"Voiceover saved to: {output_path} ({file_size / 1024:.0f}KB, {dur:.1f}s)"

    @mcp_server.tool()
    def list_voices() -> str:
        """List available TTS voices for voiceover generation."""
        lines = ["Edge-TTS neural voices:"]
        for short, full in EDGE_TTS_VOICES.items():
            lines.append(f"  {short:12s} -> {full}")
        return "\n".join(lines)

    @mcp_server.tool()
    def get_scene_template() -> str:
        """Get a complete example scenes.json config to get started."""
        template = {
            "scenes": [
                {
                    "title": "Your Product",
                    "subtitle": "Tagline goes here",
                    "narration": "Introducing Your Product. The best way to do X.",
                    "duration": 0,
                    "animation": "fade",
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
            "width": 1920, "height": 1080, "fps": 24,
            "voice": "andrew",
            "transition": "crossfade",
            "transition_duration": 0.4,
        }
        return json.dumps(template, indent=2)

    @mcp_server.tool()
    def validate_video_output(video_path: str) -> str:
        """Validate a rendered video file for quality issues.

        Checks: video/audio streams exist, resolution, black frames, file size.

        Args:
            video_path: Absolute path to the MP4 file to validate
        """
        checks = validate_video(video_path)
        lines = []
        for k, v in checks.items():
            if k == "passed":
                continue
            lines.append(f"  {k}: {v}")
        passed = checks.get("passed", False)
        lines.append(f"\n  {'PASSED' if passed else 'FAILED'}")
        return "\n".join(lines)

    @mcp_server.tool()
    def mcp_init_project(
        directory: str,
        product: str = "My Product",
        tagline: str = "",
        url: str = "",
    ) -> str:
        """Scaffold a new framecraft demo project with scenes.json template.

        Args:
            directory: Path to create the project in
            product: Product name (used in template)
            tagline: Product tagline
            url: Product URL (GitHub, website, etc.)
        """
        path = init_project(directory, product, tagline, url)
        return (
            f"Project scaffolded: {directory}/\n"
            f"  scenes.json: {path}\n"
            f"  screenshots/  — drop your PNGs here\n"
            f"  scenes/       — custom HTML scenes go here\n"
            f"\nNext: edit scenes.json, add screenshots, then render."
        )

    @mcp_server.tool()
    def mcp_export_all_formats(video_path: str, output_dir: str = "") -> str:
        """Export a rendered video to multiple platform-optimized formats.

        Generates: GitHub GIF (640x360), Twitter MP4 (1280x720), LinkedIn MP4, thumbnail PNG.

        Args:
            video_path: Path to the rendered MP4
            output_dir: Directory for outputs (defaults to same as input)
        """
        outputs = export_all_formats(video_path, output_dir)
        lines = ["Exported formats:"]
        for platform, path in outputs.items():
            size = os.path.getsize(path) / 1024
            lines.append(f"  {platform}: {path} ({size:.0f}KB)")
        return "\n".join(lines)

    return mcp_server


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="framecraft — create demo videos from screenshots + scene descriptions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # render (default when just passing a config file)
    p_render = sub.add_parser("render", help="Render a demo video from scenes.json")
    p_render.add_argument("config", help="Path to scenes.json")
    p_render.add_argument("--output", "-o", help="Override output path")
    p_render.add_argument("--scene", "-s", type=int, help="Render one scene (0-based)")
    p_render.add_argument("--auto-duration", "-a", action="store_true", help="Set duration from TTS")

    # init
    p_init = sub.add_parser("init", help="Scaffold a new demo project")
    p_init.add_argument("directory", help="Project directory to create")
    p_init.add_argument("--product", "-p", default="My Product", help="Product name")
    p_init.add_argument("--tagline", "-t", default="", help="Product tagline")
    p_init.add_argument("--url", "-u", default="", help="Product URL")

    # validate
    p_validate = sub.add_parser("validate", help="Check a rendered video")
    p_validate.add_argument("video", help="Path to MP4 file")

    # export
    p_export = sub.add_parser("export", help="Export to multiple platform formats")
    p_export.add_argument("video", help="Path to rendered MP4")
    p_export.add_argument("--output-dir", "-d", default="", help="Output directory")

    # preview
    p_preview = sub.add_parser("preview", help="Open a scene HTML in browser")
    p_preview.add_argument("html", help="Path to scene HTML file")

    # serve (MCP server)
    sub.add_parser("serve", help="Start the framecraft MCP server (stdio transport)")

    args = parser.parse_args()

    # Backward compat: if no subcommand but first arg looks like a .json file, treat as render
    if not args.command:
        if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
            args.command = "render"
            args.config = sys.argv[1]
            args.output = None
            args.scene = None
            args.auto_duration = "--auto-duration" in sys.argv or "-a" in sys.argv
            for i, a in enumerate(sys.argv):
                if a in ("--output", "-o") and i + 1 < len(sys.argv):
                    args.output = sys.argv[i + 1]
                if a in ("--scene", "-s") and i + 1 < len(sys.argv):
                    args.scene = int(sys.argv[i + 1])
        else:
            parser.print_help()
            sys.exit(1)

    if args.command == "serve":
        server = _build_mcp_server()
        server.run(transport="stdio")
        sys.exit(0)

    if args.command == "init":
        path = init_project(args.directory, args.product, args.tagline, args.url)
        print(f"Project scaffolded: {args.directory}/")
        print(f"  scenes.json: {path}")
        print(f"  screenshots/  — drop your PNGs here")
        print(f"  scenes/       — custom HTML scenes go here")
        print(f"\nNext: edit scenes.json, then run:")
        print(f"  framecraft render {os.path.join(args.directory, 'scenes.json')} --auto-duration")

    elif args.command == "validate":
        print(f"Validating: {args.video}")
        result = validate_video(args.video)
        for k, v in result.items():
            if k == "passed":
                continue
            print(f"  {k}: {v}")
        print(f"\n  {'PASSED' if result.get('passed') else 'FAILED'}")
        sys.exit(0 if result.get("passed") else 1)

    elif args.command == "export":
        print(f"Exporting: {args.video}")
        outputs = export_all_formats(args.video, args.output_dir)
        for platform, path in outputs.items():
            size = os.path.getsize(path) / 1024
            print(f"  {platform}: {path} ({size:.0f}KB)")
        print(f"\n  {len(outputs)} formats exported")

    elif args.command == "preview":
        print(f"Opening: {args.html}")
        preview_scene_in_browser(args.html)

    elif args.command == "render":
        cfg = DemoConfig.from_json(args.config)
        if args.output:
            cfg.output = args.output

        print(f"framecraft — {len(cfg.scenes)} scenes @ {cfg.width}x{cfg.height} {cfg.fps}fps")
        result = render_demo(cfg, scene_filter=args.scene, auto_duration=args.auto_duration)
        print(f"Output: {result}")

        print("\nValidating...")
        checks = validate_video(result)
        for k, v in checks.items():
            if k == "passed":
                continue
            print(f"  {k}: {v}")
        print(f"\n  {'PASSED' if checks.get('passed') else 'FAILED'}")
