import io, json
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaInMemoryUpload
SA = r"C:\project\quant\drive_poll\service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_file(SA, scopes=SCOPES)
svc = build("drive", "v3", credentials=creds)
cnt = '---\ndoc_version: 1.4\nfrom: local\nkind: STATE\n---\n\nts: 2026-10-14T10:45Z\nalive: yes\nlast_seen_peer_id: cloud-052\nopen_waits: []\nactivity: IDLE\npoll_interval: 30min\nnext_poll_eta: 2026-10-14T11:15Z\n'
fid = "17jr4jYRnlXL7K6yqv1IrxiElfJQ10h3S"
media = MediaInMemoryUpload(cnt.encode("utf-8"), mimetype="text/plain", resumable=False)
svc.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
print("STATE_local.md updated:", fid)
