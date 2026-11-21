"""The commit-msg hook in .githooks rejects AI attribution lines (D-109).

Each case makes a real commit in a throwaway repo that uses the hook.
"""

import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / ".githooks"


@pytest.fixture
def repo(tmp_path):
    def git(*args, check=True):
        return subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=check,
        )

    git("init", "-q")
    git("config", "core.hooksPath", HOOKS.as_posix())
    return git


def commit(git, message):
    return git("commit", "-q", "--allow-empty", "-m", message, check=False)


@pytest.mark.parametrize(
    "line",
    [
        "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
        "co-authored-by: Claude <noreply@anthropic.com>",
        "Co-Authored-By: Someone <bot@anthropic.com>",
        "Claude-Session: https://claude.ai/code/session_x",
        "\U0001f916 Generated with [Claude Code](https://claude.com/claude-code)",
        "Generated with Claude Code",
    ],
)
def test_rejects_attribution(repo, line):
    result = commit(repo, f"feat: a change\n\nBody.\n\n{line}\n")
    assert result.returncode != 0
    assert "D-109" in result.stderr
    assert repo("rev-list", "--all", "--count", check=False).stdout.strip() in ("", "0")


@pytest.mark.parametrize(
    "message",
    [
        "feat: a change\n\nBody.\n",
        "docs: CLAUDE.md points to the hook\n",
        "fix: x\n\nCo-Authored-By: A Person <person@example.com>\n",
    ],
)
def test_accepts_normal_messages(repo, message):
    assert commit(repo, message).returncode == 0
