import os
import time
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, session, g, send_from_directory
from app.db import connect, DB
from app.rules import reaction, transition_allowed

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "local-coursework-change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

@app.before_request
def timing():
    g.started = time.perf_counter(); g.db_ms = 0; g.queries = 0; g.conn = None

@app.after_request
def metrics(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-DB-Ms"] = f"{g.db_ms:.6f}"
    response.headers["X-Query-Count"] = str(g.queries)
    response.headers["X-App-Total-Ms"] = f"{(time.perf_counter()-g.started)*1000:.6f}"
    return response

@app.teardown_request
def cleanup(error):
    if g.get("conn") is not None:
        if error: g.conn.rollback()
        else: g.conn.commit()
        g.conn.close()

def db():
    if g.conn is None: g.conn = connect()
    return DB(g.conn)

def auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session: return jsonify(error="unauthorized"), 401
        return fn(*args, **kwargs)
    return wrapper

def payload(required):
    data = request.get_json(silent=True)
    if not isinstance(data, dict): return None
    for key in required:
        if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > 5000: return None
    return data

def positive(value):
    if isinstance(value, (bool, float)): raise ValueError()
    number = int(value)
    if number <= 0: raise ValueError()
    return number

@app.get("/")
def home(): return send_from_directory(app.root_path, "index.html")

@app.post("/api/login")
def login():
    data = payload(["username", "password"])
    if data is None: return jsonify(error="invalid_parameters"), 422
    if data["username"] != "demo" or data["password"] != os.getenv("APP_PASSWORD", "demo"):
        return jsonify(error="invalid_credentials"), 401
    user = db().one("SELECT id,username,display_name,is_staff FROM users WHERE username=%s", ("demo",))
    if user is None: return jsonify(error="database_not_seeded"), 503
    session.clear(); session["user_id"] = user["id"]
    return jsonify(user)

@app.post("/api/logout")
@auth
def logout():
    session.clear(); return jsonify(ok=True)

@app.get("/api/categories")
@auth
def categories(): return jsonify(items=db().query("SELECT * FROM categories ORDER BY id"))

@app.get("/api/tickets")
@auth
def tickets():
    try:
        page=positive(request.args.get("page", 1)); size=positive(request.args.get("size",20))
        if size>100: raise ValueError()
        status=request.args.get("status")
        if status and status not in ("new","in_progress","closed"): raise ValueError()
        category=request.args.get("category_id")
        category=positive(category) if category else None
    except (ValueError,TypeError): return jsonify(error="invalid_parameters"),422
    clauses=[]; args=[]
    if status: clauses.append("t.status=%s"); args.append(status)
    if category: clauses.append("t.category_id=%s"); args.append(category)
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    database=db()
    total=database.one("SELECT count(*) AS n FROM tickets t"+where,args)["n"]
    rows=database.query("SELECT t.*,u.display_name,c.name AS category FROM tickets t JOIN users u ON u.id=t.user_id JOIN categories c ON c.id=t.category_id"+where+" ORDER BY t.id DESC LIMIT %s OFFSET %s",[*args,size,(page-1)*size])
    return jsonify(items=rows,total=total,page=page,size=size)

@app.get("/api/tickets/<int:ticket_id>")
@auth
def card(ticket_id):
    database=db()
    row=database.one("SELECT t.*,u.display_name,c.name AS category,c.norm_minutes FROM tickets t JOIN users u ON u.id=t.user_id JOIN categories c ON c.id=t.category_id WHERE t.id=%s",(ticket_id,))
    if row is None: return jsonify(error="not_found"),404
    comments=database.query("SELECT c.*,u.display_name,u.is_staff FROM comments c JOIN users u ON u.id=c.user_id WHERE ticket_id=%s ORDER BY c.created_at,c.id",(ticket_id,))
    first=next((c["created_at"] for c in comments if c["is_staff"]),None)
    row.update(reaction(row["created_at"],first,datetime.now(timezone.utc),row["norm_minutes"]))
    return jsonify(ticket=row,comments=comments)

@app.post("/api/tickets")
@auth
def create_ticket():
    data=payload(["title","body"])
    try: category=positive(data.get("category_id")) if data else None
    except (ValueError,TypeError): category=None
    if category is None: return jsonify(error="invalid_parameters"),422
    database=db()
    if database.one("SELECT id FROM categories WHERE id=%s",(category,)) is None: return jsonify(error="category_not_found"),404
    row=database.one("INSERT INTO tickets(user_id,category_id,title,body,status,created_at,updated_at) VALUES (%s,%s,%s,%s,'new',now(),now()) RETURNING *",(session["user_id"],category,data["title"],data["body"]))
    return jsonify(row),201

@app.post("/api/tickets/<int:ticket_id>/comments")
@auth
def comment(ticket_id):
    data=payload(["body"])
    if data is None: return jsonify(error="invalid_parameters"),422
    database=db()
    row=database.one("SELECT id,status FROM tickets WHERE id=%s FOR UPDATE",(ticket_id,))
    if row is None: return jsonify(error="not_found"),404
    if row["status"]=="closed": return jsonify(error="ticket_closed"),409
    comment=database.one("INSERT INTO comments(ticket_id,user_id,body,created_at) VALUES (%s,%s,%s,now()) RETURNING *",(ticket_id,session["user_id"],data["body"]))
    return jsonify(comment),201

@app.patch("/api/tickets/<int:ticket_id>/status")
@auth
def status(ticket_id):
    data=payload(["status"])
    if data is None or data["status"] not in ("new","in_progress","closed"): return jsonify(error="invalid_parameters"),422
    database=db()
    row=database.one("SELECT status FROM tickets WHERE id=%s FOR UPDATE",(ticket_id,))
    if row is None: return jsonify(error="not_found"),404
    if not transition_allowed(row["status"],data["status"]): return jsonify(error="invalid_transition"),409
    return jsonify(database.one("UPDATE tickets SET status=%s,updated_at=now() WHERE id=%s RETURNING *",(data["status"],ticket_id)))

@app.get("/api/summary")
@auth
def summary():
    database=db()
    # Baseline implementation: one grouped query and calculations over its full result.
    rows=database.query("SELECT t.id,t.status,t.created_at,t.category_id,c.name,c.norm_minutes,min(cm.created_at) FILTER (WHERE u.is_staff) AS first_staff FROM tickets t JOIN categories c ON c.id=t.category_id LEFT JOIN comments cm ON cm.ticket_id=t.id LEFT JOIN users u ON u.id=cm.user_id GROUP BY t.id,c.id ORDER BY t.id")
    now=datetime.now(timezone.utc); result={}
    for row in rows:
        item=result.setdefault(row["category_id"],dict(category_id=row["category_id"],name=row["name"],open=0,breached=0))
        if row["status"]!="closed":
            item["open"]+=1
            item["breached"]+=int(reaction(row["created_at"],row["first_staff"],now,row["norm_minutes"])["sla_breached"])
    for item in result.values(): item["breached_share"]=item["breached"]/item["open"] if item["open"] else 0
    return jsonify(total_tickets=len(rows),categories=list(result.values()))
