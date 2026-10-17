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
    assert not speaker.STATE.with_suffix(".tmp").exists()
print("ok state")

assert speaker.move_args(2, 0) == (2, 0)
assert speaker.move_args(0, 2) == (0, 3)
assert speaker.move_args(1, 1) == (1, 1)
print("ok move")

# read_reply: skip broadcast events, fail instead of spinning when mpv hangs up
import socket
a, b = socket.socketpair()
b.sendall(b'{"event":"start-file"}\n{"request_id":1,"error":"success","data":5}\n')
assert speaker.read_reply(a, 1)["data"] == 5
b.sendall(b'{"event":"idle"}\n'); b.close()
try:
    speaker.read_reply(a, 1)
    assert False, "EOF not detected"
except ConnectionError:
    pass
a.close()
print("ok ipc")

# restore_queue: replay saved entries into a fake mpv_cmd
calls = []
speaker.mpv_cmd = lambda *a: calls.append(a)
speaker.restore_queue({"queue": ["/m/a.mp3", "https://y/x"], "pos": 1})
assert calls == [("loadfile", "/m/a.mp3", "append"), ("loadfile", "https://y/x", "append"),
                 ("set_property", "pause", True), ("playlist-play-index", 1)], calls
calls.clear(); speaker.restore_queue({}); assert calls == []
print("ok restore")

# playlists: per-profile save/delete, persisted, replayed into mpv
with tempfile.TemporaryDirectory() as d:
    speaker.PLAYLISTS = Path(d) / "playlists.json"
    assert speaker.load_playlists() == {p: {} for p in speaker.PROFILES}
    speaker.edit_playlist("지민", " 아이유 ", ["https://y/a", "/m/b.mp3"])
    speaker.edit_playlist("아빠", "jazz", ["https://y/c"])
    pls = speaker.load_playlists()
    assert pls["지민"] == {"아이유": ["https://y/a", "/m/b.mp3"]} and pls["엄마"] == {}, pls
    for bad in [("이모", "x"), ("지민", " "), ("지민", "x" * 51)]:
        try:
            speaker.edit_playlist(*bad, ["u"])
            assert False, bad
        except ValueError:
            pass
    calls.clear(); speaker.play_playlist("지민", "아이유", append=False)
    assert calls == [("loadfile", "https://y/a", "replace"), ("loadfile", "/m/b.mp3", "append-play"),
                     ("set_property", "pause", False)], calls
    calls.clear(); speaker.play_playlist("아빠", "jazz", append=True)
    assert calls == [("loadfile", "https://y/c", "append-play")], calls
    speaker.edit_playlist("지민", "아이유", None)
    assert speaker.load_playlists()["지민"] == {}
    try:
        speaker.play_playlist("지민", "아이유", append=False)
        assert False
    except ValueError:
        pass
print("ok playlists")
