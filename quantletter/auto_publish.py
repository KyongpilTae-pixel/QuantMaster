# -*- coding: utf-8 -*-
"""
퀀트레터 자동 발행 스케줄러
============================
매주 금요일 실행 → 주간 리포트 생성
달의 첫째 금요일 실행 → 전월 월간 리포트도 생성

영속 상태 (output/ 폴더):
  ledger_kr.json      KR 포지션 원장
  ledger_us.json      US 포지션 원장
  picks_history.json  주간 픽 이력 (월간 성적표 계산용)
  publish.log         실행 이력

사용:
  python auto_publish.py                     # 오늘 기준 (금요일이어야 실행)
  python auto_publish.py --date 2026-08-01   # 특정 날짜 강제 실행
  python auto_publish.py --force             # 파일 이미 있어도 재생성
  python auto_publish.py --refresh-data      # 데이터 먼저 재다운로드
  python auto_publish.py --setup-scheduler   # Windows 작업 스케줄러 등록
  python auto_publish.py --show-state        # 현재 포지션/이력 출력
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

import pandas as pd

# ── 경로 설정 ─────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR    = os.path.join(SCRIPT_DIR, "output")
os.makedirs(OUT_DIR, exist_ok=True)
os.chdir(SCRIPT_DIR)

LEDGER_KR    = os.path.join(OUT_DIR, "ledger_kr.json")
LEDGER_US    = os.path.join(OUT_DIR, "ledger_us.json")
PICKS_HIST   = os.path.join(OUT_DIR, "picks_history.json")
LOG_FILE     = os.path.join(OUT_DIR, "publish.log")
PYTHON_EXE   = sys.executable   # 현재 conda 환경 Python


# ── 로거 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)),
    ],
)
log = logging.getLogger(__name__)


# ── 영속 상태 I/O ─────────────────────────────────────────────

def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 날짜 헬퍼 ─────────────────────────────────────────────────

def is_friday(d: date) -> bool:
    return d.weekday() == 4

def is_first_friday_of_month(d: date) -> bool:
    return is_friday(d) and d.day <= 7

def last_friday_on_or_before(d: date) -> date:
    """d 이전(포함) 가장 최근 금요일."""
    days_back = (d.weekday() - 4) % 7
    return d - timedelta(days=days_back)

def prev_month(d: date):
    """d 이전 달 (year, month)."""
    if d.month == 1:
        return d.year - 1, 12
    return d.year, d.month - 1


# ── 데이터 새로고침 ───────────────────────────────────────────

def refresh_data():
    log.info("데이터 재다운로드 시작...")
    for script in ["fetch_kr_stocks.py", "fetch_sample_data.py"]:
        path = os.path.join(SCRIPT_DIR, script)
        if not os.path.exists(path):
            log.warning(f"  {script} 없음 — 건너뜀")
            continue
        log.info(f"  {script} 실행 중...")
        result = subprocess.run([PYTHON_EXE, path], capture_output=True, text=True)
        if result.returncode == 0:
            log.info(f"  {script} 완료")
        else:
            log.error(f"  {script} 오류:\n{result.stderr[-500:]}")
            raise RuntimeError(f"데이터 다운로드 실패: {script}")


# ── generate_history 함수 임포트 ──────────────────────────────

def _import_gh():
    """generate_history 모듈 함수들을 임포트."""
    import generate_history as gh
    return gh


# ── 인덱스 재빌드 ─────────────────────────────────────────────

def rebuild_index():
    import glob
    weekly  = sorted(glob.glob(os.path.join(OUT_DIR, "weekly_*.html")))
    monthly = sorted(glob.glob(os.path.join(OUT_DIR, "monthly_*.html")))
    gh = _import_gh()
    html = gh.build_index(list(reversed(weekly)), list(reversed(monthly)))
    idx_path = os.path.join(OUT_DIR, "index.html")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"index.html 재빌드 ({len(weekly)}주간 + {len(monthly)}월간)")


# ── 주간 리포트 생성 ──────────────────────────────────────────

def run_weekly(target: date, force: bool = False) -> str | None:
    """
    target 날짜(금요일) 기준 주간 리포트 생성.
    Returns: 생성된 파일 경로, 또는 None(스킵)
    """
    fname = os.path.join(OUT_DIR, f"weekly_{target.isoformat()}.html")
    if os.path.exists(fname) and not force:
        log.info(f"주간 {target} — 이미 존재, 건너뜀 (--force 로 재생성)")
        return fname

    log.info(f"주간 {target} 리포트 생성 중...")
    gh = _import_gh()

    kr_px, us_px, kr_names, _ = gh.load_all()
    name_fn = lambda c: kr_names.get(str(c), c)
    cutoff  = pd.Timestamp(target)

    kr_lv, _ = gh.picks_lowvol(kr_px, kr_names, cutoff)
    kr_sk, _ = gh.picks_momskip(kr_px, kr_names, cutoff)
    us_mo, _ = gh.picks_us_mom(us_px, cutoff)

    if not kr_lv or not us_mo:
        log.warning(f"주간 {target} — 데이터 부족, 건너뜀")
        return None

    # 영속 레저 로드 → 평가 → 편입 → 저장
    kr_led = load_json(LEDGER_KR, {})
    us_led = load_json(LEDGER_US, {})

    kr_pos, kr_cls = gh.eval_ledger(kr_led, kr_px, cutoff, name_fn)
    us_pos, us_cls = gh.eval_ledger(us_led, us_px, cutoff)

    gh.add_to_ledger(kr_led,
                     [p["code"] for p in kr_lv] + [p["code"] for p in kr_sk],
                     kr_px, cutoff)
    gh.add_to_ledger(us_led, [p["ticker"] for p in us_mo], us_px, cutoff)

    save_json(LEDGER_KR, kr_led)
    save_json(LEDGER_US, us_led)

    # 픽 이력 저장 (월간 성적표용)
    hist = load_json(PICKS_HIST, {})
    hist[target.isoformat()] = {
        "us":      [p["ticker"] for p in us_mo],
        "kr_lv":   [p["code"]   for p in kr_lv],
        "kr_skip": [p["code"]   for p in kr_sk],
    }
    save_json(PICKS_HIST, hist)

    html = gh.build_weekly(cutoff, kr_lv, kr_sk, us_mo, us_pos, kr_pos)
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)

    sells = [name_fn(t) for t in kr_cls] + list(us_cls)
    log.info(f"주간 {target} 완료 | KR:{len(kr_led)} US:{len(us_led)}"
             + (f" | 매도: {sells}" if sells else ""))
    return fname


# ── 월간 리포트 생성 ──────────────────────────────────────────

def run_monthly(year: int, month: int, force: bool = False) -> str | None:
    """
    year/month 의 월간 리포트 생성.
    성적표 기간: 해당 월의 첫 금요일 → 마지막 금요일
    자산배분 기준: 해당 월의 마지막 거래일
    """
    fname = os.path.join(OUT_DIR, f"monthly_{year}-{month:02d}.html")
    if os.path.exists(fname) and not force:
        log.info(f"월간 {year}-{month:02d} — 이미 존재, 건너뜀 (--force 로 재생성)")
        return fname

    log.info(f"월간 {year}-{month:02d} 리포트 생성 중...")
    gh = _import_gh()
    kr_px, us_px, kr_names, macro = gh.load_all()
    name_fn = lambda c: kr_names.get(str(c), c)

    # 해당 월 마지막 거래일 (데이터 내 해당 월 마지막 날짜)
    all_dates_kr = kr_px.index
    month_dates  = all_dates_kr[(all_dates_kr.year == year) & (all_dates_kr.month == month)]
    if len(month_dates) == 0:
        log.warning(f"월간 {year}-{month:02d} — 가격 데이터 없음, 건너뜀")
        return None
    cutoff = month_dates[-1]

    w, s = gh.alloc_weights(macro, cutoff)

    # 픽 이력에서 해당 월 금요일 픽 추출
    hist = load_json(PICKS_HIST, {})
    month_fridays = sorted(
        [date.fromisoformat(k) for k, v in hist.items()
         if date.fromisoformat(k).year == year
         and date.fromisoformat(k).month == month],
    )

    sc_us = sc_kr_lv = sc_kr_skip = None
    sc_from = sc_to = None

    if len(month_fridays) >= 2:
        base_dt = pd.Timestamp(month_fridays[0])
        end_dt  = pd.Timestamp(month_fridays[-1])
        picks   = hist[month_fridays[0].isoformat()]
        sc_from = str(month_fridays[0])
        sc_to   = str(month_fridays[-1])

        sc_us     = gh.compute_sc(picks["us"],     us_px, base_dt, end_dt)
        sc_kr_lv  = gh.compute_sc(picks["kr_lv"],  kr_px, base_dt, end_dt, name_fn)
        sc_kr_skip= gh.compute_sc(picks["kr_skip"], kr_px, base_dt, end_dt, name_fn)
    elif len(month_fridays) == 1:
        log.info(f"월간 {year}-{month:02d} — 금요일 1건만 있어 성적표 생략")

    html = gh.build_monthly(year, month, w, s,
                            sc_us, sc_kr_lv, sc_kr_skip,
                            sc_from, sc_to)
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)

    log.info(f"월간 {year}-{month:02d} 완료 | 성적표 기간: {sc_from}~{sc_to}")
    return fname


# ── Windows 작업 스케줄러 등록 ────────────────────────────────

def setup_scheduler():
    task_name = "QuantLetter_AutoPublish"
    script    = os.path.join(SCRIPT_DIR, "auto_publish.py")
    cmd       = f'"{PYTHON_EXE}" "{script}"'

    ps_cmd = (
        f'$action = New-ScheduledTaskAction -Execute "{PYTHON_EXE}" '
        f'-Argument "{script}"; '
        f'$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "6:00PM"; '
        f'Register-ScheduledTask -TaskName "{task_name}" '
        f'-Action $action -Trigger $trigger -RunLevel Highest -Force'
    )
    print("\n=== Windows 작업 스케줄러 등록 ===")
    print(f"작업명: {task_name}")
    print(f"실행: {cmd}")
    print(f"주기: 매주 금요일 18:00\n")
    print("아래 PowerShell 명령을 관리자 권한으로 실행하세요:\n")
    print(f"  {ps_cmd}\n")
    print("또는 schtasks 방식:\n")
    schtasks = (
        f'schtasks /create /tn "{task_name}" '
        f'/tr "\"{PYTHON_EXE}\" \"{script}\"" '
        f'/sc weekly /d FRI /st 18:00 /rl HIGHEST /f'
    )
    print(f"  {schtasks}\n")
    print("등록 후 확인:")
    print(f'  schtasks /query /tn "{task_name}" /fo list\n')

    try:
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("[OK] 작업 스케줄러 등록 완료")
            log.info(f"작업 스케줄러 등록: {task_name}")
        else:
            print(f"[WARN] 자동 등록 실패 (권한 부족?): {result.stderr.strip()}")
            print("  위 명령을 관리자 PowerShell에서 수동 실행하세요.")
    except Exception as e:
        print(f"[WARN] PowerShell 실행 실패: {e}")
        print("  위 명령을 관리자 PowerShell에서 수동 실행하세요.")


# ── 상태 초기화 (최초 1회) ────────────────────────────────────

def init_state():
    """
    generate_history.py 로 만든 과거 주간 파일들을 기반으로
    picks_history.json 과 포지션 레저를 복원한다.
    """
    from datetime import datetime as dt
    log.info("=== 상태 초기화 (과거 픽 이력 복원) ===")
    gh      = _import_gh()
    kr_px, us_px, kr_names, _ = gh.load_all()
    name_fn = lambda c: kr_names.get(str(c), c)

    START = dt(2026, 6, 1)
    END   = dt(2026, 7, 31)
    fridays = gh.get_fridays(START, END)

    hist  = {}
    kr_led = {}
    us_led = {}

    for fri in fridays:
        cutoff = pd.Timestamp(fri)
        fname  = os.path.join(OUT_DIR, f"weekly_{fri.strftime('%Y-%m-%d')}.html")
        if not os.path.exists(fname):
            log.info(f"  {fri.date()} — HTML 없음, 건너뜀")
            continue

        kr_lv, _ = gh.picks_lowvol(kr_px, kr_names, cutoff)
        kr_sk, _ = gh.picks_momskip(kr_px, kr_names, cutoff)
        us_mo, _ = gh.picks_us_mom(us_px, cutoff)

        if not kr_lv or not us_mo:
            continue

        hist[fri.strftime("%Y-%m-%d")] = {
            "us":      [p["ticker"] for p in us_mo],
            "kr_lv":   [p["code"]   for p in kr_lv],
            "kr_skip": [p["code"]   for p in kr_sk],
        }

        # 포지션도 동일하게 시뮬레이션
        gh.eval_ledger(kr_led, kr_px, cutoff, name_fn)
        gh.eval_ledger(us_led, us_px, cutoff)
        gh.add_to_ledger(kr_led,
                         [p["code"] for p in kr_lv]+[p["code"] for p in kr_sk],
                         kr_px, cutoff)
        gh.add_to_ledger(us_led, [p["ticker"] for p in us_mo], us_px, cutoff)
        log.info(f"  {fri.date()} 복원 완료")

    save_json(PICKS_HIST, hist)
    save_json(LEDGER_KR, kr_led)
    save_json(LEDGER_US, us_led)
    log.info(f"픽 이력 {len(hist)}주 저장 | KR {len(kr_led)}종목 | US {len(us_led)}종목")


# ── 현재 상태 출력 ────────────────────────────────────────────

def show_state():
    kr_led = load_json(LEDGER_KR, {})
    us_led = load_json(LEDGER_US, {})
    hist   = load_json(PICKS_HIST, {})

    print(f"\n=== 현재 포지션 현황 ===")
    print(f"KR 보유 {len(kr_led)}종목: {', '.join(kr_led.keys()) or '없음'}")
    print(f"US 보유 {len(us_led)}종목: {', '.join(us_led.keys()) or '없음'}")
    print(f"\n픽 이력: {len(hist)}주")
    for k in sorted(hist.keys())[-5:]:
        v = hist[k]
        print(f"  {k}: US={v['us']} KR저변동성={v['kr_lv']}")

    import glob
    weekly  = sorted(glob.glob(os.path.join(OUT_DIR, "weekly_*.html")))
    monthly = sorted(glob.glob(os.path.join(OUT_DIR, "monthly_*.html")))
    print(f"\n생성 파일: 주간 {len(weekly)}개 / 월간 {len(monthly)}개")
    if weekly:  print(f"  최신 주간: {os.path.basename(weekly[-1])}")
    if monthly: print(f"  최신 월간: {os.path.basename(monthly[-1])}")


# ── 메인 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="퀀트레터 자동 발행")
    parser.add_argument("--date",             default=None,   help="실행 기준 날짜 (YYYY-MM-DD)")
    parser.add_argument("--force",            action="store_true", help="기존 파일 덮어쓰기")
    parser.add_argument("--refresh-data",     action="store_true", help="실행 전 데이터 재다운로드")
    parser.add_argument("--setup-scheduler",  action="store_true", help="Windows 작업 스케줄러 등록")
    parser.add_argument("--show-state",       action="store_true", help="현재 포지션/이력 출력")
    parser.add_argument("--init-state",       action="store_true", help="과거 픽 이력 복원 (최초 1회)")
    args = parser.parse_args()

    if args.setup_scheduler:
        setup_scheduler()
        return

    if args.show_state:
        show_state()
        return

    if args.init_state:
        init_state()
        return

    # 기준 날짜 결정
    if args.date:
        today = date.fromisoformat(args.date)
    else:
        today = date.today()

    log.info(f"=== 자동 발행 시작: {today} ===")

    # 데이터 새로고침
    if args.refresh_data:
        refresh_data()

    # 금요일이 아니면 가장 최근 금요일로 맞춤
    target_friday = last_friday_on_or_before(today)
    if target_friday != today and not args.date:
        log.info(f"오늘({today})은 금요일이 아님 — 가장 최근 금요일 {target_friday} 기준으로 실행")

    # ① 주간 리포트
    weekly_file = run_weekly(target_friday, force=args.force)

    # ② 첫째 금요일이면 전월 월간 리포트
    monthly_file = None
    if is_first_friday_of_month(target_friday):
        py, pm = prev_month(target_friday)
        log.info(f"첫째 금요일 감지 → 전월({py}-{pm:02d}) 월간 리포트 생성")
        monthly_file = run_monthly(py, pm, force=args.force)

    # ③ 인덱스 재빌드
    if weekly_file or monthly_file:
        rebuild_index()

    generated = [f for f in [weekly_file, monthly_file] if f]
    log.info(f"=== 완료: {len(generated)}개 파일 생성 ===")
    for f in generated:
        log.info(f"  → {os.path.basename(f)}")


if __name__ == "__main__":
    main()
