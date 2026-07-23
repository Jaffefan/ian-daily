from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import wave
from array import array
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


def _to_pcm(source: Path, target: Path) -> None:
    subprocess.run([
        _ffmpeg(), "-y", "-i", str(source), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
    ], capture_output=True, text=True, timeout=180, check=True)


def _waveform(path: Path, bins: int = 160) -> list[float]:
    with wave.open(str(path), "rb") as source:
        samples = array("h", source.readframes(source.getnframes()))
    if not samples:
        return []
    width = max(1, len(samples) // bins)
    peaks = [max(abs(item) for item in samples[index:index + width]) / 32768 for index in range(0, len(samples), width)]
    return [round(value, 4) for value in peaks[:bins]]


def waveform_peaks(path: Path, bins: int = 160) -> list[float]:
    """Decode a published audio file and derive a stable display waveform."""
    pcm = path.with_name(f".{path.stem}-waveform.wav")
    try:
        _to_pcm(path, pcm)
        return _waveform(pcm, bins)
    finally:
        pcm.unlink(missing_ok=True)


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


async def _render_provider(podcast: PodcastEpisode, category: str, root: Path, provider: str, story_titles: dict[str, str] | None = None) -> PodcastEpisode:
    rate = config.CATEGORIES[category].tts_rate
    provider_dir = root / provider
    provider_dir.mkdir(parents=True, exist_ok=True)
    story_titles = story_titles or {}
    chapters: list[Chapter] = []
    pcm_paths: list[Path] = []
    seen_story: set[str] = set()
    for index, block in enumerate(podcast.blocks):
        clip = provider_dir / f"block-{index + 1:02d}.mp3"
        if provider == "edge":
            voice = config.LISTENER_VOICE if block.speaker == "listener" else config.IAN_VOICE
            await _edge_text(block.text, clip, voice, rate)
        else:
            voice = config.SILICONFLOW_LISTENER_VOICE if block.speaker == "listener" else config.SILICONFLOW_IAN_VOICE
            _siliconflow_text(block.text, clip, voice)
        pcm = provider_dir / f"block-{index + 1:02d}.wav"
        _to_pcm(clip, pcm)
        pcm_paths.append(pcm)
    master = root.parent / ".master.wav"
    sample_rate = 24000
    pause_frames = int(config.CHAPTER_PAUSE_SEC * sample_rate)
    cursor_frames = 0
    with wave.open(str(master), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(sample_rate)
        for index, (block, pcm) in enumerate(zip(podcast.blocks, pcm_paths)):
            with wave.open(str(pcm), "rb") as source:
                frames = source.readframes(source.getnframes())
                frame_count = source.getnframes()
            start = cursor_frames / sample_rate
            block.audio_file = ""
            block.start_sec = round(start, 3)
            block.duration_sec = round(frame_count / sample_rate, 3)
            if block.role == "opening" and not chapters:
                chapters.append(Chapter("opening", "开场", round(start, 3)))
            if block.role == "story" and block.story_id and block.story_id not in seen_story:
                chapters.append(Chapter(f"story-{len(seen_story) + 1}", story_titles.get(block.story_id, "本期事件"), round(start, 3), block.story_id))
                seen_story.add(block.story_id)
            if block.role == "synthesis" and not any(item.chapter_id == "synthesis" for item in chapters):
                chapters.append(Chapter("synthesis", "主题复盘", round(start, 3)))
            output.writeframes(frames)
            cursor_frames += frame_count
            if index < len(podcast.blocks) - 1:
                output.writeframes(b"\x00\x00" * pause_frames)
                cursor_frames += pause_frames
    raw_duration = cursor_frames / sample_rate
    if raw_duration > 1080:
        target_duration = 1075.0
        tempo = raw_duration / target_duration
        normalized = master.with_name(".master-normalized.wav")
        subprocess.run(
            [_ffmpeg(), "-y", "-i", str(master), "-filter:a", f"atempo={tempo:.6f}", "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le", str(normalized)],
            capture_output=True, text=True, timeout=900, check=True,
        )
        normalized.replace(master)
        for block in podcast.blocks:
            block.start_sec = round(block.start_sec / tempo, 3)
            block.duration_sec = round(block.duration_sec / tempo, 3)
        for chapter in chapters:
            chapter.start_sec = round(chapter.start_sec / tempo, 3)
    full = root.parent / "episode.mp3"
    subprocess.run([_ffmpeg(), "-y", "-i", str(master), "-c:a", "libmp3lame", "-b:a", "96k", str(full)], capture_output=True, text=True, timeout=900, check=True)
    podcast.chapters = chapters
    podcast.full_audio_file = "episode.mp3"
    podcast.total_duration_sec = round(audio_duration(full), 1)
    podcast.tts_provider = provider
    podcast.waveform_peaks = _waveform(master)
    master.unlink(missing_ok=True)
    shutil.rmtree(provider_dir, ignore_errors=True)
    return podcast


async def generate_podcast_audio_async(podcast: PodcastEpisode, category: str, episode_dir: Path, story_titles: dict[str, str] | None = None) -> PodcastEpisode:
    audio_root = episode_dir / "audio"
    try:
        return await _render_provider(podcast, category, audio_root, "edge", story_titles)
    except Exception as edge_error:
        if not config.SILICONFLOW_API_KEY:
            raise RuntimeError(str(edge_error)) from edge_error
        # Regenerate every block so a published episode never mixes Ian voices.
        for block in podcast.blocks:
            block.audio_file = ""
            block.start_sec = 0
            block.duration_sec = 0
        return await _render_provider(podcast, category, audio_root, "siliconflow", story_titles)


def generate_podcast_audio(podcast: PodcastEpisode, category: str, episode_dir: Path, story_titles: dict[str, str] | None = None) -> PodcastEpisode:
    return asyncio.run(generate_podcast_audio_async(podcast, category, episode_dir, story_titles))
