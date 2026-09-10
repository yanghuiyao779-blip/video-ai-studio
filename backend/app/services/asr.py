from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import get_settings
from app.services.domain import Transcript, TranscriptSegment
from app.services.text_normalizer import normalize_simplified_chinese

_models: dict[tuple[str, str, str], Any] = {}
_models_lock = Lock()


def _get_model(model_name: str):
    from faster_whisper import WhisperModel

    settings = get_settings()
    key = (model_name, settings.asr_device, settings.asr_compute_type)
    with _models_lock:
        if key not in _models:
            kwargs = {
                "device": settings.asr_device,
                "compute_type": settings.asr_compute_type,
            }
            if settings.asr_cpu_threads > 0:
                kwargs["cpu_threads"] = settings.asr_cpu_threads
            _models[key] = WhisperModel(model_name, **kwargs)
        return _models[key]


def transcribe(audio_path: Path, model_name: str, language: str | None = None) -> Transcript:
    model = _get_model(model_name)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language or None,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    detected_language = str(getattr(info, "language", language or "unknown"))
    segments: list[TranscriptSegment] = []
    last_end = 0.0
    for item in segments_iter:
        text = normalize_simplified_chinese(item.text.strip(), detected_language)
        if not text:
            continue
        last_end = float(item.end)
        segments.append(
            TranscriptSegment(start=float(item.start), end=float(item.end), text=text)
        )
    duration = float(getattr(info, "duration", 0.0) or last_end)
    probability = getattr(info, "language_probability", None)
    return Transcript(
        language=detected_language,
        language_probability=float(probability) if probability is not None else None,
        duration=duration,
        segments=segments,
    )
