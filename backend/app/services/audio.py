from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path


STEM_LABELS = {
    "vocals": "보컬",
    "guitar": "기타",
    "bass": "베이스",
    "drums": "드럼",
    "synth_other": "신스/기타",
}

BASS_TARGET_LEVEL_RATIO = 0.75
BASS_MAX_GAIN = 1.8
STEM_OUTPUT_GAIN = 1.25
MIX_MUTE_THRESHOLD = 0.03
GUITAR_OTHER_BLEND_GAIN = 0.55


class AudioToolError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment dependent
        raise AudioToolError("ffmpeg is not available. Install ffmpeg or imageio-ffmpeg.") from exc


def run_command(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=process_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise AudioToolError(detail or f"Command failed: {' '.join(command)}")
    return (proc.stdout or proc.stderr).strip()


def torch_device_info() -> dict[str, object]:
    info: dict[str, object] = {
        "torch_installed": False,
        "cuda_available": False,
        "cuda_version": None,
        "device_count": 0,
        "device_name": None,
    }
    try:
        import torch

        info["torch_installed"] = True
        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["cuda_version"] = torch.version.cuda
        info["device_count"] = int(torch.cuda.device_count())
        if torch.cuda.is_available() and torch.cuda.device_count():
            info["device_name"] = torch.cuda.get_device_name(0)
    except Exception as exc:
        info["error"] = str(exc)
    return info


def resolve_demucs_device(requested: str, warnings: list[str]) -> str:
    if requested not in {"auto", "cpu", "cuda"}:
        raise AudioToolError("Invalid Demucs device option.")
    if requested == "cpu":
        return "cpu"

    info = torch_device_info()
    if requested == "cuda":
        if info.get("cuda_available"):
            return "cuda"
        torch_version = info.get("torch_version", "unknown")
        cuda_version = info.get("cuda_version") or "none"
        warnings.append(
            "GPU 처리를 요청했지만 CUDA를 사용할 수 없어 CPU로 처리합니다. "
            f"torch={torch_version}, torch CUDA={cuda_version}"
        )
        return "cpu"

    return "cuda" if info.get("cuda_available") else "cpu"


def convert_audio(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg_exe(),
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "2",
            "-ar",
            "44100",
            str(output_path),
        ]
    )


def mix_audio(inputs: list[Path], output_path: Path) -> None:
    if not inputs:
        raise AudioToolError("No inputs to mix.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(inputs) == 1:
        shutil.copyfile(inputs[0], output_path)
        return

    command = [ffmpeg_exe(), "-y"]
    for path in inputs:
        command.extend(["-i", str(path)])
    command.extend(
        [
            "-filter_complex",
            f"amix=inputs={len(inputs)}:duration=longest",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(output_path),
        ]
    )
    run_command(command)


def write_silence(output_path: Path, duration: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg_exe(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{max(0.1, duration):.3f}",
            str(output_path),
        ]
    )


def blend_audio(inputs: list[tuple[Path, float]], output_path: Path) -> None:
    audible = [(path, gain) for path, gain in inputs if path.exists() and gain > 0]
    if not audible:
        raise AudioToolError("No inputs to blend.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(audible) == 1 and abs(audible[0][1] - 1.0) < 0.001:
        shutil.copyfile(audible[0][0], output_path)
        return

    command = [ffmpeg_exe(), "-y"]
    filters = []
    labels = []
    for index, (path, gain) in enumerate(audible):
        command.extend(["-i", str(path)])
        label = f"a{index}"
        filters.append(f"[{index}:a]volume={gain:.4f}[{label}]")
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(audible)}:duration=longest[mixed]")
    filters.append(f"[mixed]volume={len(audible)},alimiter=limit=0.98[mix]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[mix]", "-ac", "2", "-ar", "44100", str(output_path)])
    run_command(command)


def render_mix(inputs: list[tuple[Path, float]], output_path: Path, duration: float | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audible = [
        (path, max(0.0, min(1.5, volume)))
        for path, volume in inputs
        if volume >= MIX_MUTE_THRESHOLD
    ]
    if not audible:
        if not duration or duration <= 0:
            raise AudioToolError("No audible stems to render.")
        write_silence(output_path, duration)
        return

    command = [ffmpeg_exe(), "-y"]
    for path, _ in audible:
        command.extend(["-i", str(path)])

    if len(audible) == 1:
        command.extend(["-filter:a", f"volume={audible[0][1]:.4f}", "-ac", "2", "-ar", "44100", str(output_path)])
        run_command(command)
        return

    filters = []
    labels = []
    for index, (_, volume) in enumerate(audible):
        label = f"a{index}"
        filters.append(f"[{index}:a]volume={volume:.4f}[{label}]")
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(audible)}:duration=longest[mixed]")
    filters.append(f"[mixed]volume={len(audible)}[mix]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[mix]",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(output_path),
        ]
    )
    run_command(command)


def encode_mp3(input_path: Path, output_path: Path, bitrate: str = "192k") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg_exe(),
            "-y",
            "-i",
            str(input_path),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-ar",
            "44100",
            str(output_path),
        ]
    )


def apply_gain(input_path: Path, output_path: Path, gain: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg_exe(),
            "-y",
            "-i",
            str(input_path),
            "-filter:a",
            f"volume={gain:.4f},alimiter=limit=0.98",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(output_path),
        ]
    )


def boost_stem_outputs(stems: dict[str, Path], warnings: list[str]) -> None:
    if STEM_OUTPUT_GAIN <= 1:
        return

    for name, stem_path in stems.items():
        if not stem_path.exists():
            continue
        boosted_path = stem_path.with_name(f"{name}_louder.wav")
        apply_gain(stem_path, boosted_path, STEM_OUTPUT_GAIN)
        boosted_path.replace(stem_path)
    warnings.append(f"분리된 stem 기본 출력을 원본보다 {STEM_OUTPUT_GAIN:.2f}배 크게 보정했습니다.")


def boost_quiet_bass_stem(stems: dict[str, Path], warnings: list[str]) -> None:
    bass_path = stems.get("bass")
    if not bass_path or not bass_path.exists():
        return

    bass_level = audio_level(bass_path)
    reference_levels = [
        audio_level(path)
        for name, path in stems.items()
        if name in {"guitar", "drums", "vocals"} and path.exists()
    ]
    reference_level = max(reference_levels + [0.001])
    target_level = reference_level * BASS_TARGET_LEVEL_RATIO
    if bass_level <= 0 or bass_level >= target_level:
        return

    gain = min(BASS_MAX_GAIN, target_level / bass_level)
    if gain <= 1.05:
        return

    boosted_path = bass_path.with_name("bass_boosted.wav")
    apply_gain(bass_path, boosted_path, gain)
    boosted_path.replace(bass_path)
    warnings.append(f"베이스 stem이 작게 감지되어 기본 볼륨을 {gain:.2f}배로 보정했습니다.")


def fold_guitar_leakage(guitar_path: Path, other_path: Path | None, warnings: list[str]) -> bool:
    if not other_path or not other_path.exists() or not guitar_path.exists():
        return False

    guitar_level = audio_level(guitar_path)
    other_level = audio_level(other_path)
    guitar_activity = audio_activity_ratio(guitar_path)
    other_activity = audio_activity_ratio(other_path)
    likely_leak = (
        other_level >= max(0.006, guitar_level * 0.28)
        and other_activity >= max(0.035, guitar_activity * 0.75)
        and guitar_activity < 0.92
    )
    if not likely_leak:
        return False

    blended_path = guitar_path.with_name("guitar_complete.wav")
    blend_audio([(guitar_path, 1.0), (other_path, GUITAR_OTHER_BLEND_GAIN)], blended_path)
    blended_path.replace(guitar_path)
    warnings.append("기타 일부가 other stem에 감지되어 기타 stem에 함께 보정했습니다.")
    return True


def separate_stems(audio_path: Path, stems_dir: Path, warnings: list[str], device: str = "auto") -> dict[str, Path]:
    stems_dir.mkdir(parents=True, exist_ok=True)
    demucs_output = stems_dir.parent / "demucs"
    audio_stem = audio_path.stem
    separated: dict[str, Path] = {}
    resolved_device = resolve_demucs_device(device, warnings)

    cache_dir = Path(__file__).resolve().parents[2] / "storage" / "model_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "app.services.demucs_runner",
        "-n",
        "htdemucs_6s",
        "--shifts",
        "2",
        "--overlap",
        "0.35",
        "--out",
        str(demucs_output),
        "-d",
        resolved_device,
        str(audio_path),
    ]
    run_command(
        command,
        cwd=Path(__file__).resolve().parents[2],
        env={
            "TORCH_HOME": str(cache_dir / "torch"),
            "XDG_CACHE_HOME": str(cache_dir),
        },
    )
    source_dir = demucs_output / "htdemucs_6s" / audio_stem
    for name in ["vocals", "drums", "bass", "guitar"]:
        src = source_dir / f"{name}.wav"
        dst = stems_dir / f"{name}.wav"
        if not src.exists():
            raise AudioToolError(f"Demucs did not create expected stem: {name}.wav")
        shutil.copyfile(src, dst)
        separated[name] = dst

    piano_path = source_dir / "piano.wav"
    other_path = source_dir / "other.wav"
    folded_other_into_guitar = fold_guitar_leakage(separated["guitar"], other_path, warnings)
    synth_inputs = [
        path
        for path in [piano_path, None if folded_other_into_guitar else other_path]
        if path is not None and path.exists()
    ]
    synth_path = stems_dir / "synth_other.wav"
    if synth_inputs:
        mix_audio(synth_inputs, synth_path)
    else:
        write_silence(synth_path, audio_duration(separated["guitar"]))
    separated["synth_other"] = synth_path

    boost_quiet_bass_stem(separated, warnings)
    boost_stem_outputs(separated, warnings)

    return separated


def audio_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def audio_level(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)
    if sample_width != 2 or not raw:
        return 0.0
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    mono = samples[::channels] if channels > 1 else samples
    if not mono:
        return 0.0
    return (sum(sample * sample for sample in mono) / len(mono)) ** 0.5 / 32768


def audio_activity_ratio(path: Path, window_seconds: float = 0.18) -> float:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)
    if sample_width != 2 or not raw or sample_rate <= 0:
        return 0.0

    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    mono = samples[::channels] if channels > 1 else samples
    if not mono:
        return 0.0

    global_rms = (sum(sample * sample for sample in mono) / len(mono)) ** 0.5 / 32768
    threshold = max(0.004, global_rms * 0.38)
    window = max(1, int(sample_rate * window_seconds))
    active = 0
    total = 0
    for start in range(0, len(mono), window):
        chunk = mono[start : start + window]
        if not chunk:
            continue
        rms = (sum(sample * sample for sample in chunk) / len(chunk)) ** 0.5 / 32768
        active += int(rms >= threshold)
        total += 1
    return active / total if total else 0.0


def write_empty_waveform(duration: float, output_path: Path, points: int = 900) -> float:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"duration": duration, "peaks": [0.0 for _ in range(points)]}), encoding="utf-8")
    return duration


def write_waveform(path: Path, output_path: Path, points: int = 900) -> float:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    duration = frame_count / sample_rate if sample_rate else 0
    peaks = [0.0 for _ in range(points)]
    if sample_width != 2 or frame_count == 0:
        output_path.write_text(json.dumps({"duration": duration, "peaks": peaks}), encoding="utf-8")
        return duration

    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    mono = samples[::channels] if channels > 1 else samples
    bucket = max(1, len(mono) // points)
    for index in range(points):
        chunk = mono[index * bucket : (index + 1) * bucket]
        if chunk:
            peaks[index] = round(max(abs(sample) for sample in chunk) / 32768, 4)
    maximum = max(peaks) or 1
    normalized = [round(value / maximum, 4) for value in peaks]
    output_path.write_text(json.dumps({"duration": duration, "peaks": normalized}), encoding="utf-8")
    return duration
