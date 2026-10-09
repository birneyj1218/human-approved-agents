from __future__ import annotations

import importlib
import logging

log = logging.getLogger(__name__)


def cuda_available() -> bool:
    """True if CTranslate2 (used by faster-whisper) can see a CUDA device."""
    try:
        ct2 = importlib.import_module("ctranslate2")
    except ImportError:
        return False
    try:
        return int(ct2.get_cuda_device_count()) > 0
    except Exception:  # driver missing or broken: treat as no GPU
        log.info("CUDA check failed; using CPU for voice")
        return False


def choose_device(preference: str, *, has_cuda: bool | None = None) -> str | None:
    """Resolve VOICE_DEVICE to "cuda", "cpu", or None (voice off).

    ``auto`` uses the GPU when there is one and falls back to CPU.
    ``cuda`` falls back to CPU with a warning rather than failing.
    """
    pref = preference.lower()
    if pref == "off":
        return None
    gpu = cuda_available() if has_cuda is None else has_cuda
    if pref == "cpu":
        return "cpu"
    if pref == "cuda" and not gpu:
        log.warning("VOICE_DEVICE=cuda but no GPU found; falling back to CPU")
    return "cuda" if gpu else "cpu"
