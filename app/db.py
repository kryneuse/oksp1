import os
import time
import psycopg
from psycopg.rows import dict_row
from flask import g

SCHEMA = "nikita_zozulenko"
def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                          options=f"-c search_path={SCHEMA},public")

class DB:
    def __init__(self, conn):
        self.conn = conn
    def query(self, sql, params=()):
        start = time.perf_counter()
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []
        finally:
            g.db_ms += (time.perf_counter() - start) * 1000
            g.queries += 1
    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None
