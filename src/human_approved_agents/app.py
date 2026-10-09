"""Wire the pieces together from Settings."""

from __future__ import annotations

from datetime import timedelta

from .agents import Drafter, JsonInboxSource, Researcher, Reviewer, RssFileSource, Source
from .approval.gate import ApprovalGate
from .audit import AuditLog
from .clock import Clock, utcnow
from .config import Settings
from .llm import LLM, FakeLLM, OpenAICompatibleClient
from .memory import Memory
from .orchestrator import Orchestrator
from .profiles import Profile, load_profiles
from .ratelimit import SlidingWindowLimiter
from .senders import ConsoleSender, Delivery, FileSender, Sender
from .store import Store


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "fake":
        return FakeLLM()
    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_s=settings.llm_timeout_s,
    )


def build_sources(
    settings: Settings, profiles: dict[str, Profile]
) -> tuple[list[Source], dict[str, list[str]]]:
    sources: list[Source] = []
    keywords: dict[str, list[str]] = {}
    for p in profiles.values():
        src = p.source
        if not src:
            continue
        path = settings.fixtures_dir / str(src["path"])
        if src.get("type") == "rss":
            sources.append(RssFileSource(path, p.name))
        elif src.get("type") == "json_inbox":
            sources.append(JsonInboxSource(path, p.name))
        else:
            raise ValueError(f"profile {p.name}: unknown source type {src.get('type')!r}")
        kw = src.get("keywords", [])
        if isinstance(kw, list):
            keywords[p.name] = [str(k) for k in kw]
    return sources, keywords


def build(
    settings: Settings,
    *,
    llm: LLM | None = None,
    sender: Sender | None = None,
    clock: Clock = utcnow,
    owner_name: str = "The owner",
) -> Orchestrator:
    profiles = load_profiles(settings.profiles_dir)
    store = Store(settings.db_path)
    audit = AuditLog(settings.audit_path, clock)
    memory = Memory(store, owner_name=owner_name)
    sources, keywords = build_sources(settings, profiles)
    if sender is None:
        sender = (
            FileSender(settings.outbox_path, clock)
            if settings.sender == "file"
            else ConsoleSender()
        )
    gate = ApprovalGate(
        store=store,
        memory=memory,
        audit=audit,
        approvers=settings.approver_ids,
        limiter=SlidingWindowLimiter(settings.max_commands_per_minute, timedelta(minutes=1), clock),
        clock=clock,
    )
    delivery = Delivery(
        sender,
        send_enabled=settings.send_enabled,
        limiter=SlidingWindowLimiter(settings.max_sends_per_hour, timedelta(hours=1), clock),
    )
    return Orchestrator(
        profiles=profiles,
        researcher=Researcher(sources, keywords),
        drafter=Drafter(llm or build_llm(settings)),
        reviewer=Reviewer(),
        store=store,
        memory=memory,
        audit=audit,
        gate=gate,
        delivery=delivery,
        max_redrafts=settings.max_redrafts,
        clock=clock,
    )
