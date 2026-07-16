import json

from routelens.ai import WeatherAI, WEATHER_SCHEMA


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeChat:
    def __init__(self, content):
        self._content = content
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self._content)


class FakeClient:
    def __init__(self, content):
        self.chat = FakeChat(content)


def test_from_env_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert WeatherAI.from_env() is None


def test_sdk_import_path_and_client_construction():
    """Contract test against the actually-installed mistralai SDK — the real
    boundary the mocked tests can't reach. Guards the import path and that a
    client constructs (no network)."""
    from routelens.ai import _import_mistral

    Mistral = _import_mistral()
    client = Mistral(api_key="sk-fake-not-real")
    assert hasattr(client, "chat") and hasattr(client.chat, "complete")


def test_weather_schema_matches_installed_sdk_contract():
    """The 2.x SDK expects `schema_definition`, not `schema`; a mismatch is
    silently ignored and disables structured output. Assert the corrected key
    and that the SDK accepts the whole response_format."""
    from mistralai.client.models.responseformat import ResponseFormat

    js = WEATHER_SCHEMA["json_schema"]
    assert "schema_definition" in js and "schema" not in js
    # Validates against the SDK's own model (raises on a wrong shape).
    ResponseFormat.model_validate(WEATHER_SCHEMA)


def test_summarize_calls_model_with_schema_and_parses_json():
    client = FakeClient(json.dumps({
        "headline": "Squall over Sudan", "severity": "minor",
        "body_md": "## Summary\nA regional outage...",
    }))
    ai = WeatherAI(client, model="mistral-small-latest")

    result = ai.summarize({"internal": {"collector_spikes": []}, "ioda": [], "grip": [], "radar_outages": []})

    assert result["headline"] == "Squall over Sudan"
    assert result["severity"] == "minor"
    call = client.chat.calls[0]
    assert call["model"] == "mistral-small-latest"
    assert call["response_format"] == WEATHER_SCHEMA
    # System prompt frames the task; evidence rides in the user message.
    assert call["messages"][0]["role"] == "system"
    assert "Sudan" not in call["messages"][0]["content"]  # system is static
    assert "ioda" in call["messages"][1]["content"]


def test_summarize_survives_model_wrapping_json_in_prose():
    # Belt-and-braces: if a model returns prose around the JSON, extract it.
    client = FakeClient('Here is your report:\n{"headline":"H","severity":"calm","body_md":"b"}\nHope that helps!')
    ai = WeatherAI(client)

    result = ai.summarize({"internal": {}})

    assert result["severity"] == "calm"


def test_explain_returns_plain_text():
    client = FakeClient("This prefix's origin AS changed from AS64500 to AS64666, "
                        "which could be a planned migration or a leak — check RPKI.")
    ai = WeatherAI(client)

    out = ai.explain("origin change: 203.0.113.0/24 AS64500 -> AS64666, 2 flips")

    assert "origin AS changed" in out
    call = client.chat.calls[0]
    assert call["model"] == "mistral-small-latest"
    # Explanations are short and don't force the weather JSON schema.
    assert "response_format" not in call
    assert call["messages"][1]["content"].startswith("origin change")
