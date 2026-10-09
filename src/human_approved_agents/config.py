"""Settings come from environment variables only. No secrets in files."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"not a boolean: {value!r}")


def _int(value: str | None, default: int, name: str) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        n = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if n < 0:
        raise ConfigError(f"{name} must not be negative")
    return n


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    profiles_dir: Path = Path("profiles")
    fixtures_dir: Path = Path("fixtures")

    llm_provider: str = "fake"  # fake | openai
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = field(default="", repr=False)
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: int = 60

    approver_ids: frozenset[str] = frozenset()
    cli_user_id: str = "cli-owner"
    discord_token: str = field(default="", repr=False)
    discord_channel_id: int = 0

    send_enabled: bool = False
    sender: str = "console"  # console | file
    max_sends_per_hour: int = 20
    max_commands_per_minute: int = 10
    max_redrafts: int = 2

    voice_enabled: bool = False
    voice_device: str = "auto"  # auto | cuda | cpu | off
    whisper_model: str = "small"
    piper_voice_path: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "haa.sqlite3"

    @property
    def audit_path(self) -> Path:
        return self.data_dir / "audit.jsonl"

    @property
    def outbox_path(self) -> Path:
        return self.data_dir / "outbox.jsonl"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        provider = e.get("LLM_PROVIDER", "fake").strip().lower()
        if provider not in {"fake", "openai"}:
            raise ConfigError("LLM_PROVIDER must be 'fake' or 'openai'")
        sender = e.get("SENDER", "console").strip().lower()
        if sender not in {"console", "file"}:
            raise ConfigError("SENDER must be 'console' or 'file'")
        device = e.get("VOICE_DEVICE", "auto").strip().lower()
        if device not in {"auto", "cuda", "cpu", "off"}:
            raise ConfigError("VOICE_DEVICE must be auto, cuda, cpu or off")
        ids = frozenset(x.strip() for x in e.get("APPROVER_USER_IDS", "").split(",") if x.strip())
        return cls(
            data_dir=Path(e.get("DATA_DIR", "data")),
            profiles_dir=Path(e.get("PROFILES_DIR", "profiles")),
            fixtures_dir=Path(e.get("FIXTURES_DIR", "fixtures")),
            llm_provider=provider,
            llm_base_url=e.get("LLM_BASE_URL", cls.llm_base_url).rstrip("/"),
            llm_api_key=e.get("LLM_API_KEY", ""),
            llm_model=e.get("LLM_MODEL", cls.llm_model),
            llm_timeout_s=_int(e.get("LLM_TIMEOUT_S"), 60, "LLM_TIMEOUT_S"),
            approver_ids=ids,
            cli_user_id=e.get("CLI_USER_ID", "cli-owner").strip(),
            discord_token=e.get("DISCORD_BOT_TOKEN", ""),
            discord_channel_id=_int(e.get("DISCORD_CHANNEL_ID"), 0, "DISCORD_CHANNEL_ID"),
            send_enabled=_bool(e.get("SEND_ENABLED"), False),
            sender=sender,
            max_sends_per_hour=_int(e.get("MAX_SENDS_PER_HOUR"), 20, "MAX_SENDS_PER_HOUR"),
            max_commands_per_minute=_int(
                e.get("MAX_COMMANDS_PER_MINUTE"), 10, "MAX_COMMANDS_PER_MINUTE"
            ),
            max_redrafts=_int(e.get("MAX_REDRAFTS"), 2, "MAX_REDRAFTS"),
            voice_enabled=_bool(e.get("VOICE_ENABLED"), False),
            voice_device=device,
            whisper_model=e.get("WHISPER_MODEL", "small"),
            piper_voice_path=e.get("PIPER_VOICE_PATH", ""),
        )

    def require_approvers(self) -> None:
        """Refuse to run a live loop with nobody allowed to approve."""
        if not self.approver_ids:
            raise ConfigError("APPROVER_USER_IDS is empty: nobody could approve anything")
