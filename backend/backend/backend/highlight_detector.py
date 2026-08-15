"""
Picks candidate highlight timestamps from a downloaded VOD file.

Signal 1 (always on): audio loudness spikes, via ffmpeg astats per time window.
Signal 2 (optional):   chat-message-rate spikes, via a TwitchDownloaderCLI chat
                        export, if the `TwitchDownloaderCLI` binary is available.

Both signals are z-scored and summed; the top non-overlapping windows become
clip centers.
"""
import json
import shutil
import statistics
import subprocess
from dataclasses import dataclass

WINDOW_SECONDS = 30
CLIP_PRE_ROLL = 12
CLIP_POST_ROLL = 48
MIN_GAP_BETWEEN_CLIPS = 90


@dataclass
class Highlight:
    start: float
    end: float
    score: float


def _get_duration(video_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _audio_loudness_series(video_path: str, duration: float) -> list[float]:
    levels = []
    t = 0.0
    while t < duration:
        window = min(WINDOW_SECONDS, duration - t)
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats", "-ss", str(t), "-t", str(window),
            "-i", video_path, "-af", "astats=metadata=1:reset=1",
            "-f", "null", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        rms_vals = []
        for line in proc.stderr.splitlines():
            if "RMS_level" in line:
                try:
                    rms_vals.append(float(line.strip().split("=")[-1]))
                except ValueError:
                    pass
        levels.append(max(rms_vals) if rms_vals else -100.0)
        t += WINDOW_SECONDS
    return levels


def _zscore(values: list[float]) -> list[float]:
    if len(values) < 2:
        return [0.0 for _ in values]
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) or 1.0
    return [(v - mean) / stdev for v in values]


def _chat_spike_series(chat_json_path: str, duration: float) -> list[float] | None:
    try:
        with open(chat_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        comments = data.get("comments", [])
    except Exception:
        return None

    n_buckets = int(duration // WINDOW_SECONDS) + 1
    counts = [0] * n_buckets
    for c in comments:
        offset = c.get("content_offset_seconds", 0)
        idx = int(offset // WINDOW_SECONDS)
        if 0 <= idx < n_buckets:
            counts[idx] += 1
    return [float(c) for c in counts]


def find_chat_export_tool() -> str | None:
    return shutil.which("TwitchDownloaderCLI")


def detect_highlights(video_path: str, chat_json_path: str | None,
                       max_clips: int = 8) -> list[Highlight]:
    duration = _get_duration(video_path)
    audio_series = _audio_loudness_series(video_path, duration)
    audio_z = _zscore(audio_series)

    combined = list(audio_z)
    if chat_json_path:
        chat_series = _chat_spike_series(chat_json_path, duration)
        if chat_series:
            chat_z = _zscore(chat_series[:len(combined)])
            combined = [a + (chat_z[i] if i < len(chat_z) else 0)
                        for i, a in enumerate(combined)]

    scored = sorted(range(len(combined)), key=lambda i: combined[i], reverse=True)
    chosen_times: list[float] = []
    highlights: list[Highlight] = []
    for idx in scored:
        peak_t = idx * WINDOW_SECONDS
        if any(abs(peak_t - t) < MIN_GAP_BETWEEN_CLIPS for t in chosen_times):
            continue
        start = max(0.0, peak_t - CLIP_PRE_ROLL)
        end = min(duration, peak_t + CLIP_POST_ROLL)
        highlights.append(Highlight(start=start, end=end, score=combined[idx]))
        chosen_times.append(peak_t)
        if len(highlights) >= max_clips:
            break

    highlights.sort(key=lambda h: h.start)
    return highlights
