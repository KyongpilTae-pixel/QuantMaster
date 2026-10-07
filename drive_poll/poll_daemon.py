"""
QuantMaster Drive Poll Daemon — v3.0
_comms/ 폴더를 주기적으로 폴링하여 cloud 메시지를 감지하고
Claude Code CLI로 처리 프롬프트를 전달한다.
프로토콜 v1.4 + v3.0 규격(local_polling_routine_v3):
- 매 주기 무조건 Claude 깨우기 (신규 파일 없어도)
- Claude 세션이 직접 Drive 스캔 + processed_ids.json 체크
- STATE 쓰기는 마지막 단계에만 (하트비트만 쓰고 끝내기 금지)
- processed_ids.json: C:\\project\\quant\\processed_ids.json (cloud-NNN 형식)
- 실패 시 조용한 IDLE 금지 → STATUS 게시

인증: Google Service Account (JSON 키)
실행: python poll_daemon.py [--once] [--interval 1800]
"""
import argparse
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- 설정 ---
COMMS_FOLDER_ID    = "1MvjWh0HYM0QlDHKh_uyqKrCtkUHBWlSp"  # Shared Drive _comms/ (유일한 라이브 채널)
SERVICE_ACCOUNT_FILE = Path(__file__).parent / "service_account.json"
STATE_FILE         = Path(__file__).parent / "poll_state.json"
LOG_FILE           = Path(__file__).parent / "poll_daemon.log"
CLAUDE_CMD         = r"C:\Users\Administrator\.local\bin\claude.exe"

# v1.4 헬스체크 파라미터
POLL_INTERVAL_MIN  = 30          # 로컬 폴링 간격(분)
LIVENESS_GRACE_MIN = 60          # 상대 무응답 임계: poll_interval × 2
DELIVERY_GRACE_CYCLES = 2        # 전달갭 유예 주기

PROCESS_PROMPT_V3 = """[로컬 폴링 v3 — 매 주기 실행 강제]
너는 cloud와 공유 드라이브 _comms 폴더로 협업하는 local 세션이다.
이번 깨우기에서 반드시 아래 순서를 "끝까지" 실행한다. 하트비트만 쓰고 끝내지 마라.

1) 스캔: search_files(parentId='1MvjWh0HYM0QlDHKh_uyqKrCtkUHBWlSp',
   query="title contains 'cloud-to-local'") 로 전체 나열.
2) 신규 선별: 로컬 파일 C:\\project\\quant\\processed_ids.json 를 읽어,
   거기에 없는 메시지 id를 신규로 본다(ID 기준, 시간 커서 금지). 오래된 것부터 정렬.
3) 각 신규 메시지 실행:
   - kind=REQUEST 또는 "EXECUTE/실행" NOTE  → 접수 ACK 1줄 게시 →
     실제 작업 수행(백테스트 등) → 결과를 REPLY 파일로 게시
     (파일명 MSG_<UTCstamp>_local-to-cloud_REPLY_<id>.md, disableConversionToGoogleType=true) →
     processed_ids.json 에 그 id 추가.
   - kind=ACK/REPLY/STATE(cloud) → 실행 불필요, id만 processed_ids 에 추가.
   - 실행 불가(데이터/에러) → STATUS 파일로 사유 게시(조용한 IDLE 금지) 후 id 기록.
4) 자기검증: 나열된 cloud-to-local 중 processed_ids 에 없는 게 하나라도 남아 있으면
   3)으로 돌아가 처리한다. 남은 게 0이 될 때까지 반복.
5) 마지막에 STATE_local.md 를 "덮어쓰기"로 1개만 갱신:
   last_seen_peer_id = 방금 처리한 "가장 최근 실제 메시지 id"(예: cloud-043),
   open_waits = 아직 REPLY 못 낸 id 목록(없으면 []),
   activity = (open_waits 비면 IDLE, 아니면 "RUNNING <id>"),
   ts = 현재 UTC, poll_interval=30min, next_poll_eta=+30min.
금지: (a) 1~4를 건너뛰고 STATE만 쓰기 (b) last_seen 에 cloud-015 같은 옛 id나
   'REQUEST'/'REPLY' 같은 kind 단어 넣기 (c) STATE_local.md 사본을 새로 만들기(1개만 유지).
""".strip()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── 유틸 ──────────────────────────────────────────────────────────────────────
def extract_cloud_id(filename: str):
    """파일명에서 cloud-NNN id 추출. 예: 'REQUEST_cloud-032_...' → 'cloud-032'."""
    m = re.search(r'(cloud-\d+)', filename)
    return m.group(1) if m else None


# ── Drive 서비스 ───────────────────────────────────────────────────────────────
def build_drive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        log.error("google-api-python-client 미설치.")
        sys.exit(1)

    if not SERVICE_ACCOUNT_FILE.exists():
        log.error(f"Service Account 키 파일 없음: {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)

    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── 로컬 상태 ──────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    return {
        "last_check_utc": None,
        "processed_ids": [],
        "last_seen_cloud_id": None,
        "open_waits": [],
        "state_local_file_id": None,
    }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── Drive 파일 조작 ────────────────────────────────────────────────────────────
def list_new_cloud_files(service, last_check_utc):
    """parentId 직접 조회 (v1.4 §1 — list_recent_files 금지).
    createdTime 필터 대신 processed_ids로 중복 제거 — 클로드 실패 후 last_check_utc
    갱신으로 미처리 메시지가 영구 누락되는 버그 방지.
    """
    q_parts = [
        f"'{COMMS_FOLDER_ID}' in parents",
        "name contains 'cloud-to-local'",
    ]

    result = service.files().list(
        q=" and ".join(q_parts),
        fields="files(id,name,createdTime,mimeType,size)",
        orderBy="createdTime asc",
        pageSize=20,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return result.get("files", [])


def read_drive_file(service, file_id):
    """파일 텍스트 내용 다운로드."""
    try:
        content = service.files().get_media(fileId=file_id).execute()
        return content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    except Exception as e:
        log.warning(f"파일 읽기 실패 {file_id}: {e}")
        return None


def write_drive_file(service, title, content, file_id=None):
    """Drive에 텍스트 파일 생성(file_id=None) 또는 내용 업데이트(file_id 지정)."""
    from googleapiclient.http import MediaInMemoryUpload
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain", resumable=False)
    try:
        if file_id:
            result = service.files().update(
                fileId=file_id, media_body=media,
                supportsAllDrives=True,
            ).execute()
            log.info(f"Drive 파일 업데이트: {title} ({file_id})")
        else:
            meta = {"name": title, "parents": [COMMS_FOLDER_ID]}
            result = service.files().create(
                body=meta, media_body=media,
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
            log.info(f"Drive 파일 생성: {title} (id={result['id']})")
        return result.get("id")
    except Exception as e:
        log.error(f"Drive 파일 쓰기 실패 ({title}): {e}")
        return None


# ── v1.4 STATE 파일 ────────────────────────────────────────────────────────────
def write_state_local(service, state, activity="IDLE", open_waits=None):
    """STATE_local.md를 _comms/에 덮어쓰기 (v1.4 §2)."""
    now = datetime.now(timezone.utc)
    next_poll = now + timedelta(minutes=POLL_INTERVAL_MIN)
    waits = open_waits or state.get("open_waits", [])

    content = f"""---
doc_version: 1.4
from: local
kind: STATE
---

ts: {now.strftime('%Y-%m-%dT%H:%MZ')}
alive: yes
last_seen_peer_id: {state.get('last_seen_cloud_id') or 'unknown'}
open_waits: {json.dumps(waits)}
activity: {activity}
poll_interval: {POLL_INTERVAL_MIN}min
next_poll_eta: {next_poll.strftime('%Y-%m-%dT%H:%MZ')}
"""
    fid = state.get("state_local_file_id")
    new_id = write_drive_file(service, "STATE_local.md", content, file_id=fid)
    if new_id:
        state["state_local_file_id"] = new_id


def read_state_cloud(service):
    """STATE_cloud.md 파일 ID를 검색 후 내용 파싱 (v1.4 §2)."""
    try:
        result = service.files().list(
            q=f"'{COMMS_FOLDER_ID}' in parents and name = 'STATE_cloud.md' and trashed = false",
            fields="files(id,name,modifiedTime)",
            orderBy="modifiedTime desc",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = result.get("files", [])
        if not files:
            return None
        content = read_drive_file(service, files[0]["id"])
        if not content:
            return None
        parsed = {}
        for line in content.splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#") and not line.startswith("---"):
                k, _, v = line.partition(":")
                parsed[k.strip()] = v.strip()
        parsed["_modified"] = files[0]["modifiedTime"]
        return parsed
    except Exception as e:
        log.warning(f"STATE_cloud 읽기 실패: {e}")
        return None


# ── v1.4 3대 점검 ──────────────────────────────────────────────────────────────
def check_health(service, state, cloud_state):
    """생존(liveness) / 전달갭(delivery gap) / 교착(deadlock) 점검 (v1.4 §3)."""
    if not cloud_state:
        log.warning("STATE_cloud.md 없음 — 헬스체크 스킵")
        return

    now = datetime.now(timezone.utc)
    alerts = []

    # 1. 생존 점검
    cloud_ts_str = cloud_state.get("ts", "")
    try:
        cloud_ts = datetime.fromisoformat(cloud_ts_str.replace("Z", "+00:00"))
        age_min = (now - cloud_ts).total_seconds() / 60
        cloud_poll = int(cloud_state.get("poll_interval", "15").replace("min", "").strip())
        if age_min > cloud_poll * 2:
            alerts.append(f"[LIVENESS] cloud STATE가 {age_min:.0f}분 전 — 다운 의심 (임계: {cloud_poll*2}분)")
    except Exception:
        pass

    # 2. 전달갭 점검 — open_waits 기준 유예 초과
    my_open = state.get("open_waits", [])
    cloud_last_seen = cloud_state.get("last_seen_local_id") or cloud_state.get("last_seen_peer_id", "")
    for wait_id in my_open:
        # wait_id가 cloud_last_seen보다 최신이면 cloud가 못 본 것
        if wait_id and cloud_last_seen and wait_id > cloud_last_seen:
            alerts.append(f"[DELIVERY_GAP] cloud가 {wait_id}를 아직 미확인 (cloud last_seen: {cloud_last_seen})")

    # 3. 교착 점검 — 양측 open_waits 있고 서로 가리킴
    cloud_open_str = cloud_state.get("open_waits", "[]")
    try:
        cloud_open = json.loads(cloud_open_str)
    except Exception:
        cloud_open = []

    if my_open and cloud_open:
        alerts.append(f"[DEADLOCK_RISK] 양측 open_waits 비어있지 않음 — local:{my_open} / cloud:{cloud_open}")

    if alerts:
        msg = "\n".join(f"- {a}" for a in alerts)
        log.warning(f"헬스체크 이상 감지:\n{msg}")
        post_alert(service, alerts)
    else:
        log.info("헬스체크 정상")


def _post_status(service, message: str):
    """처리 실패·에러 시 STATUS 파일 게시 (v2.0 §5 — 조용한 IDLE 금지)."""
    now = datetime.now(timezone.utc)
    content = f"""---
doc_version: 1.4
from: local
kind: STATUS
ts: {now.isoformat()}
---

# STATUS — 처리 실패 또는 에러

{message}

— local (자동 게시)
"""
    fname = f"STATUS_local_{now.strftime('%Y%m%dT%H%MZ')}.md"
    write_drive_file(service, fname, content)
    log.warning(f"STATUS 게시: {fname}")


def post_alert(service, alerts):
    """ALERT_local.md 게시 (v1.4 §4)."""
    now = datetime.now(timezone.utc)
    content = f"""---
doc_version: 1.4
from: local
kind: ALERT
ts: {now.isoformat()}
---

# ALERT — 로컬 헬스체크 이상 감지

{chr(10).join(f'- {a}' for a in alerts)}

— local (자동 게시)
"""
    fname = f"ALERT_local_{now.strftime('%Y%m%dT%H%MZ')}.md"
    write_drive_file(service, fname, content)


# ── Claude CLI 트리거 ──────────────────────────────────────────────────────────
def trigger_claude():
    """v3: 파일 목록 전달 없이 v3 프롬프트만 전달. Claude 세션이 직접 Drive 스캔."""
    log.info("Claude Code CLI v3 깨우기 (스캔·실행 강제 프롬프트)")
    try:
        result = subprocess.run(
            [CLAUDE_CMD, "--print", "-p", PROCESS_PROMPT_V3],
            capture_output=True, text=True, encoding="utf-8",
            timeout=600, cwd=r"C:\project\quant",
        )
        if result.returncode == 0:
            log.info("Claude v3 처리 완료")
            if result.stdout:
                log.info(f"결과:\n{result.stdout[:500]}")
            return True
        else:
            log.error(f"Claude 오류 (exit {result.returncode}):\n{result.stderr[:300]}")
            return False
    except subprocess.TimeoutExpired:
        log.error("Claude 실행 타임아웃 (10분)")
        return False
    except FileNotFoundError:
        log.error(f"'{CLAUDE_CMD}' 명령을 찾을 수 없음. PATH를 확인하세요.")
        return False


# ── 메인 폴링 루프 ─────────────────────────────────────────────────────────────
def poll_once(service, state, interval_min=POLL_INTERVAL_MIN):
    """v3: 매 주기 무조건 Claude를 깨운다. Drive 스캔·실행은 Claude 세션에 위임."""
    now_utc = datetime.now(timezone.utc).isoformat()
    log.info(f"폴링 시작 v3 (last_check: {state.get('last_check_utc') or '처음'})")

    # 1. STATE_local.md 폴링 시작 표시
    write_state_local(service, state, activity="폴링 중 — Claude v3 깨우기")

    # 2. Claude v3 프롬프트 전달 (신규 파일 여부 무관, 무조건 실행)
    success = trigger_claude()
    if not success:
        _post_status(service, "Claude CLI v3 실행 실패 — 다음 주기에 재시도")

    # 3. STATE_cloud.md 읽고 헬스체크
    cloud_state = read_state_cloud(service)
    check_health(service, state, cloud_state)

    # 4. STATE_local.md 완료 상태로 업데이트 (open_waits 있으면 IDLE 금지)
    open_waits = state.get("open_waits", [])
    final_activity = (f"PENDING — {','.join(open_waits)}" if open_waits
                      else "IDLE — 다음 폴링 대기")
    write_state_local(service, state, activity=final_activity)

    state["last_check_utc"] = now_utc
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description="QuantMaster Drive Poll Daemon v1.4")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL_MIN * 60,
                        help=f"폴링 간격(초), 기본 {POLL_INTERVAL_MIN*60}")
    args = parser.parse_args()

    log.info("=== Drive Poll Daemon v3.0 시작 ===")
    log.info(f"_comms/ folder: {COMMS_FOLDER_ID}")
    log.info(f"폴링 간격: {args.interval}초" if not args.once else "1회 실행 모드")

    service = build_drive_service()
    state = load_state()

    if args.once:
        poll_once(service, state, interval_min=args.interval // 60)
        return

    while True:
        try:
            poll_once(service, state, interval_min=args.interval // 60)
        except Exception as e:
            log.exception(f"폴링 오류: {e}")
        log.info(f"다음 폴링까지 {args.interval}초 대기")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
