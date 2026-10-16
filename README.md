# rpi2_speaker

Raspberry Pi 2용 네트워크 스피커. 웹 UI에서 YouTube / YouTube Music URL 또는 로컬(네트워크 마운트) 파일을 재생한다.

구성: `speaker.py`(Python 표준 라이브러리 HTTP 서버) → mpv JSON IPC → mpv(+yt-dlp). 외부 Python 패키지 없음.

## 설치 (Raspberry Pi OS)

```sh
sudo apt install -y mpv python3 ffmpeg
sudo pip3 install -U yt-dlp --break-system-packages   # YouTube 재생용
sudo mkdir -p /mnt/music                                # NAS 등 네트워크 공유를 여기에 마운트
# 예: sudo mount -t cifs //nas/music /mnt/music -o guest,ro
```

## 실행

```sh
MUSIC_DIR=/mnt/music PORT=8080 python3 speaker.py
```

브라우저에서 `http://<pi-ip>:8080` 접속.

## 자동 시작 (systemd)

```sh
sudo cp rpi2-speaker.service /etc/systemd/system/
sudo systemctl enable --now rpi2-speaker
```

## API

| Method | Path | Body |
|---|---|---|
| GET | `/api/status` | |
| GET | `/api/files` | |
| POST | `/api/play` | `{"url": "<URL 또는 MUSIC_DIR 상대경로>"}` |
| POST | `/api/pause` | (토글) |
| POST | `/api/stop` | |
| POST | `/api/volume` | `{"volume": 0-100}` |

## 테스트

```sh
python3 test_speaker.py
```
