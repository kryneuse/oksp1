import sys,json,hashlib
from pathlib import Path
from app.db import connect

size=sys.argv[1] if len(sys.argv)>1 else 'small'
if size not in ('small','work'): raise SystemExit('Use: python seed.py small|work')
u,c,t=(50,5,300) if size=='small' else (3000,10,50000)
with connect() as conn:
    conn.execute(Path('schema.sql').read_text())
    conn.execute('TRUNCATE comments,tickets,categories,users RESTART IDENTITY CASCADE')
    conn.execute("INSERT INTO users SELECT i,CASE WHEN i=1 THEN 'demo' ELSE 'user_'||i END,'Пользователь '||i,(i%%5=1) FROM generate_series(1,%s) i",(u,))
    conn.execute("INSERT INTO categories SELECT i,'Категория '||i,60*i FROM generate_series(1,%s) i",(c,))
    conn.execute("INSERT INTO tickets(id,user_id,category_id,title,body,status,created_at,updated_at) SELECT i,1+(i%% %s),1+(i%% %s),'Заявка '||i,'Описание обращения '||i,CASE i%%3 WHEN 0 THEN 'new' WHEN 1 THEN 'in_progress' ELSE 'closed' END,timestamptz '2026-10-01 00:00:00+00'+(i%%10080)*interval '1 minute',timestamptz '2026-10-01 00:00:00+00'+(i%%10080)*interval '1 minute' FROM generate_series(1,%s) i",(u,c,t))
    conn.execute("INSERT INTO comments(id,ticket_id,user_id,body,created_at) SELECT (t.id-1)*3+j,t.id,CASE WHEN j=1 THEN t.user_id WHEN j=2 AND t.id%4<>0 THEN 1 ELSE 2 END,'Комментарий '||j||' к заявке '||t.id,t.created_at+(CASE WHEN j=2 THEN 30+(t.id%900) ELSE j*15 END)*interval '1 minute' FROM tickets t CROSS JOIN generate_series(1,3) j")
    for table in ('tickets','comments'):
        conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'),(SELECT max(id) FROM {table}))")
    conn.execute('ANALYZE')
    result={}
    for table in ('users','categories','tickets','comments'):
        row=conn.execute(f"SELECT count(*) n,md5(string_agg(md5(row_to_json(x)::text),'' ORDER BY id)) hash FROM {table} x").fetchone()
        result[table]=row
    print(json.dumps({'size':size,'tables':result},ensure_ascii=False))
