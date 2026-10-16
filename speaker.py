#!/usr/bin/env python3
"""Network speaker for Raspberry Pi 2: mpv backend + tiny web UI. No deps beyond mpv/yt-dlp."""
import json
import os
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", "/mnt/music"))
PORT = int(os.environ.get("PORT", "8080"))
SOCK = os.environ.get("MPV_SOCK", "/tmp/rpi2_speaker.sock")
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus", ".aac"}
HTML = (Path(__file__).parent / "index.html").read_bytes()
STATE = Path(__file__).parent / "state.json"  # audio device + volume, survives reboot


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(**kv):
    STATE.write_text(json.dumps({**load_state(), **kv}))


def mpv_cmd(*args):
    """Send one command over mpv JSON IPC and return its 'data' field."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        s.connect(SOCK)
        s.sendall(json.dumps({"command": list(args)}).encode() + b"\n")
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(4096)
    reply = json.loads(buf.split(b"\n")[0])
    if reply.get("error") != "success":
        raise RuntimeError(reply.get("error"))
    return reply.get("data")


def prop(name, default=None):
    try:
        return mpv_cmd("get_property", name)
    except RuntimeError:
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


def status():
    return {
        "title": prop("media-title", ""),
        "path": prop("path", ""),
        "paused": prop("pause", True),
        "idle": prop("idle-active", True),
        "volume": prop("volume", 0),
        "device": prop("audio-device", "auto"),
        "devices": prop("audio-device-list", []),
        "time": prop("time-pos", 0),
        "duration": prop("duration", 0),
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
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if self.path == "/api/play":
                mpv_cmd("loadfile", resolve(body["url"]))
                mpv_cmd("set_property", "pause", False)
            elif self.path == "/api/pause":
                mpv_cmd("cycle", "pause")
            elif self.path == "/api/stop":
                mpv_cmd("stop")
            elif self.path == "/api/volume":
                vol = max(0, min(100, int(body["volume"])))
                mpv_cmd("set_property", "volume", vol)
                save_state(volume=vol)
            elif self.path == "/api/device":
                mpv_cmd("set_property", "audio-device", body["device"])
                save_state(device=body["device"])
            else:
                return self._json({"error": "not found"}, 404)
            self._json(status())
        except (KeyError, ValueError, RuntimeError, OSError) as e:
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
         f"--audio-device={st.get('device', 'auto')}", f"--volume={st.get('volume', 70)}"]
    )
    for _ in range(50):
        if os.path.exists(SOCK):
            return proc
        time.sleep(0.1)
    sys.exit("mpv did not create IPC socket")


if __name__ == "__main__":
    mpv = start_mpv()
    try:
        print(f"listening on :{PORT}, music dir {MUSIC_DIR}")
        ThreadingHTTPServer(("", PORT), Handler).serve_forever()
    finally:
        mpv.terminate()
