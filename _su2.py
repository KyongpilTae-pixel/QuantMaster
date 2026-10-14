import json
from datetime import datetime,timezone,timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
SA=r"C:/project/quant/drive_poll/service_account.json"
CID="15iDkP6coeGyteCVxBD42UCdRLPJZHivi"
DUPS=["1Fp4rh4XA7dOnmq1cQmwuVgswp4GjFEvq","11Jzd438YDFiMFKcKEZ6mM8RbWv7XH5WM"]
PS=r"C:/project/quant/drive_poll/poll_state.json"
cr=service_account.Credentials.from_service_account_file(SA,scopes=["https://www.googleapis.com/auth/drive"])
sv=build("drive","v3",credentials=cr,cache_discovery=False)
now=datetime.now(timezone.utc)
nxt=now+timedelta(minutes=30)
ts=now.strftime("%Y-%m-%dT%H:%MZ")
ns=nxt.strftime("%Y-%m-%dT%H:%MZ")
parts=["---","doc_version: 1.4","from: local","kind: STATE","---","","last_seen_peer_id: cloud-052","open_waits: []","activity: IDLE","ts: "+ts,"poll_interval: 30min","next_poll_eta: "+ns,""]
body=chr(10).join(parts)
md=MediaInMemoryUpload(body.encode(),mimetype="text/plain",resumable=False)
r=sv.files().update(fileId=CID,media_body=md,supportsAllDrives=True).execute()
print("STATE:",r.get("id"),r.get("modifiedTime"))
for f in DUPS:
 try: sv.files().update(fileId=f,body={"trashed":True},supportsAllDrives=True).execute(); print("trashed:",f)
 except Exception as e: print("warn:",f,str(e)[:60])
with open(PS,encoding="utf-8-sig") as fh: p=json.load(fh)
p["last_seen_cloud_id"]="cloud-052"
p["state_local_file_id"]=CID
p["last_check_utc"]=now.isoformat()
with open(PS,"w",encoding="utf-8") as fh: json.dump(p,fh,ensure_ascii=False,indent=2)
print("poll_state OK")
print("DONE")
