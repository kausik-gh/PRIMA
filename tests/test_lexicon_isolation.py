from pathlib import Path
import subprocess

from backend.context.lexicon import iter_trigger_phrases

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEXICON = "backend/context/lexicon.py"
_SKIP_PREFIXES = (
    "Documentations/",
    "docs/",
    "frontend/",
    "backend/legacy/",
    "legacy/",
)


def _tracked_and_untracked() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
    )
    files: list[str] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8").replace("\\", "/")
        if path == _LEXICON:
            continue
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue
        files.append(path)
    return files


def test_lexicon_phrases_not_outside_lexicon():
    phrases = iter_trigger_phrases()
    assert phrases
    leaked: list[str] = []
    for rel in _tracked_and_untracked():
        path = _REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError, OSError):
            continue
        for phrase in phrases:
            if phrase in text:
                leaked.append(rel)
                break
    assert leaked == [], f"phrase literals outside lexicon in {len(leaked)} file(s): " + ", ".join(leaked)
