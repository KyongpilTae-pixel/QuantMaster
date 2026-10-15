import json,sys,re
from datetime import datetime,timezone,timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
SA=r"C:/project/quant/drive_poll/service_account.json"
SF=r"C:/project/quant/drive_poll/poll_state.json"
CF="1MvjWh0HYM0QlDHKh_uyqKrCtkUHBWlSp"
PF=r"C:/project/quant/processed_ids.json"
creds=service_account.Credentials.from_service_account_file(SA,scopes=["https://www.googleapis.com/auth/drive"])
svc=build("drive","v3",credentials=creds,cache_discovery=False)
with open(PF,encoding="utf-8-sig") as f: ids=json.load(f)
nums=[(int(re.fullmatch(r"cloud-(\d+)",str(c)).group(1)),c) for c in ids if re.fullmatch(r"cloud-(\d+)",str(c))]
lid=max(nums)[1] if nums else "unknown"
print("latest:",lid)
with open(SF,encoding="utf-8-sig") as f: st=json.load(f)
now=datetime.now(timezone.utc);nxt=now+timedelta(minutes=30)
FMT="%Y-%m-%dT%H:%MZ"
NL=chr(10)
body="---"+NL+"doc_version: 1.4"+NL+"from: local"+NL+"kind: STATE"+NL+"---"+NL+NL
body+=f"ts: {now.strftime(FMT)}"+NL+"alive: yes"+NL
body+=f"last_seen_peer_id: {lid}"+NL+"open_waits: []"+NL
body+="activity: IDLE"+NL+"poll_interval: 30min"+NL
body+=f"next_poll_eta: {nxt.strftime(FMT)}"+NL
def mm(c): return MediaInMemoryUpload(c.encode("utf-8"),mimetype="text/plain",resumable=False)
fid=st.get("state_local_file_id");uid=None
print("fid:",fid)
if fid:
    try:
        svc.files().update(fileId=fid,media_body=mm(body),supportsAllDrives=True).execute()
        print("OK",fid);uid=fid
    except Exception as e: print("fail:",e)
if not uid:
    q=f"'{CF}' in parents and name = 'STATE_local.md' and trashed = false"
    r2=svc.files().list(q=q,fields="files(id,name,modifiedTime)",orderBy="modifiedTime desc",pageSize=1,supportsAllDrives=True,includeItemsFromAllDrives=True).execute()
    fs=r2.get("files",[])
    if not fs: print("ERR");sys.exit(1)
    tid=fs[0]["id"];print("recent:",tid)
    svc.files().update(fileId=tid,media_body=mm(body),supportsAllDrives=True).execute()
    uid=tid;print("OK",tid)
st["state_local_file_id"]=uid;st["last_seen_cloud_id"]=lid;st["open_waits"]=[]
with open(SF,"w",encoding="utf-8") as f: json.dump(st,f,ensure_ascii=False,indent=2)
print("DONE",uid)