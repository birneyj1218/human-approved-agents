"""Voice tests use fake backends. No model is downloaded or loaded."""

import builtins
import wave
from datetime import UTC, datetime

import pytest

from human_approved_agents.models import Item, Lead, State, Version
from human_approved_agents.voice import (
    Speaker,
    Transcriber,
    VoiceUnavailable,
    choose_device,
    queue_summary,
    transcript_to_command,
)
from human_approved_agents.voice import device as device_mod


@pytest.mark.parametrize(
    ("pref", "gpu", "expected"),
    [
        ("off", True, None),
        ("cpu", True, "cpu"),
        ("auto", True, "cuda"),
        ("auto", False, "cpu"),
        ("cuda", False, "cpu"),
        ("cuda", True, "cuda"),
    ],
)
def test_choose_device(pref, gpu, expected):
    assert choose_device(pref, has_cuda=gpu) == expected


def test_cuda_check_without_ctranslate2(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "ctranslate2":
            raise ImportError
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(device_mod.importlib, "import_module", lambda n: fake_import(n))
    assert device_mod.cuda_available() is False
    assert choose_device("auto") == "cpu"


def test_cuda_check_with_broken_driver(monkeypatch):
    class Broken:
        @staticmethod
        def get_cuda_device_count():
            raise RuntimeError("driver")

    monkeypatch.setattr(device_mod.importlib, "import_module", lambda n: Broken)
    assert device_mod.cuda_available() is False


@pytest.mark.parametrize(
    ("heard", "command"),
    [
        ("Approve number three, version two.", "approve 3 v2"),
        ("approve twenty one version one", "approve 21 v1"),
        ("Approve 7 version 3", "approve 7 v3"),
        ("approve number five", "approve 5"),
        ("Approve three and four", "approve 3 and 4"),
        ("Reject two, too pushy.", "reject 2 too pushy"),
        ("show me number nine", "show 9"),
        ("show nine", "show 9"),
        ("What's in the queue", "What's in the queue"),
        ("queue", "list"),
        ("", ""),
    ],
)
def test_transcript_to_command(heard, command):
    assert transcript_to_command(heard) == command


def test_homophones_are_not_numbers():
    assert transcript_to_command("approve to version for") == "approve to version for"


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def transcribe(self, path, **kw):
        return [FakeSegment(" approve three "), FakeSegment("version two. ")], None


def test_transcriber_loads_lazily_once():
    loads = []

    def factory(size, device):
        loads.append((size, device))
        return FakeModel()

    t = Transcriber("tiny", "cuda", factory=factory)
    assert loads == []
    assert t.transcribe("x.ogg") == "approve three version two."
    t.transcribe("y.ogg")
    assert loads == [("tiny", "cuda")]


def test_transcriber_falls_back_to_cpu_when_gpu_fails():
    def factory(size, device):
        if device == "cuda":
            raise RuntimeError("out of memory")
        return FakeModel()

    t = Transcriber("tiny", "cuda", factory=factory)
    assert t.transcribe("x.ogg")
    assert t.device == "cpu"


def test_transcriber_cpu_failure_is_voice_unavailable():
    def factory(size, device):
        raise RuntimeError("bad model")

    with pytest.raises(VoiceUnavailable):
        Transcriber("tiny", "cpu", factory=factory).transcribe("x.ogg")


def test_missing_packages_raise_voice_unavailable(monkeypatch, tmp_path):
    def no_module(name):
        raise ImportError(name)

    from human_approved_agents.voice import stt, tts

    monkeypatch.setattr(stt.importlib, "import_module", no_module)
    monkeypatch.setattr(tts.importlib, "import_module", no_module)
    with pytest.raises(VoiceUnavailable, match="faster-whisper"):
        Transcriber("tiny", "cpu").transcribe("x.ogg")
    with pytest.raises(VoiceUnavailable, match="PIPER_VOICE_PATH"):
        Speaker("").speak("hi", tmp_path / "a.wav")
    voice = tmp_path / "v.onnx"
    voice.write_bytes(b"")
    with pytest.raises(VoiceUnavailable, match="piper-tts"):
        Speaker(str(voice)).speak("hi", tmp_path / "a.wav")


class FakeVoice:
    def __init__(self, new_api):
        self.new_api = new_api

    def _write(self, text, wav):
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * len(text))

    def __getattr__(self, name):
        if name == "synthesize_wav" and self.new_api:
            return self._write
        if name == "synthesize" and not self.new_api:
            return self._write
        raise AttributeError(name)


@pytest.mark.parametrize("new_api", [True, False])
def test_speaker_writes_wav(tmp_path, new_api):
    out = Speaker("v.onnx", loader=lambda p: FakeVoice(new_api)).speak(
        "hello", tmp_path / "o" / "a.wav"
    )
    with wave.open(str(out)) as w:
        assert w.getnframes() == 5


def _item(i):
    lead = Lead("p", str(i), f"Title {i}", "b")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Item(i, lead, State.AWAITING_APPROVAL, now, [Version(1, "t", "drafter", now)])


def test_queue_summary():
    assert queue_summary([]) == "Nothing is waiting for your approval."
    one = queue_summary([_item(1)])
    assert one.startswith("1 item waiting")
    assert "Number 1, version 1: Title 1." in one
    many = queue_summary([_item(i) for i in range(1, 8)])
    assert many.startswith("7 items")
    assert many.endswith("And 2 more.")
