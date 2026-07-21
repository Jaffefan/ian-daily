from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import config
from .models import Chapter, PodcastEpisode


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError("音频生成需要 ffmpeg") from exc


def audio_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            [_ffmpeg(), "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        pass
    return 0.0


def _split_text(text: str, max_chars: int = 430) -> list[str]:
    sentences = [item.strip() for item in re.split(r"(?<=[。！？!?])", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks or [text]


def _concat(paths: list[Path], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = output.parent / f".{output.stem}-concat.txt"
    manifest.write_text("\n".join(f"file '{path.resolve().as_posix()}'" for path in paths), encoding="utf-8")
    try:
        subprocess.run([
            _ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(manifest),
            "-c:a", "libmp3lame", "-b:a", "64k", str(output),
        ], capture_output=True, text=True, timeout=900, check=True)
    finally:
        manifest.unlink(missing_ok=True)


def _pause(path: Path) -> None:
    subprocess.run([
        _ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", str(config.CHAPTER_PAUSE_SEC), "-q:a", "9", "-acodec", "libmp3lame", str(path),
    ], capture_output=True, text=True, timeout=30, check=True)


async def _edge_chunk(text: str, output: Path, voice: str, rate: str) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("音频生成需要 edge-tts") from exc
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            output.unlink(missing_ok=True)
            await asyncio.wait_for(edge_tts.Communicate(text, voice, rate=rate).save(str(output)), timeout=90)
            if output.exists() and output.stat().st_size > 0:
                return
            raise RuntimeError("Edge TTS 未产生音频文件")
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(2 ** attempt * 2)
    raise RuntimeError(f"Edge TTS 连续三次失败：{last_error}")


async def _edge_text(text: str, output: Path, voice: str, rate: str) -> None:
    chunks = _split_text(text)
    parts: list[Path] = []
    for index, chunk in enumerate(chunks):
        part = output.with_name(f".{output.stem}-{index:02d}.mp3")
        key = hashlib.sha256(f"{voice}|{rate}|{chunk}".encode()).hexdigest()
        marker = part.with_suffix(".sha256")
        if not (part.exists() and marker.exists() and marker.read_text() == key):
            await _edge_chunk(chunk, part, voice, rate)
            marker.write_text(key, encoding="ascii")
        parts.append(part)
    _concat(parts, output)


def _siliconflow_text(text: str, output: Path, voice: str) -> None:
    if not config.SILICONFLOW_API_KEY:
        raise RuntimeError("Edge TTS 失败，且未配置 SILICONFLOW_API_KEY")
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("SiliconFlow 回退需要 httpx") from exc
    response = httpx.post(
        config.SILICONFLOW_TTS_URL,
        headers={"Authorization": f"Bearer {config.SILICONFLOW_API_KEY}"},
        json={"model": config.SILICONFLOW_TTS_MODEL, "voice": voice, "input": text, "response_format": "mp3"},
        timeout=180,
    )
    response.raise_for_status()
    output.write_bytes(response.content)
    if output.stat().st_size == 0:
        raise RuntimeError("SiliconFlow 返回了空音频")


async def _render_provider(podcast: PodcastEpisode, category: str, root: Path, provider: str) -> PodcastEpisode:
    rate = config.CATEGORIES[category].tts_rate
    provider_dir = root / provider
    provider_dir.mkdir(parents=True, exist_ok=True)
    pause = provider_dir / "pause.mp3"
    _pause(pause)
    clips: list[Path] = []
    chapters: list[Chapter] = []
    cursor = 0.0
    seen_story: set[str] = set()
    for index, block in enumerate(podcast.blocks):
        clip = provider_dir / f"block-{index + 1:02d}.mp3"
        if provider == "edge":
            voice = config.LISTENER_VOICE if block.speaker == "listener" else config.IAN_VOICE
            await _edge_text(block.text, clip, voice, rate)
        else:
            voice = config.SILICONFLOW_LISTENER_VOICE if block.speaker == "listener" else config.SILICONFLOW_IAN_VOICE
            _siliconflow_text(block.text, clip, voice)
        duration = audio_duration(clip)
        if duration <= 0:
            raise RuntimeError(f"无法读取音频块时长：{clip.name}")
        block.audio_file = clip.relative_to(root.parent).as_posix()
        block.start_sec = round(cursor, 2)
        block.duration_sec = round(duration, 2)
        if block.role == "opening" and not chapters:
            chapters.append(Chapter("opening", "开场", round(cursor, 2)))
        if block.story_id and block.story_id not in seen_story:
            chapters.append(Chapter(f"story-{len(seen_story) + 1}", f"事件 {len(seen_story) + 1}", round(cursor, 2), block.story_id))
            seen_story.add(block.story_id)
        if block.role == "synthesis" and not any(item.chapter_id == "synthesis" for item in chapters):
            chapters.append(Chapter("synthesis", "主题复盘", round(cursor, 2)))
        clips.append(clip)
        cursor += duration
        if index < len(podcast.blocks) - 1:
            clips.append(pause)
            cursor += config.CHAPTER_PAUSE_SEC
    full = root.parent / "full.mp3"
    _concat(clips, full)
    podcast.chapters = chapters
    podcast.full_audio_file = "full.mp3"
    podcast.total_duration_sec = round(audio_duration(full), 1)
    podcast.tts_provider = provider
    return podcast


async def generate_podcast_audio_async(podcast: PodcastEpisode, category: str, episode_dir: Path) -> PodcastEpisode:
    audio_root = episode_dir / "audio"
    try:
        return await _render_provider(podcast, category, audio_root, "edge")
    except Exception as edge_error:
        if not config.SILICONFLOW_API_KEY:
            raise RuntimeError(str(edge_error)) from edge_error
        # Regenerate every block so a published episode never mixes Ian voices.
        for block in podcast.blocks:
            block.audio_file = ""
            block.start_sec = 0
            block.duration_sec = 0
        return await _render_provider(podcast, category, audio_root, "siliconflow")


def generate_podcast_audio(podcast: PodcastEpisode, category: str, episode_dir: Path) -> PodcastEpisode:
    return asyncio.run(generate_podcast_audio_async(podcast, category, episode_dir))
