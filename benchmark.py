import json,math,statistics,time,sys,os,platform
from pathlib import Path
import requests
from app.db import connect

size=sys.argv[1]; base=os.getenv('BASE_URL','http://127.0.0.1:8080')
s=requests.Session()
def login():
    r=s.post(base+'/api/login',json={'username':'demo','password':os.getenv('APP_PASSWORD','demo')}); r.raise_for_status()
def create():
    r=s.post(base+'/api/tickets',json={'title':'Замер','body':'Контрольная заявка','category_id':1});r.raise_for_status();return r.json()['id']
def counts():
    with connect() as c: return {t:c.execute(f'SELECT count(*) n FROM {t}').fetchone()['n'] for t in ('users','categories','tickets','comments')}
login();before=counts();raw={};out={}
operations=[('login','POST','/api/login',{'username':'demo','password':os.getenv('APP_PASSWORD','demo')}),('categories','GET','/api/categories',None),('list','GET','/api/tickets?page=1&size=20&status=new',None),('card','GET','/api/tickets/1',None),('summary','GET','/api/summary',None),('create','POST','/api/tickets',{'title':'Замер','body':'Контрольная заявка','category_id':1}),('comment','POST','dynamic',{'body':'Ответ при замере'}),('status','PATCH','dynamic',{'status':'in_progress'}),('logout','POST','/api/logout',None)]
for name,method,path,data in operations:
    samples=[]
    if name=='comment': comment_id=create()
    for i in range(35):
        target=path
        if name=='status': target=f'/api/tickets/{create()}/status'
        if name=='comment': target=f'/api/tickets/{comment_id}/comments'
        if name=='logout': login()
        start=time.perf_counter();r=s.request(method,base+target,json=data);elapsed=(time.perf_counter()-start)*1000
        r.raise_for_status();r.json()
        if i>=5: samples.append({'http_ms':elapsed,'db_ms':float(r.headers['X-DB-Ms']),'server_ms':float(r.headers['X-App-Total-Ms']),'queries':int(r.headers['X-Query-Count']),'status':r.status_code})
    if name=='logout': login()
    raw[name]=samples; values=sorted(x['http_ms'] for x in samples)
    out[name]={'p50':statistics.median(values),'p95':values[math.ceil(.95*len(values))-1],'max':max(values),'db_mean':statistics.mean(x['db_ms'] for x in samples),'http_mean':statistics.mean(values),'remainder_mean':statistics.mean(x['http_ms']-x['db_ms'] for x in samples),'queries':statistics.mean(x['queries'] for x in samples)}
    print(name, json.dumps(out[name]),flush=True)
result={'size':size,'repeats':30,'warmup':5,'before':before,'after':counts(),'operations':out,'samples':raw,'environment':{'python':platform.python_version(),'platform':platform.platform()}}
Path('results/'+size+'.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
