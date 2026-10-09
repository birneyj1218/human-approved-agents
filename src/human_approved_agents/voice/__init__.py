"""Optional local voice: speech-to-text (faster-whisper) and text-to-speech (Piper).

Install with ``pip install -e '.[voice]'``. Everything here degrades
gracefully: no package, no GPU, or VOICE_DEVICE=off just means voice is off
and the text commands keep working.
"""

from .device import choose_device
from .normalize import transcript_to_command
from .stt import Transcriber, VoiceUnavailable
from .tts import Speaker, queue_summary

__all__ = [
    "Speaker",
    "Transcriber",
    "VoiceUnavailable",
    "choose_device",
    "queue_summary",
    "transcript_to_command",
]
