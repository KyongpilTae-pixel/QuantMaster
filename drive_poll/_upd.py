import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
SA = r"C:\project\quant\drive_poll\service_account.json"
FID = "1lFGdVlhoozEWIaRGBGVoij2h1AHd0ZcU"
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
creds = service_account.Credentials.from_service_account_file(SA, scopes=["https://www.googleapis.com/auth/drive"])
svc = build("drive","v3",credentials=creds,cache_discovery=False)
now = datetime.now(timezone.utc)
nxt = now + timedelta(minutes=30)
ts = now.strftime("%Y-%m-%dT%H:%MZ")
nt = nxt.strftime("%Y-%m-%dT%H:%MZ")
items = ["---","doc_version: 1.4","from: local","kind: STATE","---","","ts: "+ts,"alive: yes","last_seen_peer_id: cloud-054","open_waits: []","activity: IDLE","poll_interval: 30min","next_poll_eta: "+nt,""]
body = chr(10).join(items)
media = MediaInMemoryUpload(body.encode("utf-8"),mimetype="text/plain",resumable=False)
r = svc.files().update(fileId=FID,media_body=media,supportsAllDrives=True).execute()
print("OK",r.get("id"),ts)
