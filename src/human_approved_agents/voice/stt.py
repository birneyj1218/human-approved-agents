"""Speech-to-text with faster-whisper. The model loads lazily on first use."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any


class VoiceUnavailable(RuntimeError):
    pass


def _default_factory(model_size: str, device: str) -> Any:
    try:
        fw = importlib.import_module("faster_whisper")
    except ImportError as exc:
        raise VoiceUnavailable("faster-whisper is not installed (pip install '.[voice]')") from exc
    compute_type = "float16" if device == "cuda" else "int8"
    return fw.WhisperModel(model_size, device=device, compute_type=compute_type)


class Transcriber:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        *,
        factory: Callable[[str, str], Any] = _default_factory,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self._factory = factory
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                self._model = self._factory(self.model_size, self.device)
            except VoiceUnavailable:
                raise
            except Exception as exc:
                if self.device != "cuda":
                    raise VoiceUnavailable(f"could not load speech model: {exc}") from exc
                # GPU present but unusable (driver, memory): retry on CPU once.
                self.device = "cpu"
                self._model = self._factory(self.model_size, "cpu")
        return self._model

    def transcribe(self, audio_path: Path) -> str:
        model = self._load()
        segments, _info = model.transcribe(str(audio_path), language="en", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
