#!/usr/bin/env python3
"""Network speaker for Raspberry Pi 2: mpv backend + tiny web UI. No deps beyond mpv/yt-dlp."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", "/mnt/music"))
PORT = int(os.environ.get("PORT", "8080"))
SOCK = os.environ.get("MPV_SOCK", "/tmp/rpi2_speaker.sock")
# Always the 3.5mm jack. "auto" lands on HDMI, which fails (error 524) with no monitor attached.
AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "alsa/default:CARD=Headphones")
MIX_LIMIT = 50  # YouTube mixes (list=RD...) run to hundreds of entries; queue only the first ones
UPDATE_CMD = ["pip3", "install", "-U", "yt-dlp", "--break-system-packages"]
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus", ".aac"}
HTML = (Path(__file__).parent / "index.html").read_bytes()
STATE = Path(__file__).parent / "state.json"  # volume + queue, survives reboot
WATCH_DIR = Path(__file__).parent / "watch_later"  # per-file resume position (mpv native)
PLAYLISTS = Path(__file__).parent / "playlists.json"  # {profile: {name: [url, ...]}}
PROFILES = ["지훈", "아빠", "지민", "엄마"]
TITLES = {}  # url -> title; mpv forgets titles of queue entries reloaded after a restart
TITLE_CAP = 1000
REPEAT = {"off": ("no", "no"), "all": ("no", "inf"), "one": ("inf", "no")}  # mode -> (loop-file, loop-playlist)
repeat_mode = "off"
FILE_LOCK = threading.Lock()  # HTTP handlers run in threads; serialize read-modify-write of state files


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_json(path, obj):
    """Atomic replace: a Pi losing power mid-write must not leave a truncated file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def load_state():
    return read_json(STATE)


def save_state(**kv):
    with FILE_LOCK:
        write_json(STATE, {**load_state(), **kv})


def load_playlists():
    saved = read_json(PLAYLISTS)
    return {p: saved.get(p, {}) for p in PROFILES}


def edit_playlist(profile, name, urls):
    """Store urls as profile's playlist `name`; urls=None deletes it."""
    if profile not in PROFILES:
        raise ValueError("unknown profile")
    name = name.strip()
    if not name or len(name) > 50:
        raise ValueError("playlist name must be 1-50 chars")
    with FILE_LOCK:
        pls = load_playlists()
        if urls is None:
            pls[profile].pop(name, None)
        else:
            pls[profile][name] = urls
        write_json(PLAYLISTS, pls)
    return pls


def play_playlist(profile, name, append):
    urls = load_playlists().get(profile, {}).get(name)
    if not urls:
        raise ValueError("no such playlist")
    for i, u in enumerate(urls):
        mpv_cmd("loadfile", u, "append-play" if append or i else "replace")
    if not append:
        mpv_cmd("set_property", "pause", False)


def read_reply(s, req_id):
    """mpv broadcasts events to every client, so skip lines until our request_id comes back."""
    buf = b""
    while True:
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            msg = json.loads(line)
            if msg.get("request_id") == req_id:
                return msg
        chunk = s.recv(4096)
        if not chunk:
            raise ConnectionError("mpv closed IPC socket")
        buf += chunk


def mpv_cmd(*args):
    """Send one command over mpv JSON IPC and return its 'data' field."""
    req_id = 1  # one connection per command, so any fixed id is unique
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        s.connect(SOCK)
        s.sendall(json.dumps({"command": list(args), "request_id": req_id}).encode() + b"\n")
        reply = read_reply(s, req_id)
    if reply.get("error") != "success":
        raise RuntimeError(reply.get("error"))
    return reply.get("data")


def prop(name, default=None):
    try:
        return mpv_cmd("get_property", name)
    except (RuntimeError, OSError):
        return default


def list_files():
    if not MUSIC_DIR.is_dir():
        return []
    return sorted(
        str(p.relative_to(MUSIC_DIR))
        for p in MUSIC_DIR.rglob("*")
        if p.suffix.lower() in AUDIO_EXT and p.is_file()
    )


def resolve(url):
    """Local relative paths map into MUSIC_DIR; anything else goes to mpv as-is (yt-dlp handles YouTube)."""
    if "://" in url:
        return url
    p = (MUSIC_DIR / url).resolve()
    if MUSIC_DIR.resolve() not in p.parents:
        raise ValueError("path outside MUSIC_DIR")
    return str(p)


def move_args(src, dst):
    """mpv playlist-move's 2nd arg is the entry to insert before, so moving down needs dst+1."""
    return (src, dst + 1 if dst > src else dst)


def remember_titles(playlist):
    """Collect known titles into TITLES; return True if anything new was learned."""
    found = {e["filename"]: e["title"] for e in playlist if e.get("title")}
    cur = next((e for e in playlist if e.get("current")), None)
    if cur and not cur.get("title") and prop("duration"):  # loaded, so media-title is the real one
        found[cur["filename"]] = prop("media-title")
    new = {k: v for k, v in found.items() if v and TITLES.get(k) != v}
    TITLES.update(new)
    while len(TITLES) > TITLE_CAP:
        TITLES.pop(next(iter(TITLES)))
    return bool(new)


def title_of(entry):
    f = entry["filename"]
    return entry.get("title") or TITLES.get(f) or f.replace(str(MUSIC_DIR) + "/", "")


def save_queue():
    """Uses mpv_cmd, not prop: if mpv is down, raise rather than overwrite the saved queue with []."""
    pl = mpv_cmd("get_property", "playlist")
    q = {"queue": [e["filename"] for e in pl], "pos": mpv_cmd("get_property", "playlist-pos")}
    st = load_state()
    if remember_titles(pl) or {k: st.get(k) for k in q} != q:  # skip no-op writes, checkpoint calls this every 10s
        save_state(**q, titles=TITLES)


def play_now(url):
    """Insert right after the current track and jump to it, keeping the rest of the queue."""
    pos = mpv_cmd("get_property", "playlist-pos")
    idx = pos + 1 if pos >= 0 else mpv_cmd("get_property", "playlist-count")
    mpv_cmd("loadfile", url, "insert-at", idx)
    mpv_cmd("playlist-play-index", idx)
    mpv_cmd("set_property", "pause", False)


def post_allowed(headers):
    """Block cross-site POSTs: a JSON content type forces a CORS preflight we never answer,
    and a browser-sent Origin must match the host it is talking to."""
    if not (headers.get("Content-Type") or "").startswith("application/json"):
        return False
    origin = headers.get("Origin")
    return origin is None or origin.split("://", 1)[-1] == headers.get("Host")


def restore_queue(st):
    """Reload the saved playlist paused so a reboot doesn't start blasting audio."""
    for f in st.get("queue", []):
        mpv_cmd("loadfile", f, "append")
    if st.get("pos", -1) >= 0 and st.get("queue"):
        mpv_cmd("set_property", "pause", True)
        mpv_cmd("playlist-play-index", st["pos"])


def checkpoint():
    while True:
        time.sleep(10)
        try:
            mpv_cmd("write-watch-later-config")
            save_queue()  # tracks advance on their own; keep pos current for the next boot
        except (RuntimeError, OSError):
            pass


def watchdog(proc):
    """If mpv dies, exit so systemd (Restart=always) brings both back with saved state."""
    proc.wait()
    print(f"mpv exited ({proc.returncode}), restarting service", flush=True)
    os._exit(1)


def set_repeat(mode):
    global repeat_mode
    loop_file, loop_playlist = REPEAT[mode]  # KeyError -> 400 for unknown modes
    mpv_cmd("set_property", "loop-file", loop_file)
    mpv_cmd("set_property", "loop-playlist", loop_playlist)
    repeat_mode = mode
    save_state(repeat=mode)


def status():
    pl = prop("playlist", [])
    cur = next((e for e in pl if e.get("current")), None)
    duration = prop("duration", 0)
    return {
        # while a URL is still loading mpv's media-title is just "watch?v=..."; prefer a remembered title
        "title": prop("media-title", "") if duration or not cur else title_of(cur),
        "path": prop("path", ""),
        "paused": prop("pause", True),
        "idle": prop("idle-active", True),
        "volume": prop("volume", 0),
        "mute": prop("mute", False),
        "repeat": repeat_mode,
        "queue": [{"title": title_of(e), "current": e.get("current", False)} for e in pl],
        "time": prop("time-pos", 0),
        "duration": duration,
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(HTML)))
            self.end_headers()
            self.wfile.write(HTML)
        elif self.path == "/api/status":
            self._json(status())
        elif self.path == "/api/files":
            self._json(list_files())
        elif self.path == "/api/playlists":
            self._json({"profiles": PROFILES, "playlists": load_playlists()})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not post_allowed(self.headers):
            return self._json({"error": "forbidden"}, 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/playlist/save":
                urls = [e["filename"] for e in prop("playlist", [])]
                if not urls:
                    raise ValueError("queue is empty")
                return self._json(edit_playlist(body["profile"], body["name"], urls))
            elif self.path == "/api/playlist/delete":
                return self._json(edit_playlist(body["profile"], body["name"], None))
            elif self.path == "/api/playlist/play":
                play_playlist(body["profile"], body["name"], bool(body.get("append")))
            elif self.path == "/api/play":
                play_now(resolve(body["url"]))
            elif self.path == "/api/queue":
                mpv_cmd("loadfile", resolve(body["url"]), "append-play")
            elif self.path == "/api/next":
                mpv_cmd("playlist-next", "force")
            elif self.path == "/api/prev":
                mpv_cmd("playlist-prev", "force")
            elif self.path == "/api/jump":
                mpv_cmd("playlist-play-index", int(body["index"]))
                mpv_cmd("set_property", "pause", False)
            elif self.path == "/api/remove":
                mpv_cmd("playlist-remove", int(body["index"]))
            elif self.path == "/api/move":
                mpv_cmd("playlist-move", *move_args(int(body["from"]), int(body["to"])))
            elif self.path == "/api/clear":
                mpv_cmd("playlist-clear")
            elif self.path == "/api/pause":
                mpv_cmd("cycle", "pause")
            elif self.path == "/api/seek":
                mpv_cmd("seek", float(body["time"]), "absolute")
            elif self.path == "/api/repeat":
                set_repeat(body["mode"])
            elif self.path == "/api/mute":
                mpv_cmd("cycle", "mute")
            elif self.path == "/api/stop":
                mpv_cmd("stop")
            elif self.path == "/api/volume":
                vol = max(0, min(100, int(body["volume"])))
                mpv_cmd("set_property", "volume", vol)
                save_state(volume=vol)
            elif self.path == "/api/update":  # sudoers rule from install.sh; takes minutes on a Pi 2
                r = subprocess.run(["sudo", "-n"] + UPDATE_CMD, capture_output=True, text=True, timeout=900)
                ver = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True).stdout.strip()
                return self._json({"ok": r.returncode == 0, "version": ver, "log": (r.stdout + r.stderr)[-2000:]})
            elif self.path == "/api/reboot":
                self._json({"ok": True})
                subprocess.run(["sudo", "-n", "systemctl", "reboot"])
                return
            else:
                return self._json({"error": "not found"}, 404)
            save_queue()
            self._json(status())
        except (KeyError, TypeError, ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            self._json({"error": str(e)}, 400)

    def log_message(self, *a):
        pass


def start_mpv():
    if os.path.exists(SOCK):
        os.unlink(SOCK)
    st = load_state()
    proc = subprocess.Popen(
        ["mpv", "--idle", "--no-video", "--no-terminal", "--ytdl-format=bestaudio/best",
         f"--input-ipc-server={SOCK}",
         # resume position per file; written on quit and every 10s (see checkpoint)
         "--save-position-on-quit", "--watch-later-options=start", f"--watch-later-dir={WATCH_DIR}",
         # mpv's ytdl_hook passes --no-playlist unless yes-playlist is set, so watch?v=..&list=.. queued one track
         "--ytdl-raw-options-append=yes-playlist=", f"--ytdl-raw-options-append=playlist-end={MIX_LIMIT}",
         f"--audio-device={AUDIO_DEVICE}", f"--volume={st.get('volume', 70)}"]
    )
    for _ in range(50):
        if os.path.exists(SOCK):
            return proc
        time.sleep(0.1)
    sys.exit("mpv did not create IPC socket")


if __name__ == "__main__":
    mpv = start_mpv()
    try:
        TITLES.update(load_state().get("titles", {}))
        set_repeat(load_state().get("repeat", "off"))
        restore_queue(load_state())
        threading.Thread(target=checkpoint, daemon=True).start()
        threading.Thread(target=watchdog, args=(mpv,), daemon=True).start()
        print(f"listening on :{PORT}, music dir {MUSIC_DIR}")
        ThreadingHTTPServer(("", PORT), Handler).serve_forever()
    finally:
        mpv.terminate()
