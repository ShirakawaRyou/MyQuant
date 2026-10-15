"""Server-side password hashes, opaque sessions and persistent login throttling."""

import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager

from .store import connect

ITERATIONS = 600_000


class Auth:
    def __init__(self, path):
        self.path = path
        with self.connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,salt TEXT NOT NULL,hash TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,username TEXT NOT NULL,csrf TEXT NOT NULL,expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS attempts(address TEXT NOT NULL,at REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS attempt_address ON attempts(address,at);
            """)
        path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def set_password(self, username, password):
        if not username or len(username) > 64 or len(password) < 14:
            raise ValueError("用户名长度为1–64；密码至少14个字符")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
        with self.connection() as db:
            db.execute("INSERT INTO users VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET salt=excluded.salt,hash=excluded.hash",
                       (username, salt, digest))
            db.execute("DELETE FROM sessions WHERE username=?", (username,))

    def login(self, username, password, address):
        now = time.time()
        with self.connection() as db:
            db.execute("DELETE FROM attempts WHERE at<?", (now - 900,))
            if db.execute("SELECT COUNT(*) FROM attempts WHERE address=? AND at>?", (address, now - 300)).fetchone()[0] >= 5:
                return None, True
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            salt = bytes.fromhex(user["salt"]) if user else b"\0" * 16
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS).hex()
            expected = user["hash"] if user else "0" * 64
            if not hmac.compare_digest(actual, expected) or not user:
                db.execute("INSERT INTO attempts VALUES(?,?)", (address, now))
                return None, False
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), username, csrf, now + 8 * 3600))
            return token, False

    def session(self, token):
        if not token or len(token) > 100:
            return None
        with self.connection() as db:
            row = db.execute("SELECT username,csrf,expires FROM sessions WHERE token_hash=? AND expires>?",
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
