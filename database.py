"""SQLite persistence. Each operation owns one connection and transaction."""
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY,username TEXT NOT NULL COLLATE NOCASE UNIQUE,email TEXT NOT NULL COLLATE NOCASE UNIQUE,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('MEMBER','LIBRARIAN','ADMINISTRATOR')),status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','INACTIVE')),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY,account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),full_name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '',address TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','INACTIVE')));
CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY,account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),full_name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS system_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_by INTEGER REFERENCES staff(id),updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS publishers(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS authors(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS books(id INTEGER PRIMARY KEY,isbn TEXT NOT NULL UNIQUE,title TEXT NOT NULL,category_id INTEGER NOT NULL REFERENCES categories(id),publisher_id INTEGER REFERENCES publishers(id),publication_year INTEGER NOT NULL,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','WITHDRAWN')));
CREATE TABLE IF NOT EXISTS book_authors(book_id INTEGER REFERENCES books(id),author_id INTEGER REFERENCES authors(id),PRIMARY KEY(book_id,author_id));
CREATE TABLE IF NOT EXISTS book_copies(id INTEGER PRIMARY KEY,book_id INTEGER NOT NULL REFERENCES books(id),barcode TEXT NOT NULL UNIQUE,location TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK(status IN ('AVAILABLE','ON_LOAN','HELD','DAMAGED','LOST','WITHDRAWN')));
CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY,member_id INTEGER NOT NULL REFERENCES members(id),staff_id INTEGER NOT NULL REFERENCES staff(id),loan_date TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED')));
CREATE TABLE IF NOT EXISTS loan_details(id INTEGER PRIMARY KEY,loan_id INTEGER NOT NULL REFERENCES loans(id),copy_id INTEGER NOT NULL REFERENCES book_copies(id),due_date TEXT NOT NULL,return_date TEXT,renewal_count INTEGER NOT NULL DEFAULT 0,policy_snapshot TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','RETURNED')));
CREATE UNIQUE INDEX IF NOT EXISTS one_open_copy ON loan_details(copy_id) WHERE status='OPEN';
CREATE TABLE IF NOT EXISTS reservations(id INTEGER PRIMARY KEY,member_id INTEGER NOT NULL REFERENCES members(id),book_id INTEGER NOT NULL REFERENCES books(id),created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'WAITING' CHECK(status IN ('WAITING','READY','FULFILLED','CANCELLED','EXPIRED')),copy_id INTEGER REFERENCES book_copies(id),expires_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_reservation ON reservations(member_id,book_id) WHERE status IN ('WAITING','READY');
CREATE UNIQUE INDEX IF NOT EXISTS one_hold_per_copy ON reservations(copy_id) WHERE status='READY';
CREATE TABLE IF NOT EXISTS fines(id INTEGER PRIMARY KEY,detail_id INTEGER NOT NULL UNIQUE REFERENCES loan_details(id),amount INTEGER NOT NULL CHECK(amount>0),overdue_days INTEGER NOT NULL,breakdown TEXT NOT NULL,issued_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fine_payments(id INTEGER PRIMARY KEY,fine_id INTEGER NOT NULL REFERENCES fines(id),amount INTEGER NOT NULL CHECK(amount>0),method TEXT NOT NULL CHECK(method IN ('CASH','TRANSFER')),staff_id INTEGER NOT NULL REFERENCES staff(id),paid_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,account_id INTEGER NOT NULL REFERENCES accounts(id),last_active TEXT NOT NULL,csrf TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests(actor INTEGER NOT NULL REFERENCES accounts(id),kind TEXT NOT NULL,request_key TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(actor,kind,request_key));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES accounts(id),action TEXT NOT NULL,entity TEXT NOT NULL,at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS loan_member ON loans(member_id);
CREATE INDEX IF NOT EXISTS reservation_queue ON reservations(book_id,status,id);
CREATE INDEX IF NOT EXISTS books_title ON books(title);
'''

class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as c:
            c.executescript(SCHEMA)
            c.execute('PRAGMA journal_mode=WAL')

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=15000')
        return c

    @contextmanager
    def transaction(self, write=True):
        c = self.connect()
        try:
            c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
