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

# post_allowed: JSON content type required, cross-site Origin rejected
J = {"Content-Type": "application/json", "Host": "pi:8080"}
assert speaker.post_allowed(J)
assert speaker.post_allowed({**J, "Origin": "http://pi:8080"})
assert not speaker.post_allowed({**J, "Origin": "https://evil.example"})
assert not speaker.post_allowed({"Content-Type": "text/plain", "Host": "pi:8080"})
assert not speaker.post_allowed({"Host": "pi:8080"})
print("ok csrf")

# play_now inserts after current track instead of wiping the queue; save_queue skips no-op writes
props = {"playlist-pos": 1, "playlist-count": 3, "playlist": [{"filename": "a"}]}
def fake(*a):
    calls.append(a)
    return props.get(a[1]) if a[0] == "get_property" else None
speaker.mpv_cmd = fake
calls.clear(); speaker.play_now("u")
assert calls[1:] == [("loadfile", "u", "insert-at", 2), ("playlist-play-index", 2),
                     ("set_property", "pause", False)], calls
props["playlist-pos"] = -1
calls.clear(); speaker.play_now("u")
assert calls[2:4] == [("loadfile", "u", "insert-at", 3), ("playlist-play-index", 3)], calls
with tempfile.TemporaryDirectory() as d:
    speaker.STATE = Path(d) / "state.json"
    speaker.save_state(volume=5)
    speaker.save_queue()
    assert speaker.load_state() == {"volume": 5, "queue": ["a"], "pos": -1}
    mtime = speaker.STATE.stat().st_mtime_ns
    speaker.save_queue()
    assert speaker.STATE.stat().st_mtime_ns == mtime
print("ok play_now/save_queue")

# outputs: only real ALSA cards, 3.5mm first; fix_device replaces unusable saved devices
DEVS = [{"name": "auto", "description": "Autoselect device"},
        {"name": "alsa/default:CARD=vc4hdmi", "description": "vc4-hdmi, MAI PCM i2s-hifi-0/Default Audio Device"},
        {"name": "alsa/hdmi:CARD=vc4hdmi,DEV=0", "description": "vc4-hdmi, MAI PCM i2s-hifi-0/HDMI Audio Output"},
        {"name": "alsa/default:CARD=Headphones", "description": "bcm2835 Headphones, bcm2835 Headphones/Default Audio Device"},
        {"name": "alsa/default:CARD=Device", "description": "USB Audio Device, USB Audio/Default Audio Device"},
        {"name": "jack", "description": "Default (jack)"}]
assert speaker.outputs(DEVS) == [
    {"name": "alsa/default:CARD=Headphones", "description": "3.5mm 헤드폰 잭"},
    {"name": "alsa/default:CARD=vc4hdmi", "description": "HDMI (vc4hdmi)"},
    {"name": "alsa/default:CARD=Device", "description": "USB Audio Device"}], speaker.outputs(DEVS)
props["audio-device-list"] = DEVS
with tempfile.TemporaryDirectory() as d:
    speaker.STATE = Path(d) / "state.json"
    calls.clear(); speaker.fix_device({"device": "jack"})
    assert calls[-1] == ("set_property", "audio-device", "alsa/default:CARD=Headphones"), calls
    assert speaker.load_state()["device"] == "alsa/default:CARD=Headphones"
    calls.clear(); speaker.fix_device({"device": "alsa/default:CARD=Device"})
    assert len(calls) == 1, calls  # only the list query, no change
print("ok outputs")
