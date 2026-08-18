from pathlib import Path

import inspect.ansible_runner as ansible_runner


def test_project_json_callback_is_wired_without_inherited_plugins():
    source = Path(ansible_runner.__file__).read_text(encoding="utf-8")
    assert 'ANSIBLE_CALLBACK_PLUGINS' in source
    assert 'callback_plugins' in source
    assert 'ANSIBLE_STDOUT_CALLBACK' in source


def test_project_json_callback_has_runner_payload_shape():
    source = Path(ansible_runner.__file__).resolve().parent / "callback_plugins" / "json.py"
    text = source.read_text(encoding="utf-8")
    assert '"plays"' in text
    assert '"stats"' in text
    assert 'CALLBACK_NAME = "json"' in text
    assert '"stdout"' in text
    assert '"stderr"' in text
