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
환경변수 `MUSIC_DIR`, `PORT`로 경로·포트를 바꿀 수 있다 (기본 포트 80, 예: `PORT=8080 ./install.sh`).

NAS 등 네트워크 공유는 `/mnt/music`에 마운트한다. 예 (`/etc/fstab`):

```
//nas/music  /mnt/music  cifs  guest,ro,_netdev,x-systemd.automount  0  0
```

브라우저에서 `http://<pi-ip>` 접속.

수동 실행: `MUSIC_DIR=/mnt/music PORT=8080 python3 speaker.py`
로그: `journalctl -u rpi2-speaker -f`

## API

POST는 `Content-Type: application/json` 헤더가 있어야 하고, 브라우저가 보낸 `Origin`은 접속한 호스트와 같아야 한다 (다른 사이트에서의 CSRF 차단). 예: `curl -XPOST -H 'Content-Type: application/json' -d '{"volume":50}' http://<pi-ip>/api/volume`

| Method | Path | Body |
|---|---|---|
| GET | `/api/status` | 현재 곡, 볼륨, `queue` 포함 |
| GET | `/api/files` | |
| GET | `/api/playlists` | `{"profiles": [...], "playlists": {프로필: {이름: [url, ...]}}}` |
| POST | `/api/play` | `{"url": "<URL 또는 MUSIC_DIR 상대경로>"}` 현재 곡 다음에 넣고 바로 재생 (큐 유지) |
| POST | `/api/queue` | `{"url": ...}` 큐 끝에 추가 (정지 상태면 바로 재생) |
| POST | `/api/next` / `/api/prev` | |
| POST | `/api/jump` | `{"index": n}` 큐의 n번째 곡 재생 |
| POST | `/api/remove` | `{"index": n}` |
| POST | `/api/move` | `{"from": n, "to": m}` m은 이동 후 위치 |
| POST | `/api/clear` | |
| POST | `/api/playlist/save` | `{"profile": "지민", "name": ...}` 현재 큐를 저장 (같은 이름은 덮어씀) |
| POST | `/api/playlist/play` | `{"profile", "name", "append": false}` 큐를 교체해 재생, `append`면 큐 끝에 추가 |
| POST | `/api/playlist/delete` | `{"profile", "name"}` |
| POST | `/api/pause` | (토글) |
| POST | `/api/mute` | (토글) |
| POST | `/api/repeat` | `{"mode": "off" \| "all" \| "one"}` 반복 없음 / 전체 반복 / 1곡 반복 |
| POST | `/api/seek` | `{"time": 초}` |
| POST | `/api/stop` | |
| POST | `/api/volume` | `{"volume": 0-100}` |
| POST | `/api/update` | yt-dlp 최신판 설치 (수 분 소요) |
| POST | `/api/reboot` | |

재부팅·업데이트는 `install.sh`가 `/etc/sudoers.d/rpi2-speaker`에 등록한 두 명령에 한해 비밀번호 없이 sudo로 실행된다.

프로필은 지훈·아빠·지민·엄마 4개(`speaker.py`의 `PROFILES`)이며, 프로필별 플레이리스트는 `playlists.json`에 저장된다. 선택한 프로필은 각 폰 브라우저에 기억된다.

출력은 항상 3.5mm 헤드폰 잭이다 (환경변수 `AUDIO_DEVICE`로 변경 가능, 기본 `alsa/default:CARD=Headphones`). YouTube 믹스/재생목록 URL(`watch?v=..&list=..`)은 앞 50곡이 큐에 들어간다.

볼륨, 반복 모드, 큐와 현재 곡 위치는 `state.json`에, 곡 내 재생 위치는 `watch_later/`에 저장되어 재부팅 후에도 유지된다. 부팅 직후에는 일시정지 상태로 복원된다. 모니터·키보드 없이 동작한다.

## 테스트

```sh
python3 test_speaker.py
```
