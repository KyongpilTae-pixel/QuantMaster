# -*- coding: utf-8 -*-
"""
email_delivery.py — 뉴스레터 이메일 발송 모듈

구독자 관리 + SMTP 발송.
설정 환경 변수:
  SMTP_HOST   (기본: smtp.gmail.com)
  SMTP_PORT   (기본: 587)
  SMTP_USER   발신 이메일
  SMTP_PASS   앱 비밀번호 (Gmail: 2단계 인증 앱 비밀번호)
  NEWSLETTER_FROM_NAME  (기본: 퀀트레터)

사용법:
  python email_delivery.py subscribe user@example.com
  python email_delivery.py unsubscribe user@example.com
  python email_delivery.py list
  python email_delivery.py send quantletter/output/weekly_2026-09-04.html "주간 리포트 2026-09-04"
  python email_delivery.py test user@example.com   # 테스트 1통 발송
"""

import json
import os
import sys
import smtplib
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime, timezone

SUBSCRIBERS_FILE = os.path.join(os.path.dirname(__file__), "subscribers.json")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_NAME = os.environ.get("NEWSLETTER_FROM_NAME", "퀀트레터")


def load_subscribers() -> list:
    if not os.path.exists(SUBSCRIBERS_FILE):
        return []
    with open(SUBSCRIBERS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_subscribers(subs: list) -> None:
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)


def _valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def subscribe(email: str) -> str:
    email = email.strip().lower()
    if not _valid_email(email):
        return f"[오류] 이메일 형식 불일치: {email}"
    subs = load_subscribers()
    if any(s["email"] == email for s in subs):
        return f"[이미 등록됨] {email}"
    subs.append({
        "email": email,
        "subscribed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active": True,
    })
    save_subscribers(subs)
    return f"[등록 완료] {email}"


def unsubscribe(email: str) -> str:
    email = email.strip().lower()
    subs = load_subscribers()
    before = len(subs)
    subs = [s for s in subs if s["email"] != email]
    if len(subs) == before:
        return f"[없음] {email} 은 등록되지 않았습니다"
    save_subscribers(subs)
    return f"[해지 완료] {email}"


def list_subscribers() -> list:
    return [s["email"] for s in load_subscribers() if s.get("active", True)]


def send_newsletter(html_path: str, subject: str, recipients: list = None) -> dict:
    """
    HTML 파일을 읽어 구독자 전체에게 발송.
    recipients가 지정되면 그 목록에만 발송 (테스트용).
    반환: {"sent": N, "failed": [...]}
    """
    if not SMTP_USER or not SMTP_PASS:
        return {"error": "SMTP_USER / SMTP_PASS 환경 변수 미설정. 발송 불가."}

    if not os.path.exists(html_path):
        return {"error": f"HTML 파일 없음: {html_path}"}

    with open(html_path, encoding="utf-8") as f:
        html_body = f.read()

    targets = recipients if recipients is not None else list_subscribers()
    if not targets:
        return {"sent": 0, "failed": [], "note": "구독자 없음"}

    sent, failed = 0, []
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)

        for to_email in targets:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = formataddr((FROM_NAME, SMTP_USER))
                msg["To"] = to_email
                msg.attach(MIMEText(html_body, "html", "utf-8"))
                server.sendmail(SMTP_USER, [to_email], msg.as_string())
                sent += 1
                print(f"  [발송] {to_email}")
            except Exception as e:
                failed.append({"email": to_email, "error": str(e)})
                print(f"  [실패] {to_email}: {e}")

        server.quit()
    except Exception as e:
        return {"error": f"SMTP 연결 실패: {e}", "sent": sent, "failed": failed}

    return {"sent": sent, "failed": failed}


def _auto_send_if_configured(html_path: str, subject: str) -> None:
    """auto_publish.py에서 호출. SMTP 미설정이면 조용히 스킵."""
    if not SMTP_USER or not SMTP_PASS:
        print("[이메일] SMTP 미설정 → 발송 건너뜀 (SMTP_USER/SMTP_PASS 설정 필요)")
        return
    subs = list_subscribers()
    if not subs:
        print("[이메일] 구독자 없음 → 발송 건너뜀")
        return
    print(f"[이메일] {len(subs)}명 발송 시작: {subject}")
    result = send_newsletter(html_path, subject)
    if "error" in result:
        print(f"[이메일 오류] {result['error']}")
    else:
        print(f"[이메일] 완료: {result['sent']}건 성공, {len(result['failed'])}건 실패")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0].lower()

    if cmd == "subscribe" and len(args) == 2:
        print(subscribe(args[1]))

    elif cmd == "unsubscribe" and len(args) == 2:
        print(unsubscribe(args[1]))

    elif cmd == "list":
        subs = list_subscribers()
        if subs:
            print(f"구독자 {len(subs)}명:")
            for e in subs:
                print(f"  {e}")
        else:
            print("구독자 없음")

    elif cmd == "send" and len(args) >= 3:
        html_path = args[1]
        subject = " ".join(args[2:])
        print(f"발송 대상: {html_path}")
        print(f"제목: {subject}")
        result = send_newsletter(html_path, subject)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "test" and len(args) == 2:
        test_email = args[1]
        # 간단한 테스트 메일
        html = "<h2>퀀트레터 테스트</h2><p>이메일 발송 설정이 정상적으로 작동합니다.</p>"
        tmp = os.path.join(os.path.dirname(__file__), "_test_mail.html")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        result = send_newsletter(tmp, "[퀀트레터] 테스트 메일", recipients=[test_email])
        os.remove(tmp)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(__doc__)
        sys.exit(1)
