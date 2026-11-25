import json
import os

import pytest

from clipsai.config import (
    AISettings,
    DEFAULT_INDIEPOST_BASE_URL,
    IndiePostSettings,
    load_env,
    service_status,
)


@pytest.fixture
def restore_env():
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)


def test_missing_env_file_is_not_an_error(tmp_path):
    assert load_env(tmp_path / "does-not-exist") == {}


def test_load_env_handles_quotes_comments_and_export(tmp_path, restore_env):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\n"
        "\n"
        'CLIPSAI_TEST_A="hello world"\n'
        "export CLIPSAI_TEST_B='single value'\n"
        "CLIPSAI_TEST_C=plain # inline comment\n"
        "CLIPSAI_TEST_D=\n"
        "not a pair\n"
        "=missing key\n",
        encoding="utf-8",
    )
    for name in ("A", "B", "C", "D"):
        os.environ.pop("CLIPSAI_TEST_" + name, None)

    loaded = load_env(path)

    assert os.environ["CLIPSAI_TEST_A"] == "hello world"
    assert os.environ["CLIPSAI_TEST_B"] == "single value"
    assert os.environ["CLIPSAI_TEST_C"] == "plain"
    assert os.environ["CLIPSAI_TEST_D"] == ""
    assert "CLIPSAI_TEST_A" in loaded
    assert "CLIPSAI_TEST_D" in loaded


def test_load_env_does_not_override_real_environment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("CLIPSAI_TEST_OVERRIDE=from-file\n", encoding="utf-8")
    monkeypatch.setenv("CLIPSAI_TEST_OVERRIDE", "from-process")

    load_env(path)

    assert os.environ["CLIPSAI_TEST_OVERRIDE"] == "from-process"


def test_load_env_can_override_when_asked(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("CLIPSAI_TEST_FORCE=from-file\n", encoding="utf-8")
    monkeypatch.setenv("CLIPSAI_TEST_FORCE", "from-process")

    load_env(path, override=True)

    assert os.environ["CLIPSAI_TEST_FORCE"] == "from-file"


def test_ai_settings_describe_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-very-secret-value")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    settings = AISettings.from_env()

    described = settings.describe()

    assert described["configured"] is True
    assert described["api_key"] == "set"
    assert described["model"] == "deepseek-reasoner"
    assert "sk-very-secret-value" not in json.dumps(described)


def test_indiepost_defaults(monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    monkeypatch.delenv("INDIEPOST_BASE_URL", raising=False)
    settings = IndiePostSettings.from_env()
    assert settings.is_configured() is False
    assert settings.base_url == DEFAULT_INDIEPOST_BASE_URL


def test_service_status_reports_all_services(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("HF_TOKEN", "hf-test")
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)

    status = service_status()

    assert set(status) == {"deepseek", "huggingface", "indiepost"}
    assert status["deepseek"]["configured"] is True
    assert status["huggingface"]["configured"] is True
    assert status["indiepost"]["configured"] is False
    assert "sk-test" not in json.dumps(status)
