from pathlib import Path
import subprocess

from backend.context.lexicon import iter_trigger_phrases

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEXICON = "backend/context/lexicon.py"


def _tracked_files() -> list[str]:
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
        if path != _LEXICON:
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return None


def test_f_lexicon_phrases_are_not_literals_in_other_tracked_files():
    phrases = iter_trigger_phrases()
    assert phrases, "lexicon must define trigger phrases"
    leaked_paths: list[str] = []
    for rel in _tracked_files():
        text = _read_text(_REPO_ROOT / rel)
        if text is None:
            continue
        for phrase in phrases:
            if phrase in text:
                leaked_paths.append(rel)
                break
    assert leaked_paths == [], (
        f"lexicon phrase literals found outside {_LEXICON} in {len(leaked_paths)} file(s): "
        + ", ".join(leaked_paths)
    )
