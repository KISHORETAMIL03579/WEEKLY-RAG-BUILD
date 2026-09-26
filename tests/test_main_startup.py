import sys
from types import SimpleNamespace

from backend import main
from backend.config import BACKEND_DIR


def test_debug_server_uses_configured_backend_reload_directory(monkeypatch):
    calls = []
    uvicorn = SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)

    main._run_server(debug=True, host="127.0.0.1", port=7201)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("backend.main:app",)
    assert kwargs["reload"] is True
    assert kwargs["reload_dirs"] == [str(BACKEND_DIR)]


def test_production_server_disables_reload(monkeypatch):
    calls = []
    uvicorn = SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)

    main._run_server(debug=False, host="127.0.0.1", port=7201)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (main.app,)
    assert kwargs["reload"] is False
