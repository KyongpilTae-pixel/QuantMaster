from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
creds = service_account.Credentials.from_service_account_file("drive_poll/service_account.json", scopes=["https://www.googleapis.com/auth/drive"])
service = build("drive", "v3", credentials=creds)
content = "# STATE_local

last_seen_peer_id: cloud-052
open_waits: []
activity: IDLE
ts: 2026-10-14T07:40Z
poll_interval: 30min
next_poll_eta: 2026-10-14T08:10Z

## Poll Summary
- scanned: cloud-001~cloud-052 (52 total)
- new_unprocessed: 0
- status: IDLE
"
file_id = "1dKD9HDx1cexrH77d7wxUNf5OguNoateV"
media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain", resumable=False)
result = service.files().update(fileId=file_id, media_body=media).execute()
print("Updated:", result.get("name"), result.get("modifiedTime"))
