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

with tempfile.TemporaryDirectory() as d:
    speaker.STATE = Path(d) / "state.json"
    assert speaker.load_state() == {}
    speaker.save_state(volume=30)
    speaker.save_state(device="alsa/hdmi")
    assert speaker.load_state() == {"volume": 30, "device": "alsa/hdmi"}
print("ok state")

assert speaker.move_args(2, 0) == (2, 0)
assert speaker.move_args(0, 2) == (0, 3)
assert speaker.move_args(1, 1) == (1, 1)
print("ok move")
