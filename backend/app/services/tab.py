from __future__ import annotations

import json
import math
import struct
import wave
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape


@dataclass
class NoteEvent:
    start: float
    end: float
    pitch: int
    velocity: int = 90
    confidence: float = 0.5
    preferred_string: int | None = None
    preferred_fret: int | None = None
    chord: str | None = None

    @property
    def duration(self) -> float:
        return max(0.1, self.end - self.start)


@dataclass
class TabNote:
    start: float
    end: float
    pitch: int
    string: int
    fret: int
    velocity: int
    confidence: float


TUNINGS = {
    "guitar": [
        ("e", 64),
        ("B", 59),
        ("G", 55),
        ("D", 50),
        ("A", 45),
        ("E", 40),
    ],
    "bass": [
        ("G", 43),
        ("D", 38),
        ("A", 33),
        ("E", 28),
    ],
}

PROGRAMS = {"guitar": 29, "bass": 34}
SLOT_SECONDS = 0.125
MEASURE_SECONDS = 2.0
SLOTS_PER_MEASURE = int(MEASURE_SECONDS / SLOT_SECONDS)
TEMPO = 120


def transcribe_notes(audio_path: Path, instrument: str, warnings: list[str]) -> list[NoteEvent]:
    try:
        from basic_pitch.inference import predict

        _, _, note_events = predict(str(audio_path))
        notes = [
            NoteEvent(
                start=float(event[0]),
                end=float(event[1]),
                pitch=int(event[2]),
                velocity=max(1, min(127, int(float(event[3]) * 127))),
                confidence=float(event[3]),
            )
            for event in note_events
        ]
        return [note for note in notes if _pitch_is_playable(note.pitch, instrument)]
    except Exception as exc:
        warnings.append(
            f"Basic Pitch is unavailable or failed for {instrument}; generated local chord/strum estimation."
        )
        warnings.append(str(exc))
        return _fallback_notes(audio_path, instrument)


def _fallback_notes(audio_path: Path, instrument: str) -> list[NoteEvent]:
    if instrument == "guitar":
        guitar_notes = _fallback_guitar_performance(audio_path)
        if guitar_notes:
            return guitar_notes
    if instrument == "bass":
        bass_notes = _fallback_melodic_notes(audio_path, instrument)
        if bass_notes:
            return bass_notes

    scale = [28, 31, 33, 35, 38, 40, 43]
    notes: list[NoteEvent] = []
    try:
        with wave.open(str(audio_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            total_frames = wav.getnframes()
            chunk_frames = max(1, int(sample_rate * 0.5))
            index = 0
            while index < total_frames:
                raw = wav.readframes(chunk_frames)
                if not raw:
                    break
                rms = _rms(raw, sample_width, channels)
                start = index / sample_rate
                if rms > 0.012:
                    pitch = scale[len(notes) % len(scale)]
                    notes.append(NoteEvent(start=start, end=start + 0.45, pitch=pitch, confidence=0.18))
                index += chunk_frames
    except Exception:
        for i in range(12):
            start = i * 0.5
            notes.append(NoteEvent(start=start, end=start + 0.4, pitch=scale[i % len(scale)], confidence=0.1))
    return notes


def _fallback_guitar_performance(audio_path: Path) -> list[NoteEvent]:
    loaded = _load_mono_wave(audio_path)
    if loaded is None:
        return []
    samples, sample_rate = loaded
    onsets = _detect_note_onsets(samples, sample_rate)
    melodic_notes = _estimate_melodic_notes(samples, sample_rate, "guitar", onsets)
    if _looks_melodic(melodic_notes, onsets):
        return melodic_notes
    return _fallback_guitar_chords(audio_path)


def _fallback_melodic_notes(audio_path: Path, instrument: str) -> list[NoteEvent]:
    loaded = _load_mono_wave(audio_path)
    if loaded is None:
        return []
    samples, sample_rate = loaded
    onsets = _detect_note_onsets(samples, sample_rate)
    return _estimate_melodic_notes(samples, sample_rate, instrument, onsets)


def _load_mono_wave(audio_path: Path):
    try:
        import numpy as np
    except Exception:
        return None

    try:
        with wave.open(str(audio_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            raw = wav.readframes(wav.getnframes())
    except Exception:
        return None
    if sample_width != 2 or not raw:
        return None
    samples = np.frombuffer(raw, dtype="<i2").astype("float32")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples = samples / 32768.0
    return samples, sample_rate


def _detect_note_onsets(samples, sample_rate: int) -> list[float]:
    try:
        import numpy as np
    except Exception:
        return []

    frame = max(512, int(sample_rate * 0.032))
    hop = max(128, int(sample_rate * 0.01))
    if len(samples) < frame:
        return [0.0]

    envelope = []
    for start in range(0, len(samples) - frame, hop):
        chunk = samples[start : start + frame]
        envelope.append(float(np.sqrt(np.mean(chunk * chunk))))
    if not envelope:
        return [0.0]
    envelope = np.array(envelope, dtype="float64")
    envelope = np.convolve(envelope, np.ones(5) / 5, mode="same")
    novelty = np.maximum(0, np.diff(envelope, prepend=envelope[0]))
    threshold = max(float(novelty.mean() + novelty.std() * 0.75), float(envelope.max() * 0.012))
    min_gap = max(1, int(0.09 / (hop / sample_rate)))
    peaks: list[int] = []
    last_peak = -min_gap
    for index in range(1, len(novelty) - 1):
        if index - last_peak < min_gap:
            continue
        if novelty[index] >= threshold and novelty[index] >= novelty[index - 1] and novelty[index] >= novelty[index + 1]:
            peaks.append(index)
            last_peak = index

    duration = len(samples) / sample_rate
    if len(peaks) < 4:
        step = 0.25
        return [round(time, 3) for time in [i * step for i in range(int(math.ceil(duration / step)))]]
    return [round(index * hop / sample_rate, 3) for index in peaks]


def _estimate_melodic_notes(samples, sample_rate: int, instrument: str, onsets: list[float]) -> list[NoteEvent]:
    try:
        import numpy as np
    except Exception:
        return []

    duration = len(samples) / sample_rate
    global_rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    if global_rms < 0.002:
        return []

    notes: list[NoteEvent] = []
    min_midi, max_midi = (40, 88) if instrument == "guitar" else (28, 55)
    min_freq = _midi_to_hz(min_midi)
    max_freq = _midi_to_hz(max_midi)
    sorted_onsets = sorted(time for time in onsets if 0 <= time < duration)
    for index, start in enumerate(sorted_onsets):
        next_start = sorted_onsets[index + 1] if index + 1 < len(sorted_onsets) else min(duration, start + 0.55)
        note_end = min(duration, max(start + 0.12, next_start - 0.025))
        begin = int((start + 0.018) * sample_rate)
        end = min(len(samples), begin + int(min(0.34, max(0.13, note_end - start)) * sample_rate))
        chunk = samples[begin:end]
        if len(chunk) < 512:
            continue
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        if rms < max(0.0025, global_rms * 0.10):
            continue
        freq = _estimate_fundamental_frequency(chunk, sample_rate, min_freq, max_freq, np)
        if freq is None:
            continue
        midi = int(round(69 + 12 * math.log2(freq / 440.0)))
        midi = max(min_midi, min(max_midi, midi))
        string, fret = _best_string_fret_for_pitch(midi, instrument)
        if string is None or fret is None:
            continue
        notes.append(
            NoteEvent(
                start=start,
                end=note_end,
                pitch=midi,
                velocity=max(45, min(116, int(52 + (rms / max(global_rms, 0.001)) * 36))),
                confidence=0.42,
                preferred_string=string,
                preferred_fret=fret,
            )
        )
    return _dedupe_close_notes(notes)


def _estimate_fundamental_frequency(chunk, sample_rate: int, min_freq: float, max_freq: float, np) -> float | None:
    chunk = chunk.astype("float64")
    chunk = chunk - float(chunk.mean())
    if float(np.max(np.abs(chunk))) <= 1e-5:
        return None
    windowed = chunk * np.hanning(len(chunk))
    autocorr = np.correlate(windowed, windowed, mode="full")[len(windowed) - 1 :]
    min_lag = max(1, int(sample_rate / max_freq))
    max_lag = min(len(autocorr) - 1, int(sample_rate / min_freq))
    if max_lag <= min_lag:
        return None
    search = autocorr[min_lag:max_lag]
    if len(search) == 0 or float(search.max()) <= 0:
        return None
    lag = int(np.argmax(search) + min_lag)
    if 1 <= lag < len(autocorr) - 1:
        alpha, beta, gamma = autocorr[lag - 1], autocorr[lag], autocorr[lag + 1]
        denom = alpha - 2 * beta + gamma
        if abs(float(denom)) > 1e-9:
            lag = lag + float(0.5 * (alpha - gamma) / denom)
    freq_ac = sample_rate / lag

    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(windowed), 1 / sample_rate)
    mask = (freqs >= min_freq) & (freqs <= max_freq)
    freq_fft = None
    if np.any(mask):
        masked_freqs = freqs[mask]
        masked_spec = spectrum[mask]
        peak = int(np.argmax(masked_spec))
        freq_fft = float(masked_freqs[peak])

    if freq_fft and abs(12 * math.log2(freq_fft / freq_ac)) > 7:
        return freq_fft
    return float(freq_ac)


def _midi_to_hz(midi: int) -> float:
    return 440.0 * (2 ** ((midi - 69) / 12))


def _best_string_fret_for_pitch(pitch: int, instrument: str) -> tuple[int | None, int | None]:
    candidates = []
    for index, (_, open_pitch) in enumerate(TUNINGS[instrument], start=1):
        fret = pitch - open_pitch
        if 0 <= fret <= 22:
            candidates.append((fret * 0.42 + index * 0.015, index, fret))
    if not candidates:
        return None, None
    _, string, fret = min(candidates)
    return string, fret


def _dedupe_close_notes(notes: list[NoteEvent]) -> list[NoteEvent]:
    deduped: list[NoteEvent] = []
    for note in sorted(notes, key=lambda item: item.start):
        if deduped and abs(deduped[-1].start - note.start) < 0.045 and abs(deduped[-1].pitch - note.pitch) <= 1:
            if note.confidence > deduped[-1].confidence:
                deduped[-1] = note
            continue
        deduped.append(note)
    return deduped


def _looks_melodic(notes: list[NoteEvent], onsets: list[float]) -> bool:
    if len(notes) >= 10:
        return True
    if len(notes) >= 5 and len(onsets) >= len(notes):
        unique_pitches = len({note.pitch for note in notes})
        return unique_pitches >= 3
    return False


GUITAR_CHORD_SHAPES: dict[str, list[int | None]] = {
    "C": [0, 1, 0, 2, 3, None],
    "D": [2, 3, 2, 0, None, None],
    "Dm": [1, 3, 2, 0, None, None],
    "E": [0, 0, 1, 2, 2, 0],
    "Em": [0, 0, 0, 2, 2, 0],
    "F": [1, 1, 2, 3, 3, 1],
    "G": [3, 0, 0, 0, 2, 3],
    "A": [0, 2, 2, 2, 0, None],
    "Am": [0, 1, 2, 2, 0, None],
    "Bm": [2, 3, 4, 4, 2, None],
}

CHORD_PITCH_CLASSES: dict[str, set[int]] = {
    "C": {0, 4, 7},
    "D": {2, 6, 9},
    "Dm": {2, 5, 9},
    "E": {4, 8, 11},
    "Em": {4, 7, 11},
    "F": {5, 9, 0},
    "G": {7, 11, 2},
    "A": {9, 1, 4},
    "Am": {9, 0, 4},
    "Bm": {11, 2, 6},
}


def _fallback_guitar_chords(audio_path: Path) -> list[NoteEvent]:
    try:
        import numpy as np
    except Exception:
        return []

    try:
        with wave.open(str(audio_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            raw = wav.readframes(frame_count)
    except Exception:
        return []

    if sample_width != 2 or not raw:
        return []

    samples = np.frombuffer(raw, dtype="<i2").astype("float32")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples = samples / 32768.0
    duration = len(samples) / sample_rate
    if duration <= 0:
        return []

    window_seconds = 0.9
    window_samples = max(2048, int(sample_rate * window_seconds))
    global_rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    if global_rms < 0.002:
        return []

    notes: list[NoteEvent] = []
    last_chord = "Em"
    open_pitches = [midi for _, midi in TUNINGS["guitar"]]
    strum_times = _detect_strum_times(samples, sample_rate, np)
    if not strum_times:
        strum_times = [index * 0.5 for index in range(max(1, int(math.ceil(duration / 0.5))))]

    for index, start in enumerate(strum_times):
        if start >= duration:
            continue
        center = int((start + 0.12) * sample_rate)
        begin = max(0, center - window_samples // 2)
        end = min(len(samples), begin + window_samples)
        chunk = samples[begin:end]
        if len(chunk) < 512:
            continue
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        if rms < max(0.003, global_rms * 0.16):
            continue

        chord = _estimate_chord(chunk, sample_rate, np) or last_chord
        if chord in GUITAR_CHORD_SHAPES:
            last_chord = chord
        shape = GUITAR_CHORD_SHAPES.get(last_chord, GUITAR_CHORD_SHAPES["Em"])
        velocity = max(45, min(112, int(55 + (rms / max(global_rms, 0.001)) * 28)))

        string_order = [6, 5, 4, 3, 2, 1] if index % 2 == 0 else [1, 2, 3, 4, 5, 6]
        for order_index, string in enumerate(string_order):
            open_pitch = open_pitches[string - 1]
            fret = shape[string - 1]
            if fret is None:
                continue
            note_start = min(start + order_index * 0.014, duration)
            notes.append(
                NoteEvent(
                    start=note_start,
                    end=min(note_start + 0.34, duration),
                    pitch=open_pitch + fret,
                    velocity=velocity,
                    confidence=0.32,
                    preferred_string=string,
                    preferred_fret=fret,
                    chord=last_chord,
                )
            )
    return notes


def _detect_strum_times(samples, sample_rate: int, np) -> list[float]:
    frame = max(512, int(sample_rate * 0.046))
    hop = max(128, int(sample_rate * 0.012))
    if len(samples) < frame:
        return [0.0]

    rms_values = []
    for start in range(0, len(samples) - frame, hop):
        chunk = samples[start : start + frame]
        rms_values.append(float(np.sqrt(np.mean(chunk * chunk))))
    if not rms_values:
        return [0.0]

    envelope = np.array(rms_values, dtype="float64")
    if float(envelope.max()) <= 0:
        return []
    smooth_size = 5
    kernel = np.ones(smooth_size) / smooth_size
    envelope = np.convolve(envelope, kernel, mode="same")
    novelty = np.maximum(0, np.diff(envelope, prepend=envelope[0]))
    threshold = max(float(novelty.mean() + novelty.std() * 0.75), float(envelope.max() * 0.018))
    min_gap = int(0.16 / (hop / sample_rate))

    peaks: list[int] = []
    last_peak = -min_gap
    for index in range(1, len(novelty) - 1):
        if index - last_peak < min_gap:
            continue
        if novelty[index] >= threshold and novelty[index] >= novelty[index - 1] and novelty[index] >= novelty[index + 1]:
            peaks.append(index)
            last_peak = index

    if len(peaks) < 4:
        duration = len(samples) / sample_rate
        beat = 0.5
        return [time for time in [index * beat for index in range(int(math.ceil(duration / beat)))] if _energy_near(envelope, hop, sample_rate, time)]

    return [round(index * hop / sample_rate, 3) for index in peaks]


def _energy_near(envelope, hop: int, sample_rate: int, time: float) -> bool:
    index = int(time * sample_rate / hop)
    if index >= len(envelope):
        return False
    start = max(0, index - 3)
    end = min(len(envelope), index + 4)
    local = float(envelope[start:end].max()) if end > start else 0.0
    return local >= max(0.003, float(envelope.max()) * 0.12)


def _estimate_chord(chunk, sample_rate: int, np) -> str | None:
    window = np.hanning(len(chunk))
    spectrum = np.abs(np.fft.rfft(chunk * window))
    freqs = np.fft.rfftfreq(len(chunk), 1 / sample_rate)
    mask = (freqs >= 70) & (freqs <= 1400)
    if not np.any(mask):
        return None
    chroma = np.zeros(12, dtype="float64")
    for freq, magnitude in zip(freqs[mask], spectrum[mask]):
        if magnitude <= 0:
            continue
        midi = int(round(69 + 12 * math.log2(float(freq) / 440.0)))
        chroma[midi % 12] += float(magnitude)
    total = float(chroma.sum())
    if total <= 0:
        return None
    chroma = chroma / total
    best_name = None
    best_score = -1.0
    for name, classes in CHORD_PITCH_CLASSES.items():
        score = sum(chroma[index] for index in classes)
        penalty = sum(chroma[index] for index in range(12) if index not in classes) * 0.18
        score -= penalty
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _rms(raw: bytes, sample_width: int, channels: int) -> float:
    if sample_width != 2 or not raw:
        return 0.0
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    if channels > 1:
        samples = samples[::channels]
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0


def _pitch_is_playable(pitch: int, instrument: str) -> bool:
    return any(0 <= pitch - midi <= 24 for _, midi in TUNINGS[instrument])


def build_tab(notes: list[NoteEvent], instrument: str) -> list[TabNote]:
    tab_notes: list[TabNote] = []
    previous_string = 0
    grouped: dict[int, list[NoteEvent]] = {}
    for note in notes:
        grouped.setdefault(int(round(note.start / SLOT_SECONDS)), []).append(note)

    for slot in sorted(grouped):
        slot_notes = sorted(grouped[slot], key=lambda item: item.pitch)
        used_strings: set[int] = set()
        for note in slot_notes:
            if (
                note.preferred_string is not None
                and note.preferred_fret is not None
                and note.preferred_string not in used_strings
            ):
                used_strings.add(note.preferred_string)
                previous_string = note.preferred_string
                tab_notes.append(
                    TabNote(
                        start=note.start,
                        end=note.end,
                        pitch=note.pitch,
                        string=note.preferred_string,
                        fret=note.preferred_fret,
                        velocity=note.velocity,
                        confidence=note.confidence,
                    )
                )
                continue
            candidates = []
            for index, (_, open_pitch) in enumerate(TUNINGS[instrument], start=1):
                if index in used_strings:
                    continue
                fret = note.pitch - open_pitch
                if 0 <= fret <= 24:
                    movement = abs(index - previous_string) * 0.12 if previous_string else 0
                    low_fret_cost = fret * 0.34
                    position_cost = abs(fret - 3) * 0.05
                    candidates.append((low_fret_cost + position_cost + movement, index, fret))
            if not candidates:
                continue
            _, string, fret = min(candidates)
            used_strings.add(string)
            previous_string = string
            tab_notes.append(
                TabNote(
                    start=note.start,
                    end=note.end,
                    pitch=note.pitch,
                    string=string,
                    fret=fret,
                    velocity=note.velocity,
                    confidence=note.confidence,
                )
            )
    return sorted(tab_notes, key=lambda item: (item.start, item.string))


def split_lead_rhythm(tab_notes: list[TabNote]) -> dict[str, list[TabNote]]:
    if not tab_notes:
        return {"lead": [], "rhythm": []}
    median_pitch = sorted(note.pitch for note in tab_notes)[len(tab_notes) // 2]
    grouped: dict[int, list[TabNote]] = {}
    for note in tab_notes:
        slot = int(round(note.start / SLOT_SECONDS))
        grouped.setdefault(slot, []).append(note)

    lead: list[TabNote] = []
    rhythm: list[TabNote] = []
    for slot_notes in grouped.values():
        if len(slot_notes) >= 2:
            rhythm.extend(slot_notes)
        else:
            note = slot_notes[0]
            (lead if note.pitch >= median_pitch else rhythm).append(note)
    return {"lead": sorted(lead, key=lambda n: n.start), "rhythm": sorted(rhythm, key=lambda n: n.start)}


def export_all(tab_notes: list[TabNote], instrument: str, output_dir: Path, title: str) -> dict[str, Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / instrument
    artifacts: dict[str, Path | None] = {}
    artifacts["json"] = base.with_suffix(".json")
    artifacts["musicxml"] = base.with_suffix(".musicxml")
    artifacts["mid"] = base.with_suffix(".mid")
    artifacts["svg"] = base.with_suffix(".svg")
    artifacts["png"] = base.with_suffix(".png")
    artifacts["pdf"] = base.with_suffix(".pdf")
    artifacts["gp5"] = base.with_suffix(".gp5")

    _write_json(tab_notes, instrument, artifacts["json"], title)
    _write_musicxml(tab_notes, instrument, artifacts["musicxml"], title)
    _write_midi(tab_notes, instrument, artifacts["mid"])
    ascii_lines = render_ascii(tab_notes, instrument)
    _write_svg(ascii_lines, artifacts["svg"], title, instrument)
    _write_png(ascii_lines, artifacts["png"], title, instrument)
    _write_pdf(ascii_lines, artifacts["pdf"], title, instrument)
    if not _write_gp5(tab_notes, instrument, artifacts["gp5"], title):
        artifacts["gp5"] = None
    return artifacts


def _write_json(tab_notes: list[TabNote], instrument: str, path: Path, title: str) -> None:
    guitar_parts = None
    if instrument == "guitar":
        split = split_lead_rhythm(tab_notes)
        guitar_parts = {name: [asdict(note) for note in notes] for name, notes in split.items()}
    payload = {
        "title": title,
        "instrument": instrument,
        "tempo": TEMPO,
        "tuning": [{"label": label, "midi": midi} for label, midi in TUNINGS[instrument]],
        "notes": [asdict(note) for note in tab_notes],
        "guitar_parts": guitar_parts,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_ascii(tab_notes: list[TabNote], instrument: str) -> list[str]:
    measure_count = max(1, math.ceil(max([note.end for note in tab_notes] + [MEASURE_SECONDS]) / MEASURE_SECONDS))
    width = measure_count * (SLOTS_PER_MEASURE + 1)
    lines = [[label.ljust(3) + "|" + "-" * width] for label, _ in TUNINGS[instrument]]
    grids = [list(line[0]) for line in lines]

    for measure in range(measure_count + 1):
        column = 4 + measure * (SLOTS_PER_MEASURE + 1)
        for grid in grids:
            if column < len(grid):
                grid[column] = "|"

    for note in tab_notes:
        slot = int(round(note.start / SLOT_SECONDS))
        measure = slot // SLOTS_PER_MEASURE
        slot_in_measure = slot % SLOTS_PER_MEASURE
        column = 5 + measure * (SLOTS_PER_MEASURE + 1) + slot_in_measure
        grid = grids[note.string - 1]
        fret_text = str(note.fret)
        for offset, char in enumerate(fret_text):
            if column + offset < len(grid):
                grid[column + offset] = char
    return ["".join(grid) for grid in grids]


def render_ascii_systems(tab_notes: list[TabNote], instrument: str, measures_per_system: int = 4) -> list[list[str]]:
    measure_count = max(1, math.ceil(max([note.end for note in tab_notes] + [MEASURE_SECONDS]) / MEASURE_SECONDS))
    systems: list[list[str]] = []
    for start_measure in range(0, measure_count, measures_per_system):
        end_measure = min(measure_count, start_measure + measures_per_system)
        width = (end_measure - start_measure) * (SLOTS_PER_MEASURE + 1)
        grids = [list(label.ljust(3) + "|" + "-" * width) for label, _ in TUNINGS[instrument]]
        for measure in range(end_measure - start_measure + 1):
            column = 4 + measure * (SLOTS_PER_MEASURE + 1)
            for grid in grids:
                if column < len(grid):
                    grid[column] = "|"
        for note in tab_notes:
            absolute_slot = int(round(note.start / SLOT_SECONDS))
            measure = absolute_slot // SLOTS_PER_MEASURE
            if not (start_measure <= measure < end_measure):
                continue
            slot_in_measure = absolute_slot % SLOTS_PER_MEASURE
            local_measure = measure - start_measure
            column = 5 + local_measure * (SLOTS_PER_MEASURE + 1) + slot_in_measure
            grid = grids[note.string - 1]
            fret_text = str(note.fret)
            for offset, char in enumerate(fret_text):
                if column + offset < len(grid):
                    grid[column + offset] = char
        systems.append(["".join(grid) for grid in grids])
    return systems


def _write_musicxml(tab_notes: list[TabNote], instrument: str, path: Path, title: str) -> None:
    measures: dict[int, list[TabNote]] = {}
    for note in tab_notes:
        measures.setdefault(int(note.start // MEASURE_SECONDS) + 1, []).append(note)
    measure_count = max(1, math.ceil(max([note.end for note in tab_notes] + [MEASURE_SECONDS]) / MEASURE_SECONDS))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<score-partwise version="3.1">',
        "  <part-list>",
        f'    <score-part id="P1"><part-name>{escape(instrument.title())}</part-name></score-part>',
        "  </part-list>",
        '  <part id="P1">',
    ]
    for measure_number in range(1, measure_count + 1):
        lines.append(f'    <measure number="{measure_number}">')
        if measure_number == 1:
            lines.extend(
                [
                    "      <attributes>",
                    "        <divisions>4</divisions>",
                    "        <key><fifths>0</fifths></key>",
                    "        <time><beats>4</beats><beat-type>4</beat-type></time>",
                    "        <clef><sign>TAB</sign><line>5</line></clef>",
                    "      </attributes>",
                ]
            )
        for note in measures.get(measure_number, []):
            step, alter, octave = _pitch_parts(note.pitch)
            alter_xml = f"<alter>{alter}</alter>" if alter else ""
            lines.extend(
                [
                    "      <note>",
                    f"        <pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>",
                    "        <duration>2</duration><type>eighth</type>",
                    "        <notations><technical>"
                    f"<string>{note.string}</string><fret>{note.fret}</fret>"
                    "</technical></notations>",
                    "      </note>",
                ]
            )
        if not measures.get(measure_number):
            lines.append("      <note><rest/><duration>8</duration><type>half</type></note>")
        lines.append("    </measure>")
    lines.extend(["  </part>", "</score-partwise>"])
    path.write_text("\n".join(lines), encoding="utf-8")


def _pitch_parts(midi: int) -> tuple[str, int, int]:
    names = [("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0), ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0)]
    step, alter = names[midi % 12]
    octave = midi // 12 - 1
    return step, alter, octave


def _write_midi(tab_notes: list[TabNote], instrument: str, path: Path) -> None:
    ticks_per_beat = 480
    events = [(0, bytes([0xC0, PROGRAMS[instrument]]))]
    tempo_mpq = int(60_000_000 / TEMPO)
    events.append((0, b"\xff\x51\x03" + tempo_mpq.to_bytes(3, "big")))
    for note in tab_notes:
        start = int(note.start * ticks_per_beat * TEMPO / 60)
        end = int(note.end * ticks_per_beat * TEMPO / 60)
        events.append((start, bytes([0x90, note.pitch, max(1, min(127, note.velocity))])))
        events.append((max(start + 1, end), bytes([0x80, note.pitch, 0])))
    events.sort(key=lambda event: (event[0], event[1][0]))
    track = bytearray()
    last_tick = 0
    for tick, payload in events:
        track.extend(_var_len(max(0, tick - last_tick)))
        track.extend(payload)
        last_tick = tick
    track.extend(b"\x00\xff\x2f\x00")
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, ticks_per_beat)
    chunk = b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    path.write_bytes(header + chunk)


def _var_len(value: int) -> bytes:
    result = [value & 0x7F]
    value >>= 7
    while value:
        result.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(result)


def _write_svg(lines: list[str], path: Path, title: str, instrument: str) -> None:
    systems = _lines_to_systems(lines, instrument)
    width = max(980, max(len(line) for system in systems for line in system) * 8 + 48)
    height = 74 + sum(len(system) * 22 + 22 for system in systems)
    text_lines = []
    y = 64
    for system in systems:
        for line in system:
            text_lines.append(
                f'<text x="24" y="{y}" font-family="Consolas, monospace" font-size="16">{escape(line)}</text>'
            )
            y += 22
        y += 18
    text = "\n".join(text_lines)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#fbfaf7"/>
<text x="24" y="32" font-family="Arial, sans-serif" font-size="20" font-weight="700">{escape(title)} - {escape(instrument.title())}</text>
{text}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def _write_png(lines: list[str], path: Path, title: str, instrument: str) -> None:
    if _write_png_with_pillow(lines, path, title, instrument):
        return
    systems = _lines_to_systems(lines, instrument)
    text_lines = [f"{title} - {instrument.title()}", ""]
    for system in systems:
        text_lines.extend(system)
        text_lines.append("")
    scale = 2
    char_w, char_h = 6 * scale, 8 * scale
    width = max(640, max(len(line) for line in text_lines) * char_w + 32)
    height = len(text_lines) * (char_h + 6) + 32
    pixels = bytearray([250, 248, 242] * width * height)

    def set_px(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            idx = (y * width + x) * 3
            pixels[idx : idx + 3] = bytes(color)

    for row, line in enumerate(text_lines):
        y = 16 + row * (char_h + 6)
        for col, char in enumerate(line):
            _draw_char(set_px, 16 + col * char_w, y, char, scale)

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride : (y + 1) * stride])
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def _write_png_with_pillow(lines: list[str], path: Path, title: str, instrument: str) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False

    systems = _lines_to_systems(lines, instrument)
    font = _load_monospace_font(ImageFont, 20, bold=False)
    title_font = _load_monospace_font(ImageFont, 24, bold=True) or font

    text_lines = [f"{title} - {instrument.title()}", ""]
    for system in systems:
        text_lines.extend(system)
        text_lines.append("")

    dummy = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy)
    widths = [draw.textbbox((0, 0), line, font=title_font if index == 0 else font)[2] for index, line in enumerate(text_lines)]
    line_height = 28
    width = max(960, max(widths, default=0) + 80)
    height = max(360, 56 + len(text_lines) * line_height + 40)
    image = Image.new("RGB", (width, height), "#fbfaf7")
    draw = ImageDraw.Draw(image)
    y = 36
    for index, line in enumerate(text_lines):
        draw.text((40, y), line, fill="#17191e", font=title_font if index == 0 else font)
        y += line_height
    image.save(path)
    return True


def _load_monospace_font(image_font, size: int, bold: bool):
    candidates = [
        "C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Menlo.ttc",
    ]
    for candidate in candidates:
        try:
            return image_font.truetype(candidate, size)
        except Exception:
            continue
    return image_font.load_default()


FONT = {
    "-": ["00000", "00000", "00000", "11110", "00000", "00000", "00000"],
    "|": ["00100", "00100", "00100", "00100", "00100", "00100", "00100"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
}


def _draw_char(set_px, x: int, y: int, char: str, scale: int) -> None:
    pattern = FONT.get(char.upper(), FONT.get("-") if char in "-|" else None)
    if pattern is None:
        pattern = ["00000", "00000", "00000", "00000", "00000", "00000", "00000"]
    for py, row in enumerate(pattern):
        for px, bit in enumerate(row):
            if bit == "1":
                for sy in range(scale):
                    for sx in range(scale):
                        set_px(x + px * scale + sx, y + py * scale + sy, (22, 24, 28))


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _write_pdf(lines: list[str], path: Path, title: str, instrument: str) -> None:
    systems = _lines_to_systems(lines, instrument)
    escaped_lines = [f"{title} - {instrument.title()}", ""]
    for system in systems:
        escaped_lines.extend(system)
        escaped_lines.append("")
    content = ["BT", "/F1 12 Tf", "40 780 Td"]
    for index, line in enumerate(escaped_lines):
        if index:
            content.append("0 -18 Td")
        content.append(f"({line.replace('\\\\', '\\\\\\\\').replace('(', '\\\\(').replace(')', '\\\\)')}) Tj")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    path.write_bytes(bytes(pdf))


def _lines_to_systems(lines: list[str], instrument: str) -> list[list[str]]:
    line_count = len(TUNINGS[instrument])
    if not lines:
        return []
    if len(lines) > line_count:
        return [lines[index : index + line_count] for index in range(0, len(lines), line_count)]
    body_width = max(1, min(len(line) - 4 for line in lines))
    max_body = SLOTS_PER_MEASURE * 4 + 4
    if body_width <= max_body:
        return [lines]
    systems: list[list[str]] = []
    for start in range(4, 4 + body_width, max_body):
        system = []
        for line in lines:
            label = line[:4]
            chunk = line[start : min(len(line), start + max_body)]
            system.append(label + chunk)
        systems.append(system)
    return systems


def _write_gp5(tab_notes: list[TabNote], instrument: str, path: Path, title: str) -> bool:
    try:
        import guitarpro
        from guitarpro import models as gp

        measure_count = max(1, math.ceil(max([note.end for note in tab_notes] + [MEASURE_SECONDS]) / MEASURE_SECONDS))
        song = gp.Song(tracks=[], measureHeaders=[])
        song.title = title
        song.tempo = TEMPO
        for number in range(1, measure_count + 1):
            header = gp.MeasureHeader(number=number)
            header.start = gp.Duration.quarterTime + (number - 1) * header.length
            song.measureHeaders.append(header)

        track = gp.Track(song)
        track.name = instrument.title()
        track.channel.instrument = PROGRAMS[instrument]
        track.strings = [gp.GuitarString(index, midi) for index, (_, midi) in enumerate(TUNINGS[instrument], start=1)]
        track.measures = []
        song.tracks.append(track)

        by_measure_slot: dict[tuple[int, int], list[TabNote]] = {}
        for note in tab_notes:
            slot = int(round(note.start / SLOT_SECONDS))
            by_measure_slot.setdefault((slot // SLOTS_PER_MEASURE, slot % SLOTS_PER_MEASURE), []).append(note)

        for measure_index, header in enumerate(song.measureHeaders):
            measure = gp.Measure(track, header)
            voice = measure.voices[0]
            for slot in range(SLOTS_PER_MEASURE):
                beat = gp.Beat(voice)
                beat.duration = gp.Duration(gp.Duration.sixteenth)
                beat.start = header.start + slot * beat.duration.time
                slot_notes = by_measure_slot.get((measure_index, slot), [])
                if slot_notes:
                    beat.status = gp.BeatStatus.normal
                    for tab_note in slot_notes[: len(TUNINGS[instrument])]:
                        beat.notes.append(
                            gp.Note(
                                beat=beat,
                                value=tab_note.fret,
                                velocity=max(1, min(127, tab_note.velocity)),
                                string=tab_note.string,
                                type=gp.NoteType.normal,
                            )
                        )
                else:
                    beat.status = gp.BeatStatus.rest
                voice.beats.append(beat)
            track.measures.append(measure)
        guitarpro.write(song, str(path))
        return True
    except Exception:
        if path.exists():
            path.unlink()
        return False
