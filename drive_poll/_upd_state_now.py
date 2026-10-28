from datetime import datetime,timezone,timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
import json
SA=r"C:\project\quant\drive_poll\service_account.json"
ps=json.load(open(r"C:\project\quant\drive_poll\poll_state.json"))
FID=ps.get("state_local_file_id","1CLfldvMvt03iNKulOk0u0mChonXLE_5G")
ls=ps.get("last_seen_cloud_id","cloud-060")
creds=service_account.Credentials.from_service_account_file(SA,scopes=["https://www.googleapis.com/auth/drive"])
svc=build("drive","v3",credentials=creds,cache_discovery=False)
now=datetime.now(timezone.utc);nxt=now+timedelta(minutes=30)
ts=now.strftime("%Y-%m-%dT%H:%MZ");nt=nxt.strftime("%Y-%m-%dT%H:%MZ")
parts=["---","doc_version: 1.4","from: local","kind: STATE","---","","ts: "+ts,"alive: yes","last_seen_peer_id: "+ls,"open_waits: []","activity: IDLE","poll_interval: 30min","next_poll_eta: "+nt,""]
body=chr(10).join(parts)
media=MediaInMemoryUpload(body.encode("utf-8"),mimetype="text/plain",resumable=False)
r=svc.files().update(fileId=FID,media_body=media,supportsAllDrives=True).execute()
print("OK",r.get("id"),ts,"last_seen="+ls)
