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

    # Step 3: Concat voiceover audio
    valid_audio = [a for a in audio_files if a and os.path.exists(a)]
    narration_audio = ""
    if valid_audio:
        narration_audio = os.path.join(tmp_dir, "narration.wav")
        if len(valid_audio) == 1:
            shutil.copy(valid_audio[0], narration_audio)
        else:
            audio_list = os.path.join(tmp_dir, "audio_list.txt")
            with open(audio_list, "w") as f:
                for a in valid_audio:
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
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="framecraft — create demo videos from screenshots + scene descriptions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s scenes.json                        # render all scenes
  %(prog)s scenes.json --scene 2              # render only scene 2
  %(prog)s scenes.json --auto-duration        # set duration from TTS length
  %(prog)s scenes.json -o demo.mp4            # override output path
  %(prog)s --validate output.mp4              # validate a rendered video
        """,
    )
    parser.add_argument("config", nargs="?", help="Path to scenes.json config file")
    parser.add_argument("--output", "-o", help="Override output path")
    parser.add_argument("--scene", "-s", type=int, help="Render only this scene index (0-based)")
    parser.add_argument("--auto-duration", "-a", action="store_true",
                        help="Auto-detect scene duration from TTS audio length")
    parser.add_argument("--validate", "-v", metavar="VIDEO",
                        help="Validate a rendered video file instead of rendering")
    args = parser.parse_args()

    if args.validate:
        print(f"Validating: {args.validate}")
        result = validate_video(args.validate)
        for k, v in result.items():
            if k == "passed":
                continue
            status = "OK" if v not in (False, 0, "none") else "FAIL"
            print(f"  {k}: {v} {status if isinstance(v, bool) else ''}")
        passed = result.get("passed", False)
        print(f"\n  {'PASSED' if passed else 'FAILED'}")
        sys.exit(0 if passed else 1)

    if not args.config:
        parser.error("config is required when not using --validate")

    cfg = DemoConfig.from_json(args.config)
    if args.output:
        cfg.output = args.output

    print(f"framecraft — {len(cfg.scenes)} scenes @ {cfg.width}x{cfg.height} {cfg.fps}fps")
    result = render_demo(cfg, scene_filter=args.scene, auto_duration=args.auto_duration)
    print(f"Output: {result}")

    # Auto-validate after render
    print("\nValidating output...")
    checks = validate_video(result)
    for k, v in checks.items():
        if k == "passed":
            continue
        print(f"  {k}: {v}")
    print(f"\n  {'PASSED' if checks.get('passed') else 'FAILED'}")
