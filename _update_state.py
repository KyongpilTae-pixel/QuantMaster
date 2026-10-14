import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

SA_FILE = Path("drive_poll/service_account.json")
STATE_FILE = Path("drive_poll/poll_state.json")
creds = service_account.Credentials.from_service_account_file(str(SA_FILE), scopes=["https://www.googleapis.com/auth/drive"])
svc = build("drive", "v3", credentials=creds, cache_discovery=False)
KEEP_ID = "193-4KF1fR8J_ZDUSiiN7HyHrCG3UtjhJ"
TRASH_IDS = ["1Cw0TOaxmMZuEgao3bteagVwZedzvwSij", "1S4oWb8isn-3oaopE0Dsho_O4VNKR8p1m", "1Q5gNhe8PTldmv5GJYeUEX-cJxIgOvY5v"]
now = datetime.now(timezone.utc)
nxt = now + timedelta(minutes=30)
lines2 = ["---", "doc_version: 1.4", "from: local", "kind: STATE", "---", "",
          "ts: " + now.strftime("%Y-%m-%dT%H:%MZ"),
          "alive: yes", "last_seen_peer_id: cloud-052", "open_waits: []", "activity: IDLE",
          "poll_interval: 30min", "next_poll_eta: " + nxt.strftime("%Y-%m-%dT%H:%MZ")]
content = chr(10).join(lines2) + chr(10)
media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain", resumable=False)
svc.files().update(fileId=KEEP_ID, media_body=media, supportsAllDrives=True).execute()
print("OK updated " + KEEP_ID)
for fid in TRASH_IDS:
    try:
        svc.files().update(fileId=fid, body={"trashed": True}, supportsAllDrives=True).execute()
        print("TRASH " + fid)
    except Exception as e:
        print("WARN " + str(e))
with open(STATE_FILE, encoding="utf-8-sig") as f: state = json.load(f)
state["state_local_file_id"] = KEEP_ID
state["last_seen_cloud_id"] = "cloud-052"
state["open_waits"] = []
with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(state, f, ensure_ascii=False, indent=2)
print("OK poll_state updated")