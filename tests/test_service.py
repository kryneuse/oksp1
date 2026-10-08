from datetime import datetime,timedelta,timezone
import pytest
from app.rules import reaction,transition_allowed
from app.server import app
from app.db import connect

NOW=datetime(2026,10,8,tzinfo=timezone.utc)
@pytest.mark.parametrize('old,new,expected', [('new','in_progress',True),('in_progress','closed',True),('new','closed',False),('closed','in_progress',False)])
def test_status_rules(old,new,expected): assert transition_allowed(old,new)==expected
@pytest.mark.parametrize('minutes,first,breached',[(60,True,False),(61,True,True),(61,False,True),(59,False,False)])
def test_sla_boundary(minutes,first,breached):
    result=reaction(NOW-timedelta(minutes=minutes), NOW if first else None,NOW,60)
    assert result['sla_breached']==breached
    assert result['reaction_seconds']==(minutes*60 if first else None)

@pytest.fixture
def client(monkeypatch):
    conn=connect()
    class Transaction:
        def cursor(self): return conn.cursor()
        def commit(self): pass
        def rollback(self): conn.rollback()
        def close(self): pass
    monkeypatch.setattr('app.server.connect', lambda:Transaction())
    app.config['TESTING']=True
    with app.test_client() as client:
        yield client
    conn.rollback();conn.close()
@pytest.fixture
def authorized(client):
    assert client.post('/api/login',json={'username':'demo','password':'demo'}).status_code==200
    return client
@pytest.mark.parametrize('method,path,data',[('get','/api/categories',None),('get','/api/tickets',None),('get','/api/tickets/1',None),('get','/api/summary',None),('post','/api/tickets',{}),('post','/api/tickets/1/comments',{}),('patch','/api/tickets/1/status',{}),('post','/api/logout',None)])
def test_requires_auth(client,method,path,data): assert getattr(client,method)(path,json=data).status_code==401

def test_wrong_login(client): assert client.post('/api/login',json={'username':'demo','password':'wrong'}).status_code==401
@pytest.mark.parametrize('query',['page=0','size=101','status=other','category_id=abc'])
def test_invalid_list(authorized,query): assert authorized.get('/api/tickets?'+query).status_code==422

def test_list_and_filter(authorized):
    data=authorized.get('/api/tickets?size=7&status=new').json
    assert len(data['items'])==7
    assert all(x['status']=='new' for x in data['items'])
    assert data['total']>=7

def test_card(authorized):
    data=authorized.get('/api/tickets/1').json
    assert len(data['comments'])==3
    assert {'category','norm_minutes','reaction_seconds','sla_breached'}<=data['ticket'].keys()
    staff=[x for x in data['comments'] if x['is_staff']]
    assert staff

def test_not_found(authorized): assert authorized.get('/api/tickets/999999999').status_code==404

def test_lifecycle(authorized):
    response=authorized.post('/api/tickets',json={'title':'Проверка','body':'Описание','category_id':1})
    assert response.status_code==201
    tid=response.json['id']
    assert authorized.patch(f'/api/tickets/{tid}/status',json={'status':'closed'}).status_code==409
    assert authorized.patch(f'/api/tickets/{tid}/status',json={'status':'in_progress'}).status_code==200
    assert authorized.post(f'/api/tickets/{tid}/comments',json={'body':'Ответ'}).status_code==201
    assert authorized.get(f'/api/tickets/{tid}').json['ticket']['reaction_seconds'] is not None
    assert authorized.patch(f'/api/tickets/{tid}/status',json={'status':'closed'}).status_code==200
    assert authorized.post(f'/api/tickets/{tid}/comments',json={'body':'Поздний ответ'}).status_code==409

def test_invalid_create(authorized): assert authorized.post('/api/tickets',json={'title':'','body':'x','category_id':1}).status_code==422

def test_missing_category(authorized): assert authorized.post('/api/tickets',json={'title':'x','body':'x','category_id':999999}).status_code==404

def test_summary(authorized):
    data=authorized.get('/api/summary').json
    assert data['total_tickets']>=300
    assert sum(x['open'] for x in data['categories'])>0
    assert all(0<=x['breached_share']<=1 for x in data['categories'])

def test_logout(authorized):
    assert authorized.post('/api/logout').status_code==200
    assert authorized.get('/api/tickets').status_code==401
