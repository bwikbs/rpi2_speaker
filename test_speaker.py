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
                 ("set_property", "pause", True), ("set_property", "resume-playback", True),
                 ("playlist-play-index", 1)], calls
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
    assert speaker.load_state() == {"volume": 5, "queue": ["a"], "pos": -1, "titles": {}}
    mtime = speaker.STATE.stat().st_mtime_ns
    speaker.save_queue()
    assert speaker.STATE.stat().st_mtime_ns == mtime
print("ok play_now/save_queue")


# titles survive a restart: learned from playlist entries, used when mpv no longer knows them
speaker.TITLES.clear()
props["playlist"] = [{"filename": "https://y/a", "title": "Song A"}, {"filename": "https://y/b"}]
with tempfile.TemporaryDirectory() as d:
    speaker.STATE = Path(d) / "state.json"
    speaker.save_queue()
    assert speaker.load_state()["titles"] == {"https://y/a": "Song A"}
assert speaker.title_of({"filename": "https://y/a"}) == "Song A"
assert speaker.title_of({"filename": "https://y/b"}) == "https://y/b"
speaker.TITLE_CAP = 1
speaker.remember_titles([{"filename": "https://y/c", "title": "C"}])
assert speaker.TITLES == {"https://y/c": "C"}
print("ok titles")

# repeat: modes map onto mpv loop-file / loop-playlist and are persisted
with tempfile.TemporaryDirectory() as d:
    speaker.STATE = Path(d) / "state.json"
    calls.clear(); speaker.set_repeat("one")
    assert calls == [("set_property", "loop-file", "inf"), ("set_property", "loop-playlist", "no")], calls
    calls.clear(); speaker.set_repeat("all")
    assert calls == [("set_property", "loop-file", "no"), ("set_property", "loop-playlist", "inf")], calls
    assert speaker.repeat_mode == "all" and speaker.load_state()["repeat"] == "all"
    try:
        speaker.set_repeat("bogus")
        assert False
    except KeyError:
        pass
    assert speaker.repeat_mode == "all"
print("ok repeat")

# sleep timer: arms, reports time left, cancels, pauses when it fires
speaker.set_timer(30)
assert 1795 <= speaker.timer_left() <= 1800, speaker.timer_left()
speaker.set_timer(15)  # re-arming replaces the old timer
assert speaker.timer_left() <= 900
speaker.set_timer(0)
assert speaker.timer_left() is None
try:
    speaker.set_timer(7)
    assert False
except ValueError:
    pass
calls.clear(); speaker.set_timer(15); speaker.timer_expired()
assert calls == [("set_property", "pause", True)] and speaker.timer_left() is None, calls
print("ok timer")

# stall watchdog: reopen audio only after time-pos stays frozen while playing
state = {"time-pos": 5.0, "pause": False, "paused-for-cache": False}
def fake(*a):
    calls.append(a)
    return state.get(a[1]) if a[0] == "get_property" else None
speaker.mpv_cmd = fake
speaker.STALL_TICKS = 2
calls.clear()
last, ticks = speaker.unstick_audio(None, 0)
assert (last, ticks) == (5.0, 0)
last, ticks = speaker.unstick_audio(last, ticks)
assert ticks == 1 and ("ao-reload",) not in calls
last, ticks = speaker.unstick_audio(last, ticks)
assert ticks == 0 and ("ao-reload",) in calls
calls.clear(); state["pause"] = True
assert speaker.unstick_audio(5.0, 1) == (5.0, 0) and ("ao-reload",) not in calls
state["pause"] = False; state["time-pos"] = None  # still loading
assert speaker.unstick_audio(None, 1) == (None, 0)
print("ok stall")

# morning call: alarms validated against saved playlists, kept sorted, ring replaces the queue unmuted
with tempfile.TemporaryDirectory() as d:
    speaker.ALARMS = Path(d) / "alarms.json"
    speaker.PLAYLISTS = Path(d) / "playlists.json"
    speaker.STATE = Path(d) / "state.json"
    speaker.edit_playlist("엄마", "아침", ["https://y/m"])
    assert speaker.load_alarms() == []
    speaker.edit_alarm({"time": "07:30", "profile": "엄마", "name": "아침", "volume": 140})
    al = speaker.edit_alarm({"time": "06:05", "profile": "엄마", "name": "아침"})
    assert [(a["id"], a["time"], a["volume"], a["on"]) for a in al] == [(2, "06:05", 50, True), (1, "07:30", 100, True)], al
    al = speaker.edit_alarm({**al[1], "on": False})
    assert len(al) == 2 and al[1]["on"] is False
    for bad in [{"time": "7:30"}, {"time": "24:00"}, {"name": "없음"}, {"profile": "이모"}]:
        try:
            speaker.edit_alarm({"time": "07:00", "profile": "엄마", "name": "아침", **bad})
            assert False, bad
        except ValueError:
            pass
    assert [a["id"] for a in speaker.edit_alarm({"id": 2}, delete=True)] == [1]
    calls.clear(); speaker.ring(al[1])
    assert calls == [("set_property", "mute", False), ("set_property", "volume", 100),
                     ("loadfile", "https://y/m", "replace"), ("set_property", "pause", False)], calls
    assert speaker.load_state()["volume"] == 100
print("ok alarms")
