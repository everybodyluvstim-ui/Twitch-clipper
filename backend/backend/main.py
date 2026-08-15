import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from twitch import TwitchClient
from clipper import download_vod, download_chat, cut_clip
from highlight_detector import detect_highlights

load_dotenv()

CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "")
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError(
        "Missing TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET environment variables."
    )

STORAGE = Path(__file__).parent.parent / "storage"
VODS_DIR = STORAGE / "vods"
CLIPS_DIR = STORAGE / "clips"
VODS_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

twitch = TwitchClient(CLIENT_ID, CLIENT_SECRET)

app = FastAPI(title="Twitch VOD Auto-Clipper")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

JOBS: dict[str, dict] = {}


class ProcessRequest(BaseModel):
    vod_id: str
    max_clips: int = 8


@app.get("/api/channel/{login}/vods")
def list_vods(login: str, limit: int = 20):
    user = twitch.get_user(login)
    if not user:
        raise HTTPException(404, f"No Twitch channel found for '{login}'")
    vods = twitch.get_vods(user["id"], limit=limit)
    return {
        "channel": user["display_name"],
        "avatar": user["profile_image_url"],
        "vods": [
            {
                "id": v["id"],
                "title": v["title"],
                "created_at": v["created_at"],
                "duration": v["duration"],
                "thumbnail": v["thumbnail_url"]
                    .replace("%{width}", "320").replace("%{height}", "180"),
                "url": v["url"],
            }
            for v in vods
        ],
    }


@app.post("/api/process")
def start_processing(req: ProcessRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "queued", "vod_id": req.vod_id, "clips": [], "error": None}
    background_tasks.add_task(_run_job, job_id, req.vod_id, req.max_clips)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job


def _run_job(job_id: str, vod_id: str, max_clips: int):
    job = JOBS[job_id]
    try:
        job["status"] = "downloading_vod"
        vod_path = download_vod(vod_id, VODS_DIR)

        job["status"] = "downloading_chat"
        chat_path = download_chat(vod_id, VODS_DIR)

        job["status"] = "analyzing"
        highlights = detect_highlights(
            str(vod_path),
            str(chat_path) if chat_path else None,
            max_clips=max_clips,
        )

        job["status"] = "clipping"
        clip_dir = CLIPS_DIR / vod_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        clips = []
        for i, h in enumerate(highlights, start=1):
            out_path = clip_dir / f"clip_{i:02d}.mp4"
            cut_clip(vod_path, h, out_path)
            clips.append({
                "index": i,
                "start": round(h.start, 1),
                "end": round(h.end, 1),
                "score": round(h.score, 2),
                "download_url": f"/clips/{vod_id}/{out_path.name}",
            })

        job["clips"] = clips
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
