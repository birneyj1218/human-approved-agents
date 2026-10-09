"""Text-to-speech with Piper: read the approval queue aloud as a WAV file."""

from __future__ import annotations

import importlib
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..models import Item
from .stt import VoiceUnavailable


def _default_loader(voice_path: str) -> Any:
    if not voice_path or not Path(voice_path).exists():
        raise VoiceUnavailable("PIPER_VOICE_PATH does not point at a .onnx voice file")
    try:
        piper = importlib.import_module("piper")
    except ImportError as exc:
        raise VoiceUnavailable("piper-tts is not installed (pip install '.[voice]')") from exc
    return piper.PiperVoice.load(voice_path)


def queue_summary(items: Sequence[Item]) -> str:
    """A short spoken summary; no draft text, just what is waiting."""
    if not items:
        return "Nothing is waiting for your approval."
    n = len(items)
    parts = [f"{n} item{'s' if n != 1 else ''} waiting for approval."]
    for i in items[:5]:
        v = i.current.number if i.current else 0
        parts.append(f"Number {i.id}, version {v}: {i.lead.title}.")
    if n > 5:
        parts.append(f"And {n - 5} more.")
    return " ".join(parts)


class Speaker:
    def __init__(self, voice_path: str, *, loader: Callable[[str], Any] = _default_loader) -> None:
        self.voice_path = voice_path
        self._loader = loader
        self._voice: Any = None

    def speak(self, text: str, out_path: Path) -> Path:
        if self._voice is None:
            self._voice = self._loader(self.voice_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wav:
            # piper-tts >= 1.3 has synthesize_wav; older versions use synthesize.
            if hasattr(self._voice, "synthesize_wav"):
                self._voice.synthesize_wav(text, wav)
            else:
                self._voice.synthesize(text, wav)
        return out_path
