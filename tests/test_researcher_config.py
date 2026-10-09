from pathlib import Path

import pytest

from human_approved_agents.agents import JsonInboxSource, Researcher, RssFileSource
from human_approved_agents.app import build_llm, build_sources
from human_approved_agents.config import ConfigError, Settings
from human_approved_agents.llm import FakeLLM, OpenAICompatibleClient
from human_approved_agents.models import Lead
from human_approved_agents.profiles import load_profiles

ROOT = Path(__file__).resolve().parents[1]


def test_rss_source_parses_fixture():
    leads = list(RssFileSource(ROOT / "fixtures" / "freelancer-jobs.rss", "freelancer").fetch())
    assert len(leads) == 4
    assert leads[0].source_id == "jobs.example.com/1001"
    assert leads[0].contact_name == "Priya N."
    assert "\n" not in leads[0].body


def test_keywords_filter_per_profile():
    rss = RssFileSource(ROOT / "fixtures" / "freelancer-jobs.rss", "freelancer")
    inbox = JsonInboxSource(ROOT / "fixtures" / "blue-gable-inbox.json", "blue-gable-roofing")
    r = Researcher([rss, inbox], {"freelancer": ["python", "n8n", "api"]})
    titles = [lead.title for lead in r.collect()]
    assert "Logo and brand colors for a bakery" not in titles
    assert len(titles) == 5  # 3 jobs + 2 emails (no keywords for roofing)


def test_leads_without_id_or_body_are_dropped():
    r = Researcher([])
    assert not r.relevant(Lead("p", "", "t", "body"))
    assert not r.relevant(Lead("p", "id", "t", ""))


def test_settings_defaults_are_safe():
    s = Settings.from_env({})
    assert s.send_enabled is False
    assert s.approver_ids == frozenset()
    assert s.llm_provider == "fake"
    assert s.voice_enabled is False
    with pytest.raises(ConfigError):
        s.require_approvers()


def test_settings_parse_and_hide_secrets():
    s = Settings.from_env(
        {
            "APPROVER_USER_IDS": " 111, 222 ,",
            "SEND_ENABLED": "true",
            "LLM_PROVIDER": "openai",
            "LLM_API_KEY": "should-not-print",
            "DISCORD_BOT_TOKEN": "also-hidden",
            "DISCORD_CHANNEL_ID": "42",
            "LLM_BASE_URL": "http://localhost:11434/v1/",
        }
    )
    assert s.approver_ids == {"111", "222"}
    assert s.send_enabled
    assert s.discord_channel_id == 42
    assert s.llm_base_url == "http://localhost:11434/v1"
    assert "should-not-print" not in repr(s)
    assert "also-hidden" not in repr(s)
    assert isinstance(build_llm(s), OpenAICompatibleClient)
    assert isinstance(build_llm(Settings()), FakeLLM)


@pytest.mark.parametrize(
    "env",
    [
        {"SEND_ENABLED": "maybe"},
        {"LLM_PROVIDER": "magic"},
        {"SENDER": "carrier-pigeon"},
        {"VOICE_DEVICE": "tpu"},
        {"MAX_SENDS_PER_HOUR": "-1"},
        {"MAX_REDRAFTS": "two"},
    ],
)
def test_bad_settings_raise(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_unknown_source_type(tmp_path):
    (tmp_path / "x.toml").write_text(
        'name="x"\ntask="t"\nfacts=[]\n[source]\ntype="web"\npath="p"\n'
    )
    with pytest.raises(ValueError, match="unknown source type"):
        build_sources(Settings(fixtures_dir=tmp_path), load_profiles(tmp_path))


def test_no_profiles(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profiles(tmp_path)
