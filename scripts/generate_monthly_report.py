"""월간 리포트 자동 생성.

quantReports/YYYY-MM.html 에 저장.
실행 권장 시점: 매월 1일 08:00 KST

Windows 작업 스케줄러 등록:
  schtasks /create /tn "QuantMaster 월간리포트" ^
    /tr "C:\\Users\\Administrator\\miniconda3\\envs\\quantmaster\\python.exe C:\\project\\quant\\scripts\\generate_monthly_report.py" ^
    /sc monthly /d 1 /st 08:00 /ru SYSTEM
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.monthly_report_generator import generate_full_monthly_report


def main():
    today = datetime.today().strftime("%Y-%m-%d")
    print(f"[{today}] 월간 리포트 생성 시작", flush=True)

    try:
        path = generate_full_monthly_report()
        print(f"[{today}] 완료 → {path}", flush=True)
    except Exception as e:
        print(f"[{today}] 오류: {e}", flush=True)
        raise


if __name__ == "__main__":
    main()
