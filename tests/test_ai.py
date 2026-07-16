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
