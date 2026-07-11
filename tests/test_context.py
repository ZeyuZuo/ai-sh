from tmksh import context


def test_collect_context_uses_safe_detectors(monkeypatch) -> None:
    monkeypatch.setattr(context.Path, "cwd", lambda: context.Path("/tmp/project"))
    monkeypatch.setattr(context, "detect_shell", lambda: "bash")
    monkeypatch.setattr(
        context,
        "detect_os",
        lambda: {"system": "Linux", "release": "test", "machine": "x86_64"},
    )
    monkeypatch.setattr(context.getpass, "getuser", lambda: "tester")
    monkeypatch.setattr(context, "detect_tools", lambda: {"git": True})

    data = context.collect_context()

    assert data["cwd"] == "/tmp/project"
    assert data["shell"] == "bash"
    assert data["username"] == "tester"
    assert data["tools"] == {"git": True}


def test_detect_tools_reports_boolean(monkeypatch) -> None:
    monkeypatch.setattr(
        context.shutil, "which", lambda tool: "/bin/" + tool if tool == "git" else None
    )

    assert context.detect_tools(["git", "kubectl"]) == {"git": True, "kubectl": False}
