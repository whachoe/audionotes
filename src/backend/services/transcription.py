"""Speech-to-text via faster-whisper.

The WhisperModel is a lazily-initialized module-level singleton so that it is
only loaded into memory the first time a transcription job actually runs, not
at application startup (so /health responds instantly).
"""
from __future__ import annotations

import logging

from ..config import get_settings

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        settings = get_settings()
        logger.info(
            "Loading faster-whisper model size=%s device=%s compute_type=%s",
            settings.WHISPER_MODEL_SIZE,
            settings.WHISPER_DEVICE,
            settings.WHISPER_COMPUTE_TYPE,
        )
        _model = WhisperModel(
            settings.WHISPER_MODEL_SIZE,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
        )
    return _model


def transcribe_audio(audio_path: str) -> str:
    """Synchronous, CPU-bound transcription. Call via run_in_executor from async code.

    Returns the joined transcript text. Raises on failure (caller marks the
    note as failed with the exception message as processing_error).
    """
    model = _get_model()
    segments, _info = model.transcribe(audio_path, beam_size=5, vad_filter=True)
    text_parts = [segment.text.strip() for segment in segments]
    return " ".join(part for part in text_parts if part).strip()
