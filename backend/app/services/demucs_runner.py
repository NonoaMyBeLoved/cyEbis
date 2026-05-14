from __future__ import annotations

import sys
import wave
from pathlib import Path


def _patched_save(path, tensor, sample_rate: int, **_kwargs) -> None:
    import torch

    wav = tensor.detach().cpu()
    if wav.ndim == 1:
        wav = wav.unsqueeze(0)
    if wav.shape[0] > wav.shape[1]:
        wav = wav.transpose(0, 1)
    channels, frames = wav.shape
    wav = torch.clamp(wav, -1, 1)
    pcm = (wav.transpose(0, 1).contiguous().numpy() * 32767).astype("<i2")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(int(channels))
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())


def _patched_read_info(path):
    path = Path(path)
    if path.suffix.lower() != ".wav":
        raise RuntimeError("cyEbis Demucs runner expects the preprocessed input to be a WAV file.")
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        frames = handle.getnframes()
    return {
        "format": {"duration": str(frames / sample_rate)},
        "streams": [
            {
                "codec_type": "audio",
                "channels": str(channels),
                "sample_rate": str(sample_rate),
            }
        ],
    }


def _patched_read(self, seek_time=None, duration=None, streams=slice(None), samplerate=None, channels=None):
    import numpy as np
    import torch
    import demucs.audio as demucs_audio

    with wave.open(str(self.path), "rb") as handle:
        source_channels = handle.getnchannels()
        source_rate = handle.getframerate()
        total_frames = handle.getnframes()
        if seek_time:
            handle.setpos(min(total_frames, int(seek_time * source_rate)))
        frame_count = total_frames - handle.tell()
        if duration is not None:
            frame_count = min(frame_count, int(duration * source_rate) + 1)
        raw = handle.readframes(frame_count)
        sample_width = handle.getsampwidth()

    if sample_width != 2:
        raise RuntimeError("cyEbis Demucs runner expects 16-bit PCM WAV input.")
    samples = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    wav = torch.from_numpy(samples.reshape(-1, source_channels).T.copy())
    if channels is not None:
        wav = demucs_audio.convert_audio_channels(wav, channels)
    if samplerate is not None and samplerate != source_rate:
        wav = demucs_audio.convert_audio(wav, source_rate, samplerate, channels or source_channels)
    return wav


def main() -> None:
    import torchaudio
    import demucs.audio as demucs_audio
    from demucs.separate import main as demucs_main

    torchaudio.save = _patched_save
    demucs_audio._read_info = _patched_read_info
    demucs_audio.AudioFile.read = _patched_read
    demucs_main()


if __name__ == "__main__":
    main()
