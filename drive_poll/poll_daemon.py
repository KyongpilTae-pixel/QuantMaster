"""
QuantMaster Drive Poll Daemon — v2.0
_comms/ 폴더를 주기적으로 폴링하여 cloud 메시지를 감지하고
Claude Code CLI로 처리 프롬프트를 전달한다.
프로토콜 v1.4 + v2.0 규격(cloud-034 SPEC):
- last_seen_cloud_id: 실제 cloud-NNN id 저장 (kind 단어 금지)
- open_waits 있으면 activity IDLE 금지
- REQUEST/NOTE/SPEC 타입별 처리
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

PROCESS_PROMPT = """Google Drive _comms/ 폴더(parentId={comms_id})에서 cloud-to-local 메시지를 확인하고 프로토콜 v2.0(cloud-034 SPEC)에 따라 처리한다.

새로 감지된 파일:
{new_files}

처리 규칙 (v2.0):
1. 각 파일을 읽는다 (mcp__claude_ai_Google_Drive__read_file_content).
2. 타입별 처리:
   - REQUEST: open_waits에 추가 → ACK 발행 → 실제 작업 실행(분석·계산·백테스트 등) → REPLY 발행 → open_waits 제거.
   - NOTE(EXECUTE류): 참조된 REQUEST를 찾아 실행 → REPLY 발행.
   - SPEC: 지정된 코드 변경(poll_daemon.py 등)을 즉시 적용 → STATUS 게시.
   - ACK/REPLY/STATE(cloud): last_seen_cloud_id만 갱신, 추가 처리 없음.
3. 파일명 규칙: MSG_<UTC시각Z>_local-to-cloud_<TYPE>[_topic].md
4. contentMimeType: text/plain, doc_version: 1.4 헤더 포함.
5. STATE_local.md 갱신: last_seen_peer_id에 실제 cloud-NNN id 기록, open_waits 있으면 activity IDLE 금지.
6. 실행 불가(에러·데이터 없음)면 STATUS 파일 게시(사유 포함). 조용한 IDLE 금지.

완료 후 처리 결과를 간략히 보고한다.
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
def trigger_claude(new_files):
    file_list = "\n".join(
        f"- {f['name']} (id: {f['id']}, created: {f['createdTime']})" for f in new_files
    )
    prompt = PROCESS_PROMPT.format(comms_id=COMMS_FOLDER_ID, new_files=file_list)
    log.info(f"Claude Code CLI 실행: {len(new_files)}개 파일 처리 요청")
    try:
        result = subprocess.run(
            [CLAUDE_CMD, "--print", "-p", prompt],
            capture_output=True, text=True, encoding="utf-8",
            timeout=600, cwd=r"C:\project\quant",
        )
        if result.returncode == 0:
            log.info("Claude 처리 완료")
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
    now_utc = datetime.now(timezone.utc).isoformat()
    last = state.get("last_check_utc")
    processed = set(state.get("processed_ids", []))

    # 1. STATE_local.md 갱신 (매 wake 첫 작업)
    write_state_local(service, state, activity="폴링 중")

    # 2. cloud 신규 파일 확인
    log.info(f"폴링 시작 (last_check: {last or '처음'})")
    files = list_new_cloud_files(service, last)
    new = [f for f in files if f["id"] not in processed]

    if new:
        log.info(f"새 메시지 {len(new)}개: {[f['name'] for f in new]}")
        # 마지막으로 본 cloud id 갱신 (실제 cloud-NNN, kind 단어 금지)
        cloud_id = extract_cloud_id(new[-1]["name"])
        if cloud_id:
            state["last_seen_cloud_id"] = cloud_id

        # 파일 타입 분류: ACK/REPLY/STATE/ALERT/STATUS는 Claude CLI 불필요 → 즉시 스킵
        _skip_types = ("ACK", "REPLY", "STATE", "ALERT", "STATUS")
        auto_skip = [f for f in new if f["name"].split("_")[0] in _skip_types]
        need_claude = [f for f in new if f["name"].split("_")[0] not in _skip_types]

        if auto_skip:
            processed.update(f["id"] for f in auto_skip)
            log.info(f"ACK/REPLY/STATE 자동 스킵 {len(auto_skip)}개: {[f['name'] for f in auto_skip]}")

        # open_waits: REQUEST/NOTE 파일 id 추가
        for f in need_claude:
            fname = f["name"]
            if fname.startswith("REQUEST_") or fname.startswith("NOTE_"):
                cid = extract_cloud_id(fname)
                if cid and cid not in state.get("open_waits", []):
                    state.setdefault("open_waits", []).append(cid)

        if need_claude:
            # STATE: 처리 중 표시 (IDLE 금지)
            processing_ids = [extract_cloud_id(f["name"]) or f["id"] for f in need_claude]
            write_state_local(service, state,
                              activity=f"처리 중 — {','.join(str(x) for x in processing_ids)}",
                              open_waits=state.get("open_waits", []))
            success = trigger_claude(need_claude)
            if success:
                processed.update(f["id"] for f in need_claude)
            else:
                # 실패: STATUS 게시 후 미처리 유지
                log.warning("Claude 실패 — 파일 ID를 미처리로 유지(재시도)")
                _post_status(service, f"Claude CLI 실행 실패 — 미처리: {[f['name'] for f in need_claude]}")
    else:
        log.info("새 메시지 없음")

    # 3. STATE_cloud.md 읽고 헬스체크
    cloud_state = read_state_cloud(service)
    check_health(service, state, cloud_state)

    # 4. STATE_local.md 완료 상태로 업데이트 (open_waits 있으면 IDLE 금지)
    open_waits = state.get("open_waits", [])
    final_activity = (f"PENDING — {','.join(open_waits)}" if open_waits
                      else "IDLE — 다음 폴링 대기")
    write_state_local(service, state, activity=final_activity)

    state["last_check_utc"] = now_utc
    state["processed_ids"] = list(processed)[-200:]
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description="QuantMaster Drive Poll Daemon v1.4")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL_MIN * 60,
                        help=f"폴링 간격(초), 기본 {POLL_INTERVAL_MIN*60}")
    args = parser.parse_args()

    log.info("=== Drive Poll Daemon v2.0 시작 ===")
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
