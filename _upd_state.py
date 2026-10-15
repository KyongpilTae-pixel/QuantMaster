import json
from datetime import datetime, timezone, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
SA = r"C:/project/quant/drive_poll/service_account.json"
SF = r"C:/project/quant/drive_poll/poll_state.json"
FID = "1MvjWh0HYM0QlDHKh_uyqKrCtkUHBWlSp"
now = datetime.now(timezone.utc)
np_ = now + timedelta(minutes=30)
creds = service_account.Credentials.from_service_account_file(SA, scopes=["https://www.googleapis.com/auth/drive"])
svc = build("drive", "v3", credentials=creds, cache_discovery=False)
q = chr(39)+FID+chr(39)+" in parents and name = "+chr(39)+"STATE_local.md"+chr(39)+" and trashed = false"
r = svc.files().list(q=q,fields="files(id,modifiedTime)",orderBy="modifiedTime desc",pageSize=50,supportsAllDrives=True,includeItemsFromAllDrives=True).execute()
fs = r.get("files",[])
print(f"Found {len(fs)} STATE_local.md files")
cid = fs[0]["id"] if fs else None
for dup in fs[1:]:
    try:
        svc.files().update(fileId=dup["id"],body=dict(trashed=True),supportsAllDrives=True).execute()
        print("Trashed",dup["id"])
    except Exception as e:
        print("Skip",dup["id"],str(e)[:60])
ts=now.strftime("%Y-%m-%dT%H:%MZ"); ne=np_.strftime("%Y-%m-%dT%H:%MZ")
parts=["---","doc_version: 1.4","from: local","kind: STATE","---","","ts: "+ts,"alive: yes","last_seen_peer_id: cloud-052","open_waits: []","activity: IDLE","poll_interval: 30min","next_poll_eta: "+ne,""]
body=chr(10).join(parts)
media=MediaInMemoryUpload(body.encode("utf-8"),mimetype="text/plain",resumable=False)
if cid:
    svc.files().update(fileId=cid,media_body=media,supportsAllDrives=True).execute()
    print("Updated",cid)
else:
    res=svc.files().create(body=dict(name="STATE_local.md",parents=[FID]),media_body=media,fields="id",supportsAllDrives=True).execute()
    cid=res["id"]; print("Created",cid)
with open(SF,encoding="utf-8-sig") as f: st=json.load(f)
st["state_local_file_id"]=cid; st["last_seen_cloud_id"]="cloud-052"; st["open_waits"]=[]; st["last_check_utc"]=now.isoformat()
with open(SF,"w",encoding="utf-8") as f: json.dump(st,f,indent=2,ensure_ascii=False)
print("Done:",cid)