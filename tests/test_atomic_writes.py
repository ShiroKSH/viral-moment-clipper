import pytest

from backend.core import config, utils


def test_write_json_replaces_complete_document(tmp_path):
    destination = tmp_path / "metadata.json"

    utils.write_json(destination, {"title": "Продолжение", "score": 91})

    assert utils.read_json(destination) == {"title": "Продолжение", "score": 91}
    assert list(tmp_path.iterdir()) == [destination]


def test_write_json_preserves_previous_document_when_replace_fails(monkeypatch, tmp_path):
    destination = tmp_path / "metadata.json"
    destination.write_text('{"state": "ready"}', encoding="utf-8")

    def fail_replace(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr(utils.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        utils.write_json(destination, {"state": "rendered"})

    assert utils.read_json(destination) == {"state": "ready"}
    assert list(tmp_path.iterdir()) == [destination]


def test_save_config_round_trips_from_atomic_file(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    config.load_config.cache_clear()
    raw = config.Settings().model_dump()
    raw["branding"]["badge_text"] = "@test_channel"

    try:
        saved = config.save_config(raw)
    finally:
        config.load_config.cache_clear()

    assert saved.branding.badge_text == "@test_channel"
    assert config_path.read_text(encoding="utf-8").count("@test_channel") == 1
    assert list(tmp_path.iterdir()) == [config_path]
