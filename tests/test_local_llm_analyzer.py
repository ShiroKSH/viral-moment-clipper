from backend.core.config import Settings
from backend.schemas.moments import SentenceSegment
from backend.services import local_llm_analyzer


class _Response:
    def __init__(self, payload: list[dict]):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        import json

        return {"response": json.dumps(self.payload)}


class _Client:
    prompts: list[str] = []
    payloads: list[dict] = []

    def __init__(self, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def post(self, _url: str, *, json: dict):
        self.prompts.append(json["prompt"])
        self.payloads.append(json)
        if "180.00-190.00" in json["prompt"]:
            return _Response(
                [
                    {
                        "start": 180,
                        "end": 190,
                        "summary": "late insight",
                        "moment_type": "insight",
                        "hook_text": "late hook",
                        "reason": "specific late-window reason",
                    }
                ]
            )
        return _Response([])


def test_local_llm_analyzes_late_transcript_windows(monkeypatch):
    _Client.prompts = []
    _Client.payloads = []
    monkeypatch.setattr(local_llm_analyzer.httpx, "Client", _Client)
    settings = Settings()
    settings.local_llm.enabled = True
    settings.local_llm.max_window_sec = 60
    settings.local_llm.overlap_sec = 10
    sentences = [
        SentenceSegment(id=f"s{index}", start=index * 10, end=index * 10 + 10, text=f"sentence {index}")
        for index in range(25)
    ]

    moments = local_llm_analyzer.analyze_with_local_llm(sentences, settings)

    assert len(_Client.prompts) > 1
    assert moments[0].start == 180
    assert moments[0].text == "sentence 17 sentence 18 sentence 19"
    assert all(payload["options"] == {"temperature": 0.15, "seed": 7} for payload in _Client.payloads)
