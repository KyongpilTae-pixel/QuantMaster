from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
import datetime

SA_FILE = r"C:\project\quant\drive_poll\service_account.json"
FILE_ID = "1eNoLvDIHqsbNbZzalHMyrevbFy7wMNEy"

creds = service_account.Credentials.from_service_account_file(SA_FILE, scopes=["https://www.googleapis.com/auth/drive"])
service = build("drive", "v3", credentials=creds)

now_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
next_poll = (datetime.datetime.utcnow() + datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%MZ")
parts = ["last_seen_peer_id: cloud-060", "open_waits: []", "activity: IDLE", "ts: " + now_utc, "poll_interval: 30min", "next_poll_eta: " + next_poll, ""]
nl = chr(10)
content = nl.join(parts)

media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain", resumable=False)
result = service.files().update(fileId=FILE_ID, media_body=media).execute()
print("Updated:", result.get("id"), result.get("modifiedTime"))