# rpi2_speaker

Raspberry Pi 2용 네트워크 스피커. 웹 UI에서 YouTube / YouTube Music URL 또는 로컬(네트워크 마운트) 파일을 재생한다.

구성: `speaker.py`(Python 표준 라이브러리 HTTP 서버) → mpv JSON IPC → mpv(+yt-dlp). 외부 Python 패키지 없음.

## 설치 (깨끗한 Raspberry Pi OS)

```sh
git clone https://github.com/bwikbs/rpi2_speaker
cd rpi2_speaker
./install.sh
```

mpv/ffmpeg/yt-dlp 설치, `/mnt/music` 생성, systemd 서비스 등록·시작까지 수행하며 재부팅 후 자동 실행된다.
환경변수 `MUSIC_DIR`, `PORT`로 경로·포트를 바꿀 수 있다 (예: `PORT=80 ./install.sh`).

NAS 등 네트워크 공유는 `/mnt/music`에 마운트한다. 예 (`/etc/fstab`):

```
//nas/music  /mnt/music  cifs  guest,ro,_netdev,x-systemd.automount  0  0
```

브라우저에서 `http://<pi-ip>:8080` 접속.

수동 실행: `MUSIC_DIR=/mnt/music PORT=8080 python3 speaker.py`
로그: `journalctl -u rpi2-speaker -f`

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
