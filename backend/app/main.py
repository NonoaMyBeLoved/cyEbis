from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models.schemas import ArtifactInfo, CreateJobResponse, JobStatus, MixRequest, StemInfo, TabResponse
from app.services.audio import (
    STEM_LABELS,
    audio_activity_ratio,
    audio_duration,
    audio_level,
    convert_audio,
    encode_mp3,
    render_mix,
    separate_stems,
    torch_device_info,
    write_empty_waveform,
    write_waveform,
)
from app.services.tab import build_tab, export_all, transcribe_notes


if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass


BASE_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = BASE_DIR / "storage"
JOBS_DIR = STORAGE_DIR / "jobs"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="cyEbis MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def suppress_browser_disconnects(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    exc = context.get("exception")
    if isinstance(exc, ConnectionResetError) and getattr(exc, "winerror", None) == 10054:
        return
    loop.default_exception_handler(context)


def cleanup_job_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs_root = JOBS_DIR.resolve()
    for path in JOBS_DIR.iterdir():
        resolved = path.resolve()
        if resolved.parent != jobs_root:
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                path.unlink()
            except OSError:
                pass


@app.on_event("startup")
async def configure_event_loop() -> None:
    asyncio.get_running_loop().set_exception_handler(suppress_browser_disconnects)
    cleanup_job_dirs()


@app.on_event("shutdown")
async def cleanup_jobs_on_shutdown() -> None:
    cleanup_job_dirs()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def status_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def write_status(job_id: str, **updates) -> None:
    path = status_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Queued",
            "warnings": [],
            "stems": [],
            "artifacts": [],
            "created_at": now_iso(),
            "completed_at": None,
        }
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def original_url(job_id: str) -> str:
    return f"/api/jobs/{job_id}/files/audio/source.wav"


def safe_download_stem(name: str | None) -> str:
    cleaned = re.sub(r"[^\w가-힣.-]+", "-", name or "cyEbis", flags=re.UNICODE).strip(".-")
    return cleaned or "cyEbis"


def uploaded_source_path(root: Path) -> Path | None:
    uploads = root / "uploads"
    for path in uploads.glob("source.*"):
        if path.is_file():
            return path
    return None


def original_download_path(root: Path) -> Path:
    uploaded = uploaded_source_path(root)
    if uploaded and uploaded.suffix.lower() == ".mp3":
        return uploaded
    source_wav = root / "audio" / "source.wav"
    output_path = root / "mixes" / "original_mix.mp3"
    if not output_path.exists() or (source_wav.exists() and output_path.stat().st_mtime < source_wav.stat().st_mtime):
        encode_mp3(source_wav, output_path)
    return output_path


def is_original_mix_request(status: dict, request: MixRequest) -> bool:
    if request.solo:
        return False
    requested = {track.name: track for track in request.tracks}
    for stem in status.get("stems", []):
        if not stem.get("active", True):
            continue
        track = requested.get(stem["name"])
        if not track or not track.active or track.muted or abs(track.volume - 1.0) > 0.001:
            return False
    return True


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/devices")
def devices() -> dict[str, object]:
    return torch_device_info()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.post("/api/jobs", response_model=CreateJobResponse)
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    device: str = Form("auto"),
) -> CreateJobResponse:
    if device not in {"auto", "cpu", "cuda"}:
        raise HTTPException(status_code=400, detail="Unknown processing device.")
    job_id = uuid.uuid4().hex
    root = job_dir(job_id)
    uploads = root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "audio").suffix or ".audio"
    source = uploads / f"source{suffix}"
    with source.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    source_name = Path(file.filename or "audio").stem or "audio"
    write_status(job_id, message="Upload saved", device=device, source_name=source_name)
    background_tasks.add_task(process_job, job_id, source, device)
    return CreateJobResponse(id=job_id, status_url=f"/api/jobs/{job_id}")


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    path = status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**json.loads(path.read_text(encoding="utf-8")))


@app.get("/api/jobs/{job_id}/files/{relative_path:path}")
def get_job_file(job_id: str, relative_path: str) -> FileResponse:
    root = job_dir(job_id).resolve()
    path = (root / relative_path).resolve()
    if not str(path).startswith(str(root)) or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.post("/api/jobs/{job_id}/mix")
def download_mix(job_id: str, request: MixRequest) -> FileResponse:
    path = status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    status = json.loads(path.read_text(encoding="utf-8"))
    if status["status"] != "complete":
        raise HTTPException(status_code=409, detail="Stem separation must complete before mix download.")

    root = job_dir(job_id)
    download_name = f"{safe_download_stem(status.get('source_name'))}-cymixed.mp3"
    status_by_name = {stem["name"]: stem for stem in status.get("stems", [])}
    requested = {track.name: track for track in request.tracks}
    mix_inputs = []
    longest_duration = 0.0
    for name, stem in status_by_name.items():
        stem_path = root / "stems" / f"{name}.wav"
        if not stem_path.exists():
            continue
        longest_duration = max(longest_duration, audio_duration(stem_path))
        track = requested.get(name)
        if not track or not track.active or not stem.get("active", True):
            continue
        if request.solo and request.solo != name:
            continue
        volume = 0.0 if track.muted else track.volume
        mix_inputs.append((stem_path, volume))

    output_wav = root / "mixes" / "current_mix.wav"
    output_mp3 = root / "mixes" / "current_mix.mp3"
    try:
        render_mix(mix_inputs, output_wav, longest_duration)
        encode_mp3(output_wav, output_mp3)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(output_mp3, media_type="audio/mpeg", filename=download_name)


@app.post("/api/jobs/{job_id}/tabs/{instrument}", response_model=TabResponse)
def create_tab(job_id: str, instrument: str) -> TabResponse:
    if instrument not in {"guitar", "bass"}:
        raise HTTPException(status_code=400, detail="Tab extraction is available for guitar and bass only.")
    path = status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    status = json.loads(path.read_text(encoding="utf-8"))
    if status["status"] != "complete":
        raise HTTPException(status_code=409, detail="Stem separation must complete before tab extraction.")

    warnings: list[str] = []
    root = job_dir(job_id)
    stem_path = root / "stems" / f"{instrument}.wav"
    if not stem_path.exists():
        raise HTTPException(status_code=404, detail=f"{instrument} stem not found")

    notes = transcribe_notes(stem_path, instrument, warnings)
    tab_notes = build_tab(notes, instrument)
    exported = export_all(tab_notes, instrument, root / "tabs" / instrument, f"cyEbis {instrument.title()}")
    artifacts: list[ArtifactInfo] = []
    version = uuid.uuid4().hex[:8]
    for kind, artifact_path in exported.items():
        if artifact_path is None:
            warnings.append(f"{instrument} .gp5 export skipped because PyGuitarPro could not write the file.")
            continue
        artifacts.append(
            ArtifactInfo(
                name=artifact_path.name,
                instrument=instrument,
                kind=kind,
                url=f"/api/jobs/{job_id}/files/{artifact_path.relative_to(root).as_posix()}?v={version}",
            )
        )

    existing = [
        artifact
        for artifact in status.get("artifacts", [])
        if artifact.get("instrument") != instrument
    ]
    status["artifacts"] = existing + [artifact.model_dump() for artifact in artifacts]
    merged_warnings = status.get("warnings", [])
    for warning in warnings:
        if warning not in merged_warnings:
            merged_warnings.append(warning)
    status["warnings"] = merged_warnings
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return TabResponse(instrument=instrument, artifacts=artifacts, warnings=warnings)


def process_job(job_id: str, source: Path, device: str = "auto") -> None:
    warnings: list[str] = []
    root = job_dir(job_id)
    try:
        write_status(job_id, status="running", progress=0.1, message="Preparing audio")
        prepared = root / "audio" / "source.wav"
        convert_audio(source, prepared)

        write_status(job_id, progress=0.25, message="Separating stems with Demucs")
        stems = separate_stems(prepared, root / "stems", warnings, device=device)
        write_status(job_id, progress=0.8, message="Preparing stem waveforms")
        levels = {name: audio_level(path) for name, path in stems.items()}
        activities = {name: audio_activity_ratio(path) for name, path in stems.items()}
        strongest_level = max([level for name, level in levels.items() if name != "synth_other"] + [0.001])
        vocal_reference_level = max([levels.get(name, 0.0) for name in ["guitar", "bass", "drums"]] + [0.001])
        stem_infos = []
        for name, path in stems.items():
            active = True
            if name in {"guitar", "bass"}:
                active = (
                    levels[name] >= max(0.008, strongest_level * 0.04)
                    and (activities[name] >= 0.025 or levels[name] >= strongest_level * 0.12)
                )
            if name == "synth_other":
                active = levels[name] >= 0.003 and levels[name] >= strongest_level * 0.08
            if name == "vocals":
                active = levels[name] >= 0.003 and levels[name] >= vocal_reference_level * 0.08
            waveform_path = root / "waveforms" / f"{name}.json"
            duration = (
                write_waveform(path, waveform_path)
                if active
                else write_empty_waveform(audio_duration(path), waveform_path)
            )
            stem_infos.append(StemInfo(
                name=name,
                label=STEM_LABELS[name],
                url=f"/api/jobs/{job_id}/files/{path.relative_to(root).as_posix()}",
                waveform_url=f"/api/jobs/{job_id}/files/{waveform_path.relative_to(root).as_posix()}",
                duration=duration,
                active=active,
            ))
        write_status(job_id, progress=0.92, message="Stem separation complete", warnings=warnings, stems=[s.model_dump() for s in stem_infos])

        write_status(
            job_id,
            status="complete",
            progress=1,
            message="Stems ready. Use Extract Tab on guitar or bass when needed.",
            warnings=warnings,
            stems=[s.model_dump() for s in stem_infos],
            artifacts=[],
            original_url=original_url(job_id),
            completed_at=now_iso(),
        )
    except Exception as exc:
        warnings.append(str(exc))
        write_status(job_id, status="failed", progress=1, message="Processing failed", warnings=warnings, completed_at=now_iso())
