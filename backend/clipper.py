import subprocess
from pathlib import Path

from highlight_detector import Highlight


def download_vod(vod_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{vod_id}.mp4"
    if out_path.exists():
        return out_path

    url = f"https://www.twitch.tv/videos/{vod_id}"
    cmd = [
        "yt-dlp",
        "-f", "best[ext=mp4]/best",
        "-o", str(out_path),
        url,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def download_chat(vod_id: str, out_dir: Path) -> Path | None:
    import shutil
    if not shutil.which("TwitchDownloaderCLI"):
        return None
    out_path = out_dir / f"{vod_id}_chat.json"
    if out_path.exists():
        return out_path
    cmd = [
        "TwitchDownloaderCLI", "chatdownload",
        "--id", vod_id,
        "-o", str(out_path),
        "--embed-images", "false",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path
    except subprocess.CalledProcessError:
        return None


def cut_clip(source_path: Path, highlight: Highlight, out_path: Path) -> Path:
    duration = highlight.end - highlight.start
    cmd = [
        "ffmpeg", "-y", "-ss", str(highlight.start), "-i", str(source_path),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
