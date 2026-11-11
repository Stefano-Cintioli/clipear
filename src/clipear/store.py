"""Small SQLite job/plan store. Transactions bind approval and render snapshots."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .captions import require_caption_boundaries


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("Expected a clipear source, plan or job ID")
    return value


def pack(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, home: Path):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.home / "state.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                  id TEXT PRIMARY KEY, locator TEXT NOT NULL, path TEXT NOT NULL,
                  sha256 TEXT NOT NULL, info TEXT NOT NULL, transcript TEXT, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS plans (
                  id TEXT PRIMARY KEY, source_id TEXT NOT NULL, revision INTEGER NOT NULL,
                  document TEXT NOT NULL, digest TEXT NOT NULL, approved_digest TEXT,
                  approved_at REAL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                  progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                  request TEXT NOT NULL, result TEXT, error TEXT, pid INTEGER,
                  created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                  action TEXT NOT NULL, entity TEXT NOT NULL, detail TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def event(db, action: str, entity: str, detail: dict):
        db.execute("INSERT INTO events(at,action,entity,detail) VALUES(?,?,?,?)", (time.time(), action, entity, pack(detail)))

    def add_source(self, source_id: str, locator: str, path: str, sha256: str, info: dict):
        identifier(source_id)
        with self.connect() as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", (source_id, locator, path, sha256, pack(info), None, time.time()))
            self.event(db, "source_imported", source_id, {"sha256": sha256})

    def get_source(self, source_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (identifier(source_id),)).fetchone()
        if row is None:
            raise ValueError("Source not found")
        out = dict(row)
        out["info"] = json.loads(out["info"])
        out["transcript"] = json.loads(out["transcript"]) if out["transcript"] else None
        return out

    def set_transcript(self, source_id: str, transcript: dict):
        with self.connect() as db:
            cursor = db.execute("UPDATE sources SET transcript=? WHERE id=?", (pack(transcript), identifier(source_id)))
            if not cursor.rowcount:
                raise ValueError("Source not found")
            self.event(db, "transcribed", source_id, {"segments": len(transcript.get("segments", []))})

    def save_plan(self, source_id: str, document: dict, digest: str, plan_id: str | None = None) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if plan_id:
                row = db.execute("SELECT source_id,revision FROM plans WHERE id=?", (identifier(plan_id),)).fetchone()
                if row is None or row["source_id"] != source_id:
                    raise ValueError("Plan not found for this source")
                revision = row["revision"] + 1
                db.execute("UPDATE plans SET revision=?,document=?,digest=?,approved_digest=NULL,approved_at=NULL WHERE id=?", (revision, pack(document), digest, plan_id))
            else:
                plan_id, revision = uuid.uuid4().hex, 1
                db.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?)", (plan_id, source_id, revision, pack(document), digest, None, None, time.time()))
            self.event(db, "plan_saved", plan_id, {"digest": digest, "revision": revision})
        return self.get_plan(plan_id)

    def get_plan(self, plan_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM plans WHERE id=?", (identifier(plan_id),)).fetchone()
        if row is None:
            raise ValueError("Plan not found")
        out = dict(row)
        out["document"] = json.loads(out["document"])
        out["approved"] = out["approved_digest"] == out["digest"]
        return out

    def approve(self, plan_id: str, digest: str, revision: int):
        """Trusted human CLI/review path only; never exposed as an MCP tool."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM plans WHERE id=? AND digest=? AND revision=?", (identifier(plan_id), digest, revision)).fetchone()
            if row is None:
                raise PermissionError("Plan changed during review; review the current revision again")
            require_caption_boundaries(json.loads(row["document"]))
            cursor = db.execute("UPDATE plans SET approved_digest=?,approved_at=? WHERE id=? AND digest=? AND revision=?", (digest, time.time(), identifier(plan_id), digest, revision))
            if cursor.rowcount != 1:
                raise PermissionError("Plan changed during review; review the current revision again")
            self.event(db, "human_approved", plan_id, {"digest": digest, "revision": revision})

    def new_job(self, kind: str, request: dict) -> str:
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            self._insert_job(db, job_id, kind, request)
        return job_id

    def _insert_job(self, db, job_id: str, kind: str, request: dict):
        now = time.time()
        db.execute("INSERT INTO jobs(id,kind,status,request,created_at,updated_at) VALUES(?,?,?,?,?,?)", (job_id, kind, "queued", pack(request), now, now))
        self.event(db, "job_queued", job_id, {"kind": kind})

    def queue_render(self, plan_id: str, source: dict) -> str:
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM plans WHERE id=?", (identifier(plan_id),)).fetchone()
            if row is None:
                raise ValueError("Plan not found")
            if row["approved_digest"] != row["digest"]:
                raise PermissionError("Human approval required for this exact plan revision")
            plan = json.loads(row["document"])
            require_caption_boundaries(plan)
            if plan["source_sha256"] != source["sha256"]:
                raise PermissionError("Source changed; create and approve a new plan")
            self._insert_job(db, job_id, "render", {"plan_id": plan_id, "revision": row["revision"], "digest": row["digest"], "plan": plan, "source": source})
        return job_id

    def claim_job(self, job_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("UPDATE jobs SET status='running',pid=?,updated_at=? WHERE id=? AND status='queued'", (os.getpid(), time.time(), identifier(job_id)))
            if cursor.rowcount:
                self.event(db, "job_claimed", job_id, {"pid": os.getpid()})
            return cursor.rowcount == 1

    def job_request(self, job_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT request FROM jobs WHERE id=?", (identifier(job_id),)).fetchone()
        if row is None:
            raise ValueError("Job not found")
        return json.loads(row["request"])

    def get_job(self, job_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT id,kind,status,progress,message,result,error,pid,created_at,updated_at FROM jobs WHERE id=?", (identifier(job_id),)).fetchone()
        if row is None:
            raise ValueError("Job not found")
        out = dict(row)
        out["result"] = json.loads(out["result"]) if out["result"] else None
        return out

    def progress(self, job_id: str, fraction: float, message: str):
        with self.connect() as db:
            db.execute("UPDATE jobs SET progress=?,message=?,updated_at=? WHERE id=? AND status='running'", (max(0, min(1, fraction)), message, time.time(), identifier(job_id)))

    def finish_job(self, job_id: str, result: dict | None = None, error: str | None = None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?,progress=?,result=?,error=?,updated_at=? WHERE id=?", ("failed" if error else "succeeded", 0 if error else 1, pack(result) if result is not None else None, error, time.time(), identifier(job_id)))
            self.event(db, "job_failed" if error else "job_succeeded", job_id, {"error": error} if error else {})

    def worker_exited(self, job_id: str, returncode: int, log_path: Path):
        """A live parent observed exit; preserve any result already recorded by the worker."""
        error = f"Worker exited with return code {returncode} before recording a terminal job status. See log: {log_path}"
        with self.connect() as db:
            cursor = db.execute("UPDATE jobs SET status='failed',progress=0,error=?,updated_at=? WHERE id=? AND status IN ('queued','running')", (error, time.time(), identifier(job_id)))
            if cursor.rowcount:
                self.event(db, "job_failed", job_id, {"error": error, "returncode": returncode, "log": str(log_path)})
