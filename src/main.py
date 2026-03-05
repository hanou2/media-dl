import os
import shutil
import subprocess
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Media Downloader", description="Download videos from YouTube, Instagram, TikTok")

DOWNLOADS_DIR = Path("/app/data/downloads")
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
SHARED_DIR = Path("/shared/downloads")


class DownloadRequest(BaseModel):
    url: str
    audio_only: bool = False
    output_dir: str | None = None


@app.post("/download")
def download(req: DownloadRequest):
    """Download a video or extract audio from a URL."""
    # Build yt-dlp command to extract info first
    info_cmd = [
        "yt-dlp",
        "--no-playlist",
        "--dump-json",
        req.url,
    ]

    try:
        info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout fetching video info")

    if info_result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"yt-dlp error: {info_result.stderr.strip()}")

    info = json.loads(info_result.stdout)
    title = info.get("title", "unknown")
    duration = info.get("duration")
    video_id = info.get("id", "unknown")

    # Sanitize filename
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title).strip()

    if req.audio_only:
        output_template = str(DOWNLOADS_DIR / f"{safe_title}__{video_id}.%(ext)s")
        dl_cmd = [
            "yt-dlp",
            "--no-playlist",
            "-x",
            "--audio-format", "mp3",
            "-o", output_template,
            req.url,
        ]
    else:
        output_template = str(DOWNLOADS_DIR / f"{safe_title}__{video_id}.%(ext)s")
        dl_cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", output_template,
            req.url,
        ]

    try:
        dl_result = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout downloading media")

    if dl_result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Download failed: {dl_result.stderr.strip()}")

    # Find the downloaded file
    ext = "mp3" if req.audio_only else "mp4"
    expected_name = f"{safe_title}__{video_id}.{ext}"
    expected_path = DOWNLOADS_DIR / expected_name

    if not expected_path.exists():
        # Fallback: find any file matching the video_id
        matches = list(DOWNLOADS_DIR.glob(f"*{video_id}*"))
        if matches:
            expected_path = matches[0]
            expected_name = expected_path.name
        else:
            raise HTTPException(status_code=500, detail="File not found after download")

    file_size = expected_path.stat().st_size

    # Copy to shared volume for inter-service access
    shared_path = None
    try:
        if req.output_dir:
            out = Path(req.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            shared_dest = out / expected_name
        else:
            SHARED_DIR.mkdir(parents=True, exist_ok=True)
            shared_dest = SHARED_DIR / expected_name
        shutil.copy2(str(expected_path), str(shared_dest))
        shared_path = str(shared_dest)
    except Exception:
        pass  # Shared volume may not be mounted

    return {
        "title": title,
        "duration": duration,
        "filename": expected_name,
        "size_bytes": file_size,
        "audio_only": req.audio_only,
        "file_path": shared_path,
    }


@app.get("/files")
def list_files():
    """List all downloaded files."""
    files = []
    for f in sorted(DOWNLOADS_DIR.iterdir()):
        if f.is_file():
            files.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
            })
    return {"files": files}


@app.get("/files/{filename}")
def get_file(filename: str):
    """Serve a downloaded file."""
    file_path = DOWNLOADS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Prevent path traversal
    if file_path.resolve().parent != DOWNLOADS_DIR.resolve():
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(file_path, filename=filename)


@app.delete("/files/{filename}")
def delete_file(filename: str):
    """Delete a downloaded file."""
    file_path = DOWNLOADS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.resolve().parent != DOWNLOADS_DIR.resolve():
        raise HTTPException(status_code=403, detail="Access denied")
    file_path.unlink()
    return {"deleted": filename}


@app.get("/health")
def health():
    return {"status": "ok"}
