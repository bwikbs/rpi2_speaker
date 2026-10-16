"""Self-check without mpv: file listing and path resolution."""
import tempfile
from pathlib import Path

import speaker

with tempfile.TemporaryDirectory() as d:
    speaker.MUSIC_DIR = Path(d)
    (Path(d) / "sub").mkdir()
    (Path(d) / "sub" / "a.mp3").touch()
    (Path(d) / "b.txt").touch()
    assert speaker.list_files() == ["sub/a.mp3"], speaker.list_files()
    assert speaker.resolve("sub/a.mp3") == str(Path(d).resolve() / "sub" / "a.mp3")
    assert speaker.resolve("https://music.youtube.com/watch?v=x").startswith("https://")
    try:
        speaker.resolve("../etc/passwd")
        assert False, "traversal allowed"
    except ValueError:
        pass
print("ok")
