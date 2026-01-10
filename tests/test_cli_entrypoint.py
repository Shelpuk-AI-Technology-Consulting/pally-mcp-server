import sys


def test_pally_mcp_server_cli_version_prints_version(capsys, monkeypatch):
    import cli
    from config import __version__

    monkeypatch.setattr(sys, "argv", ["pally-mcp-server", "--version"])
    cli.main()

    captured = capsys.readouterr()
    assert captured.out.strip() == str(__version__)


def test_pally_mcp_server_cli_start_subcommand_invokes_asyncio(monkeypatch):
    import cli

    called = {"value": False}

    def fake_asyncio_run(_coro):
        called["value"] = True
        _coro.close()

    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(sys, "argv", ["pally-mcp-server", "start-mcp-server"])
    cli.main()

    assert called["value"] is True


def test_pally_mcp_server_cli_no_args_invokes_asyncio(monkeypatch):
    import cli

    called = {"value": False}

    def fake_asyncio_run(_coro):
        called["value"] = True
        _coro.close()

    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(sys, "argv", ["pally-mcp-server"])
    cli.main()

    assert called["value"] is True
