"""Durable queue. Each operation owns a connection and a short transaction."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from uuid import UUID


class StorageUnavailable(RuntimeError):
    pass


class RepositoryConflict(ValueError):
    pass


class RepositoryLimit(ValueError):
    pass


class JobRepository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA busy_timeout=5000")
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError) as exc:
            if connection:
                connection.rollback()
            raise StorageUnavailable("Обязательное хранилище недоступно") from exc
        except BaseException:
            if connection:
                connection.rollback()
            raise
        finally:
            if connection:
                connection.close()

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageUnavailable("Cannot create data directory") from exc
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
                INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
                CREATE TABLE IF NOT EXISTS sessions(
                    id TEXT PRIMARY KEY, owner_client_id TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    queued_at REAL, completed_at REAL,
                    state TEXT NOT NULL, stage TEXT, page_order TEXT NOT NULL DEFAULT '[]',
                    demo INTEGER NOT NULL DEFAULT 0, error_code TEXT, error_message TEXT,
                    output_error_code TEXT, output_error_message TEXT,
                    verified_answer_sha256 TEXT, result_sha256 TEXT, package_sha256 TEXT);
                CREATE INDEX IF NOT EXISTS queue_order ON sessions(state,queued_at,created_at);
                CREATE TABLE IF NOT EXISTS pages(
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
                    byte_count INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                    format TEXT NOT NULL, PRIMARY KEY(session_id,number));
                CREATE TABLE IF NOT EXISTS paired_clients(
                    id TEXT PRIMARY KEY, credential_digest TEXT UNIQUE NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL, name TEXT NOT NULL);
            """)
            version = db.execute("SELECT version FROM schema_version").fetchone()[0]
            if version != 1:
                raise StorageUnavailable("Unsupported database schema")

    @staticmethod
    def _record(db, row):
        if row is None:
            return None
        value = dict(row)
        value["page_order"] = json.loads(value["page_order"])
        value["pages"] = {p["number"]: {"number": p["number"], "file": p["filename"],
            "sha256": p["sha256"], "bytes": p["byte_count"], "width": p["width"],
            "height": p["height"], "format": p["format"]}
            for p in db.execute("SELECT * FROM pages WHERE session_id=? ORDER BY number", (value["id"],))}
        return value

    def get(self, identifier):
        with self.connection() as db:
            return self._record(db, db.execute("SELECT * FROM sessions WHERE id=?", (str(identifier),)).fetchone())

    def all(self):
        with self.connection() as db:
            return [self._record(db, r) for r in db.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()]

    def create(self, identifier, owner, demo=False, limit=32, created_at=None):
        identifier = str(UUID(str(identifier)))
        now = time.time() if created_at is None else created_at
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM sessions WHERE id=?", (identifier,)).fetchone()
            if existing:
                if existing["owner_client_id"] != owner:
                    raise RepositoryConflict("session_owner_conflict")
                return self._record(db, existing)
            count = db.execute("SELECT count(*) FROM sessions WHERE state IN ('RECEIVING','QUEUED','RUNNING','RENDERING','PACKAGING')").fetchone()[0]
            if count >= limit:
                raise RepositoryLimit("Too many active sessions")
            db.execute("INSERT INTO sessions(id,owner_client_id,created_at,updated_at,state,demo) VALUES(?,?,?,?,'RECEIVING',?)",
                       (identifier, owner, now, now, int(demo)))
        return self.get(identifier)

    def add_page(self, identifier, page, total_limit):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM sessions WHERE id=?", (identifier,)).fetchone()
            existing = db.execute("SELECT sha256 FROM pages WHERE session_id=? AND number=?", (identifier, page["number"])).fetchone()
            if existing:
                if existing[0] == page["sha256"]:
                    return
                raise RepositoryConflict("page_content_conflict")
            if row is None or row[0] != "RECEIVING":
                raise RepositoryConflict("session_already_submitted")
            total = db.execute("SELECT COALESCE(sum(byte_count),0) FROM pages WHERE session_id=?", (identifier,)).fetchone()[0]
            if total + page["bytes"] > total_limit:
                raise RepositoryLimit("session_input_limit")
            db.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?,?)", (identifier, page["number"], page["file"],
                page["sha256"], page["bytes"], page["width"], page["height"], page["format"]))
            db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (time.time(), identifier))

    def submit(self, identifier, order, limit):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sessions WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise RepositoryConflict("session_missing")
            if row["state"] != "RECEIVING":
                if row["state"] != "ERROR" and json.loads(row["page_order"]) == order:
                    return
                raise RepositoryConflict("session_already_submitted")
            pages = [p[0] for p in db.execute("SELECT number FROM pages WHERE session_id=?", (identifier,))]
            if sorted(pages) != sorted(order):
                raise RepositoryConflict("missing_pages")
            count = db.execute("SELECT count(*) FROM sessions WHERE state IN ('QUEUED','RUNNING','RENDERING','PACKAGING')").fetchone()[0]
            if count >= limit:
                raise RepositoryLimit("queue_full")
            now = time.time()
            db.execute("UPDATE sessions SET state='QUEUED',queued_at=?,updated_at=?,page_order=? WHERE id=?",
                       (now, now, json.dumps(order), identifier))

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM sessions WHERE state IN ('QUEUED','RENDERING') ORDER BY queued_at,created_at LIMIT 1").fetchone()
            if not row:
                return None
            original = db.execute("SELECT state FROM sessions WHERE id=?", (row[0],)).fetchone()[0]
            db.execute("UPDATE sessions SET state=?,updated_at=? WHERE id=?",
                       ('RUNNING' if original == 'QUEUED' else 'PACKAGING', time.time(), row[0]))
            result = self._record(db, db.execute("SELECT * FROM sessions WHERE id=?", (row[0],)).fetchone())
            result["render_only"] = original == 'RENDERING'
            return result

    def update(self, identifier, **values):
        allowed = {"state", "stage", "error_code", "error_message", "output_error_code", "output_error_message",
                   "verified_answer_sha256", "result_sha256", "package_sha256", "completed_at", "updated_at",'page_order'}
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid session fields")
        values.setdefault("updated_at", time.time())
        if 'page_order' in values:values['page_order']=json.dumps(values['page_order'])
        with self.connection() as db:
            sql = ",".join(f"{k}=?" for k in values)
            db.execute(f"UPDATE sessions SET {sql} WHERE id=?", (*values.values(), identifier))

    def retry_render(self, identifier):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,verified_answer_sha256 FROM sessions WHERE id=?", (identifier,)).fetchone()
            if row and row[0] in {"RENDERING", "PACKAGING", "COMPLETE"}:
                return
            if row is None or row[0] != "ANSWER_READY" or not row[1]:
                raise RepositoryConflict("answer_not_ready")
            db.execute("UPDATE sessions SET state='RENDERING',updated_at=?,output_error_code=NULL,output_error_message=NULL WHERE id=?", (time.time(),identifier))

    def delete(self, identifier):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (identifier,))

    def add_client(self, identifier, digest, expires_at, name):
        with self.connection() as db:
            db.execute("INSERT INTO paired_clients VALUES(?,?,?,?,?)", (identifier, digest, time.time(), expires_at, name))

    def client(self, digest):
        with self.connection() as db:
            row = db.execute("SELECT * FROM paired_clients WHERE credential_digest=? AND expires_at>?", (digest,time.time())).fetchone()
            return dict(row) if row else None

    def clients(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,name,created_at,expires_at FROM paired_clients WHERE expires_at>?", (time.time(),))]

    def revoke_client(self, identifier):
        with self.connection() as db:
            db.execute("DELETE FROM paired_clients WHERE id=?", (identifier,))
