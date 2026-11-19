"""Nguồn nghiệp vụ của chương trình quản lý thư viện.

1. Các lớp đối tượng: Account, Member, Staff, Book, Loan, Fine...
2. LibraryService: kiểm tra quyền và xử lý nghiệp vụ.
3. seed_figma_demo: tạo dữ liệu minh họa khi chương trình chạy lần đầu.

Giao diện và HTTP được xử lý trong app.py; SQLite nằm trong database.py.
"""


# 1. CÁC LỚP ĐỐI TƯỢNG

"""Small domain objects used by the service layer (no HTTP or SQL here)."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class LoanDetail:
    due_date: datetime
    return_date: datetime | None = None

    def overdue_days(self, now: datetime) -> int:
        """A started late day counts as one day, consistent with checkout policy."""
        seconds = ((self.return_date or now) - self.due_date).total_seconds()
        return max(0, (int(seconds) + 86399) // 86400)

    def is_overdue(self, now: datetime) -> bool:
        return self.return_date is None and now > self.due_date


@dataclass(frozen=True)
class Fine:
    amount: int
    paid: int = 0

    @property
    def balance(self) -> int:
        return self.amount - self.paid

    def pay(self, amount: int):
        if type(amount) is not int or not 0 < amount <= self.balance:
            raise ValueError('Số tiền phải là số nguyên dương và không vượt dư nợ.')
        return Fine(self.amount, self.paid + amount)


@dataclass(frozen=True)
class BookCopy:
    barcode: str
    status: str

    def can_issue(self) -> bool:
        return self.status in ('AVAILABLE', 'HELD')

    def mark_borrowed(self):
        if not self.can_issue():
            raise ValueError('Bản sao không sẵn sàng.')
        return BookCopy(self.barcode, 'ON_LOAN')

    def mark_available(self):
        return BookCopy(self.barcode, 'AVAILABLE')


@dataclass
class Account:
    id: int = 0
    username: str = ''
    email: str = ''
    role: str = 'MEMBER'
    status: str = 'ACTIVE'

    def can_login(self) -> bool:
        return self.status == 'ACTIVE'


@dataclass
class Member(Account):
    account_id: int = 0
    full_name: str = ''
    phone: str = ''
    address: str = ''
    member_status: str = 'ACTIVE'
    open_count: int = 0
    limit: int = 5
    overdue_count: int = 0
    balance: int = 0

    def borrowing_reasons(self, count: int, allowed_debt: int = 0) -> list[str]:
        reasons = []
        if self.member_status != 'ACTIVE' or self.status != 'ACTIVE':
            reasons.append('INACTIVE_MEMBER')
        if self.overdue_count:
            reasons.append('OVERDUE_UNRETURNED')
        if self.open_count + count > self.limit:
            reasons.append('BORROWING_LIMIT_EXCEEDED')
        if self.balance > allowed_debt:
            reasons.append('OUTSTANDING_FINE_BLOCK')
        return reasons

    def can_borrow(self, count: int = 1, allowed_debt: int = 0) -> bool:
        return not self.borrowing_reasons(count, allowed_debt)


@dataclass
class Staff(Account):
    account_id: int = 0
    full_name: str = ''
    phone: str = ''
    hire_date: str = ''


@dataclass
class Author:
    id: int = 0
    name: str = ''


@dataclass
class Publisher:
    id: int = 0
    name: str = ''
    phone: str = ''


@dataclass
class Category:
    id: int = 0
    name: str = ''
    description: str = ''


@dataclass
class Book:
    id: int = 0
    isbn: str = ''
    title: str = ''
    publication_year: int = 2024
    description: str = ''
    status: str = 'ACTIVE'

    def count_available(self, copies: list[BookCopy]) -> int:
        return sum(copy.status == 'AVAILABLE' for copy in copies)


@dataclass
class Loan:
    id: int = 0
    member_id: int = 0
    staff_id: int = 0
    loan_date: str = ''
    status: str = 'OPEN'
    copies: list[BookCopy] = field(default_factory=list)

    def add_item(self, copy: BookCopy):
        if any(item.barcode == copy.barcode for item in self.copies):
            raise ValueError('Bản sao đã có trong phiếu.')
        self.copies.append(copy)


@dataclass
class Reservation:
    id: int = 0
    member_id: int = 0
    book_id: int = 0
    reservation_date: str = ''
    expiry_date: str | None = None
    queue_position: int = 0
    status: str = 'WAITING'

    def cancel(self):
        if self.status not in ('WAITING', 'READY'):
            raise ValueError('Yêu cầu không còn hoạt động.')
        self.status = 'CANCELLED'

    def fulfill(self):
        if self.status != 'READY':
            raise ValueError('Chưa có bản sao được giữ cho yêu cầu này.')
        self.status = 'FULFILLED'


@dataclass
class FinePayment:
    id: int = 0
    fine_id: int = 0
    amount: int = 0
    payment_date: str = ''
    payment_method: str = 'CASH'


@dataclass
class SystemSetting:
    key: str = ''
    value: str = ''
    description: str = ''

    def get(self, key: str) -> str:
        if key != self.key:
            raise KeyError(key)
        return self.value


# 2. XỬ LÝ NGHIỆP VỤ

"""Business services: all permissions, ownership and consistency live here."""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

from database import Database

DEFAULT_POLICY = dict(max_active_copies=5, loan_days=14, renewal_days=7,
                      max_renewals=1, daily_fine_rate=1000, fine_block_threshold=0,
                      band1_days=7, band2_days=30, multiplier2=2, multiplier3=3,
                      pickup_hours=48)
STAFF = ('LIBRARIAN', 'ADMINISTRATOR')

class RuleError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status

def require(condition, code, message, status=400):
    if not condition:
        raise RuleError(code, message, status)

def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return 'pbkdf2_sha256$600000$' + salt.hex() + '$' + digest.hex()

def password_matches(password, encoded):
    try:
        _, iterations, salt, digest = encoded.split('$')
        got = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(got.hex(), digest)
    except (ValueError, TypeError):
        return False

def integer(value, name, minimum=0, maximum=10**9):
    require(type(value) is int and minimum <= value <= maximum, 'INVALID_INPUT', f'{name}: cần số nguyên từ {minimum} đến {maximum}.')
    return value

def text(value, name, maximum=255):
    require(isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= maximum,
            'INVALID_INPUT', f'{name}: bắt buộc, tối đa {maximum} ký tự.')
    return value.strip()

def fine_amount(days, policy):
    """Integer VND; each day belongs to exactly one progressive band."""
    d = max(0, days)
    a = min(d, policy['band1_days'])
    b = min(max(d-policy['band1_days'], 0), policy['band2_days']-policy['band1_days'])
    c = max(d-policy['band2_days'], 0)
    amounts = [a*policy['daily_fine_rate'], b*policy['daily_fine_rate']*policy['multiplier2'],
               c*policy['daily_fine_rate']*policy['multiplier3']]
    return sum(amounts), dict(days=[a,b,c], amounts=amounts)

class LibraryService:
    def __init__(self, path, clock=None):
        self.db = Database(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.failures, self.lock = {}, threading.Lock()
        self.dummy_hash = password_hash('not-an-account-password')
        with self.db.transaction() as c:
            for key, value in DEFAULT_POLICY.items():
                c.execute('INSERT OR IGNORE INTO system_settings(key,value,updated_at) VALUES(?,?,?)', (key,str(value),self.now()))

    def now(self):
        return self.clock().astimezone(timezone.utc).isoformat(timespec='seconds')

    def _policy(self, c):
        return {r['key']: int(r['value']) for r in c.execute('SELECT key,value FROM system_settings')}

    def _audit(self, c, actor, action, entity):
        c.execute('INSERT INTO audit(actor,action,entity,at) VALUES(?,?,?,?)', (actor['id'] if actor else None,action,str(entity),self.now()))

    def _actor(self, c, token, roles=None, touch=True):
        row = c.execute('SELECT a.*,s.last_active,s.csrf FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE token_hash=?',
                        (hashlib.sha256((token or '').encode()).hexdigest(),)).fetchone()
        require(row is not None and row['status']=='ACTIVE' and
                self.clock()-datetime.fromisoformat(row['last_active']) < timedelta(minutes=15),
                'SESSION_EXPIRED', 'Phiên đã hết hạn. Vui lòng đăng nhập.', 401)
        require(roles is None or row['role'] in roles, 'FORBIDDEN', 'Bạn không có quyền thực hiện chức năng này.', 403)
        if touch:
            c.execute('UPDATE sessions SET last_active=? WHERE token_hash=?', (self.now(),hashlib.sha256(token.encode()).hexdigest()))
        return dict(row)

    def _member(self, c, member_id):
        row = c.execute('SELECT m.*,a.status account_status FROM members m JOIN accounts a ON a.id=m.account_id WHERE m.id=?', (member_id,)).fetchone()
        require(row is not None, 'NOT_FOUND', 'Không tìm thấy độc giả.', 404)
        return dict(row)

    def _own_member(self, c, actor, requested=None):
        if actor['role']=='MEMBER':
            member_id = c.execute('SELECT id FROM members WHERE account_id=?',(actor['id'],)).fetchone()['id']
            require(requested is None or requested==member_id,'FORBIDDEN','Chỉ được xem dữ liệu của chính mình.',403)
            return member_id
        require(actor['role'] in STAFF and requested is not None,'INVALID_INPUT','Cần chọn độc giả.')
        self._member(c, requested)
        return requested

    def _staff_id(self, c, actor):
        return c.execute('SELECT id FROM staff WHERE account_id=?',(actor['id'],)).fetchone()['id']

    def _identity(self, data):
        username=text(data.get('username'),'Tên đăng nhập',50)
        require(bool(re.fullmatch(r'[A-Za-z0-9_.-]{3,50}',username)),'INVALID_INPUT','Tên đăng nhập 3–50 ký tự chữ, số, _, . hoặc -.')
        email=text(data.get('email'),'Email',100).lower()
        require(bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email)),'INVALID_INPUT','Email không hợp lệ.')
        name=text(data.get('full_name'),'Họ tên',100)
        pw=data.get('password','')
        require(isinstance(pw,str) and 8<=len(pw)<=256,'INVALID_INPUT','Mật khẩu phải dài 8–256 ký tự.')
        return username,email,name,pw

    def _create_account(self, c, data, role='MEMBER'):
        username,email,name,pw=self._identity(data)
        try:
            account=c.execute('INSERT INTO accounts(username,email,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                              (username,email,password_hash(pw),role,self.now())).lastrowid
            table='members' if role=='MEMBER' else 'staff'
            profile=c.execute(f'INSERT INTO {table}(account_id,full_name) VALUES(?,?)',(account,name)).lastrowid
            return dict(account_id=account,profile_id=profile)
        except sqlite3.IntegrityError as e:
            raise RuleError('DUPLICATE_IDENTITY','Tên đăng nhập hoặc email đã tồn tại.',409) from e

    def register(self, data):
        require(data.get('password')==data.get('confirmation'),'INVALID_INPUT','Mật khẩu xác nhận không khớp.')
        with self.db.transaction() as c:
            return self._create_account(c,data)

    def login(self, identity, password, client='local'):
        identity = text(identity,'Tài khoản',100).lower()
        require(isinstance(password,str) and len(password)<=256,'AUTH_FAILED','Thông tin đăng nhập không hợp lệ.',401)
        key=(client,identity)
        with self.lock:
            previous=[t for t in self.failures.get(key,[]) if self.clock()-t<timedelta(minutes=5)]
            self.failures[key]=previous
            require(len(previous)<5,'RATE_LIMIT','Thử lại sau 5 phút.',429)
        with self.db.transaction() as c:
            a=c.execute('SELECT * FROM accounts WHERE username=? OR email=?',(identity,identity)).fetchone()
            valid=password_matches(password,a['password_hash'] if a else self.dummy_hash)
            if not a or not valid or not Account(status=a['status']).can_login():
                with self.lock:
                    self.failures.setdefault(key,[]).append(self.clock())
                raise RuleError('AUTH_FAILED','Thông tin đăng nhập không hợp lệ.',401)
            token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24)
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),a['id'],self.now(),csrf))
            with self.lock:
                self.failures.pop(key,None)
            return dict(token=token,csrf=csrf,role=a['role'])

    def me(self, token, touch=True):
        with self.db.transaction() as c:
            a=self._actor(c,token,touch=touch)
            table='members' if a['role']=='MEMBER' else 'staff'
            profile=dict(c.execute(f'SELECT * FROM {table} WHERE account_id=?',(a['id'],)).fetchone())
            return dict(id=a['id'],username=a['username'],email=a['email'],role=a['role'],csrf=a['csrf'],profile=profile)

    def logout(self, token):
        with self.db.transaction() as c:
            c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256((token or '').encode()).hexdigest(),))
        return dict(signed_out=True)

    def update_profile(self, token, data):
        with self.db.transaction() as c:
            a=self._actor(c,token)
            name=text(data.get('full_name'),'Họ tên',100)
            phone=str(data.get('phone','')).strip()
            require(not phone or bool(re.fullmatch(r'[+0-9 ()-]{6,20}',phone)),'INVALID_INPUT','Số điện thoại không hợp lệ.')
            table='members' if a['role']=='MEMBER' else 'staff'
            c.execute(f'UPDATE {table} SET full_name=?,phone=? WHERE account_id=?',(name,phone,a['id']))
            if table=='members':
                address=str(data.get('address','')).strip()
                require(len(address)<=255,'INVALID_INPUT','Địa chỉ quá dài.')
                c.execute('UPDATE members SET address=? WHERE account_id=?',(address,a['id']))
        return dict(saved=True)

    def change_password(self, token, old, new):
        with self.db.transaction() as c:
            a=self._actor(c,token)
            require(isinstance(old,str) and password_matches(old,a['password_hash']),'AUTH_FAILED','Mật khẩu hiện tại không đúng.',401)
            require(isinstance(new,str) and 8<=len(new)<=256,'INVALID_INPUT','Mật khẩu mới phải dài 8–256 ký tự.')
            c.execute('UPDATE accounts SET password_hash=? WHERE id=?',(password_hash(new),a['id']))
            c.execute('DELETE FROM sessions WHERE account_id=?',(a['id'],))
            self._audit(c,a,'CHANGE_PASSWORD',a['id'])
        return dict(signed_out=True)

    def settings(self, token, changes=None):
        with self.db.transaction() as c:
            a=self._actor(c,token,STAFF if changes is None else ('ADMINISTRATOR',))
            p=self._policy(c)
            if changes is not None:
                require(isinstance(changes,dict) and set(changes)<=set(DEFAULT_POLICY),'INVALID_INPUT','Tên quy định không hợp lệ.')
                for k,v in changes.items():
                    integer(v,k,0 if k in ('daily_fine_rate','fine_block_threshold','max_renewals') else 1,10000000)
                p.update(changes)
                require(p['band1_days']<p['band2_days'] and 1<p['multiplier2']<=p['multiplier3'],'INVALID_POLICY','Cần mốc 1 < mốc 2 và 1 < hệ số 2 ≤ hệ số 3.')
                for k,v in changes.items():
                    c.execute('UPDATE system_settings SET value=?,updated_by=?,updated_at=? WHERE key=?',(str(v),self._staff_id(c,a),self.now(),k))
                self._audit(c,a,'UPDATE_POLICY',json.dumps(changes))
            return p

    def catalog(self, query='', category=None, page=1, page_size=20, availability='all'):
        integer(page,'Trang',1,1000000);integer(page_size,'Kích thước trang',1,100)
        require(isinstance(query,str) and len(query)<=200,'INVALID_INPUT','Từ khóa quá dài.')
        require(availability in ('all','available','borrowed'), 'INVALID_INPUT', 'Bộ lọc sách không hợp lệ.')
        with self.db.transaction(False) as c:
            where="b.status='ACTIVE' AND (b.title LIKE ? OR b.isbn LIKE ? OR EXISTS(SELECT 1 FROM book_authors ba JOIN authors au ON au.id=ba.author_id WHERE ba.book_id=b.id AND au.name LIKE ?))"
            params=['%'+query+'%']*3
            if availability != 'all':
                where += ' AND EXISTS(SELECT 1 FROM book_copies selected WHERE selected.book_id=b.id AND selected.status=?)'
                params.append('AVAILABLE' if availability == 'available' else 'ON_LOAN')
            if category is not None:
                integer(category,'Thể loại',1);where+=' AND b.category_id=?';params.append(category)
            count=c.execute('SELECT COUNT(*) n FROM books b WHERE '+where,params).fetchone()['n']
            rows=c.execute('SELECT b.*,ca.name category,p.name publisher,(SELECT group_concat(au.name, ", ") FROM authors au JOIN book_authors ba ON ba.author_id=au.id WHERE ba.book_id=b.id) authors,(SELECT COUNT(*) FROM book_copies bc WHERE bc.book_id=b.id AND bc.status="AVAILABLE") available,(SELECT COUNT(*) FROM book_copies bc WHERE bc.book_id=b.id) total FROM books b JOIN categories ca ON ca.id=b.category_id LEFT JOIN publishers p ON p.id=b.publisher_id WHERE '+where+' ORDER BY b.id LIMIT ? OFFSET ?',params+[page_size,(page-1)*page_size]).fetchall()
            return dict(items=[dict(r) for r in rows],total=count,page=page)

    def book(self, book_id):
        integer(book_id,'Mã sách',1)
        with self.db.transaction(False) as c:
            r=c.execute('SELECT b.*,ca.name category,p.name publisher,(SELECT group_concat(au.name, ", ") FROM authors au JOIN book_authors ba ON ba.author_id=au.id WHERE ba.book_id=b.id) authors FROM books b JOIN categories ca ON ca.id=b.category_id LEFT JOIN publishers p ON p.id=b.publisher_id WHERE b.id=?',(book_id,)).fetchone()
            require(r is not None,'NOT_FOUND','Không tìm thấy sách.',404)
            copies=[dict(x) for x in c.execute('SELECT id,barcode,location,status FROM book_copies WHERE book_id=? ORDER BY id',(book_id,))]
            return dict(book=dict(r),copies=copies)

    def preview_return(self,token,barcode):
        with self.db.transaction() as c:
            self._actor(c,token,STAFF)
            d=c.execute("SELECT d.*,b.title,m.full_name,bc.barcode FROM loan_details d JOIN loans l ON l.id=d.loan_id JOIN members m ON m.id=l.member_id JOIN book_copies bc ON bc.id=d.copy_id JOIN books b ON b.id=bc.book_id WHERE bc.barcode=? AND d.status='OPEN'",(barcode,)).fetchone()
            require(d is not None,'NOT_ON_LOAN','Không tìm thấy bản sao đang mượn.',404)
            days=max(0,(int((self.clock()-datetime.fromisoformat(d['due_date'])).total_seconds())+86399)//86400)
            amount,breakdown=fine_amount(days,json.loads(d['policy_snapshot']))
            return dict(detail_id=d['id'],title=d['title'],barcode=barcode,full_name=d['full_name'],due_date=d['due_date'],return_date=self.now(),overdue_days=days,fine=amount,breakdown=breakdown,estimate=True)

    def save_book(self, token, data, book_id=None):
        with self.db.transaction() as c:
            a=self._actor(c,token,STAFF)
            title=text(data.get('title'),'Tên sách',200);isbn=text(data.get('isbn'),'ISBN',20)
            require(bool(re.fullmatch(r'[0-9Xx-]{10,20}',isbn)),'INVALID_INPUT','ISBN cần 10–20 chữ số / dấu gạch nối.')
            year=integer(data.get('publication_year'),'Năm xuất bản',1000,self.clock().year+1)
            category=text(data.get('category'),'Thể loại',100)
            authors=data.get('authors')
            require(isinstance(authors,list) and 1<=len(authors)<=20,'INVALID_INPUT','Cần từ 1 đến 20 tác giả.')
            authors=list(dict.fromkeys(text(x,'Tác giả',120) for x in authors))
            publisher=str(data.get('publisher','')).strip();require(len(publisher)<=150,'INVALID_INPUT','Nhà xuất bản quá dài.')
            description=str(data.get('description',''));require(len(description)<=5000,'INVALID_INPUT','Mô tả quá dài.')
            status=data.get('status','ACTIVE');require(status in ('ACTIVE','WITHDRAWN'),'INVALID_INPUT','Trạng thái sách không hợp lệ.')
            if book_id is not None:
                require(c.execute('SELECT id FROM books WHERE id=?',(book_id,)).fetchone() is not None,'NOT_FOUND','Không tìm thấy sách.',404)
                if status=='WITHDRAWN':
                    require(not c.execute("SELECT id FROM book_copies WHERE book_id=? AND status IN ('ON_LOAN','HELD')",(book_id,)).fetchone(),'CONFLICT','Sách đang được mượn hoặc giữ chỗ.',409)
                    require(not c.execute("SELECT id FROM reservations WHERE book_id=? AND status IN ('READY','WAITING')",(book_id,)).fetchone(),'CONFLICT','Sách còn hàng chờ đặt trước.',409)
            c.execute('INSERT OR IGNORE INTO categories(name) VALUES(?)',(category,));category_id=c.execute('SELECT id FROM categories WHERE name=?',(category,)).fetchone()['id']
            publisher_id=None
            if publisher:
                c.execute('INSERT OR IGNORE INTO publishers(name) VALUES(?)',(publisher,));publisher_id=c.execute('SELECT id FROM publishers WHERE name=?',(publisher,)).fetchone()['id']
            try:
                values=(isbn,title,category_id,publisher_id,year,description,status)
                if book_id is None:
                    book_id=c.execute('INSERT INTO books(isbn,title,category_id,publisher_id,publication_year,description,status) VALUES(?,?,?,?,?,?,?)',values).lastrowid
                else:
                    c.execute('UPDATE books SET isbn=?,title=?,category_id=?,publisher_id=?,publication_year=?,description=?,status=? WHERE id=?',values+(book_id,))
                    c.execute('DELETE FROM book_authors WHERE book_id=?',(book_id,))
                for author in authors:
                    c.execute('INSERT OR IGNORE INTO authors(name) VALUES(?)',(author,));author_id=c.execute('SELECT id FROM authors WHERE name=?',(author,)).fetchone()['id']
                    c.execute('INSERT INTO book_authors VALUES(?,?)',(book_id,author_id))
            except sqlite3.IntegrityError as e:
                raise RuleError('DUPLICATE_ISBN','ISBN đã tồn tại.',409) from e
            self._audit(c,a,'SAVE_BOOK',book_id)
            return dict(id=book_id)

    def save_copy(self, token, data, copy_id=None):
        with self.db.transaction() as c:
            a=self._actor(c,token,STAFF)
            barcode=text(data.get('barcode'),'Mã vạch',50);location=text(data.get('location'),'Vị trí',60)
            status=data.get('status','AVAILABLE');require(status in ('AVAILABLE','DAMAGED','LOST','WITHDRAWN'),'INVALID_INPUT','Trạng thái này chỉ được đổi qua quy trình mượn trả.')
            book_id=integer(data.get('book_id'),'Mã đầu sách',1)
            require(c.execute("SELECT id FROM books WHERE id=? AND status='ACTIVE'",(book_id,)).fetchone() is not None,'NOT_FOUND','Đầu sách không hoạt động.',404)
            if copy_id is not None:
                old=c.execute('SELECT * FROM book_copies WHERE id=?',(copy_id,)).fetchone();require(old is not None,'NOT_FOUND','Không tìm thấy bản sao.',404)
                require(old['status'] not in ('ON_LOAN','HELD'),'CONFLICT','Không chỉnh bản sao đang mượn hoặc giữ chỗ.',409)
                require(old['book_id']==book_id,'CONFLICT','Không chuyển bản sao sang đầu sách khác.',409)
            try:
                if copy_id is None:
                    copy_id=c.execute('INSERT INTO book_copies(book_id,barcode,location,status) VALUES(?,?,?,?)',(book_id,barcode,location,status)).lastrowid
                else:
                    c.execute('UPDATE book_copies SET barcode=?,location=?,status=? WHERE id=?',(barcode,location,status,copy_id))
            except sqlite3.IntegrityError as e:
                raise RuleError('DUPLICATE_BARCODE','Mã vạch đã tồn tại.',409) from e
            self._expire(c);self._allocate(c,book_id)
            self._audit(c,a,'SAVE_COPY',copy_id)
            return dict(id=copy_id)

    def members(self, token, query=''):
        with self.db.transaction() as c:
            self._actor(c,token,STAFF)
            return [dict(r) for r in c.execute('SELECT m.*,a.username,a.email,a.status account_status FROM members m JOIN accounts a ON a.id=m.account_id WHERE m.full_name LIKE ? OR a.username LIKE ? OR m.phone LIKE ? ORDER BY m.id LIMIT 200',tuple(['%'+str(query)+'%']*3))]

    def save_member(self, token, data, member_id=None):
        with self.db.transaction() as c:
            a=self._actor(c,token,STAFF)
            if member_id is None:
                result=self._create_account(c,data)
                self._audit(c,a,'CREATE_MEMBER',result['profile_id'])
                return result
            self._member(c,member_id)
            name=text(data.get('full_name'),'Họ tên',100)
            phone=str(data.get('phone',''));address=str(data.get('address',''))
            require((not phone or bool(re.fullmatch(r'[+0-9 ()-]{6,20}',phone))) and len(address)<=255,'INVALID_INPUT','Liên hệ không hợp lệ.')
            status=data.get('status','ACTIVE');require(status in ('ACTIVE','INACTIVE'),'INVALID_INPUT','Trạng thái thẻ không hợp lệ.')
            c.execute('UPDATE members SET full_name=?,phone=?,address=?,status=? WHERE id=?',(name,phone,address,status,member_id))
            if status=='INACTIVE':
                c.execute('DELETE FROM sessions WHERE account_id=(SELECT account_id FROM members WHERE id=?)',(member_id,))
            self._audit(c,a,'UPDATE_MEMBER',member_id)
            return dict(id=member_id)

    def accounts(self, token):
        with self.db.transaction() as c:
            self._actor(c,token,('ADMINISTRATOR',))
            return [dict(r) for r in c.execute('SELECT a.id,a.username,a.email,a.role,a.status,COALESCE(m.full_name,s.full_name) full_name FROM accounts a LEFT JOIN members m ON m.account_id=a.id LEFT JOIN staff s ON s.account_id=a.id ORDER BY a.id')]

    def save_account(self, token, data, account_id=None):
        with self.db.transaction() as c:
            a=self._actor(c,token,('ADMINISTRATOR',))
            role=data.get('role','MEMBER');status=data.get('status','ACTIVE')
            require(role in ('MEMBER',)+STAFF and status in ('ACTIVE','INACTIVE'),'INVALID_INPUT','Vai trò / trạng thái không hợp lệ.')
            if account_id is None:
                result=self._create_account(c,data,role)
                if status=='INACTIVE':c.execute('UPDATE accounts SET status=? WHERE id=?',(status,result['account_id']))
                self._audit(c,a,'CREATE_ACCOUNT',result['account_id'])
                return result
            old=c.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
            require(old is not None,'NOT_FOUND','Không tìm thấy tài khoản.',404)
            require((old['role']=='MEMBER')==(role=='MEMBER'),'PROFILE_CONFLICT','Không đổi chéo hồ sơ độc giả và nhân viên.',409)
            if old['role']=='ADMINISTRATOR' and old['status']=='ACTIVE' and (role!='ADMINISTRATOR' or status!='ACTIVE'):
                require(c.execute("SELECT COUNT(*) n FROM accounts WHERE role='ADMINISTRATOR' AND status='ACTIVE'").fetchone()['n']>1,'LAST_ADMIN','Không thể vô hiệu hóa quản trị viên cuối cùng.',409)
            c.execute('UPDATE accounts SET role=?,status=? WHERE id=?',(role,status,account_id))
            c.execute('DELETE FROM sessions WHERE account_id=?',(account_id,))
            self._audit(c,a,'UPDATE_ACCOUNT',account_id)
            return dict(id=account_id)

    def _balance(self, c, member_id):
        return c.execute('SELECT COALESCE(SUM(f.amount-(SELECT COALESCE(SUM(p.amount),0) FROM fine_payments p WHERE p.fine_id=f.id)),0) balance FROM fines f JOIN loan_details d ON d.id=f.detail_id JOIN loans l ON l.id=d.loan_id WHERE l.member_id=?',(member_id,)).fetchone()['balance']

    def _eligibility(self, c, member_id, count):
        m=self._member(c,member_id);p=self._policy(c)
        rows=c.execute("SELECT d.id,d.due_date FROM loan_details d JOIN loans l ON l.id=d.loan_id WHERE l.member_id=? AND d.status='OPEN'",(member_id,)).fetchall()
        overdue=[r['id'] for r in rows if r['due_date']<self.now()];balance=self._balance(c,member_id)
        member = Member(id=member_id, member_status=m['status'], status=m['account_status'],
                        open_count=len(rows), limit=p['max_active_copies'], overdue_count=len(overdue), balance=balance)
        reasons = member.borrowing_reasons(count, p['fine_block_threshold'])
        return dict(eligible=not reasons,reasons=reasons,open_count=len(rows),requested=count,limit=p['max_active_copies'],overdue_details=overdue,balance=balance)

    def eligibility(self, token, member_id, count=1):
        integer(count,'Số lượng',0,100)
        with self.db.transaction() as c:
            self._actor(c,token,STAFF)
            return self._eligibility(c,member_id,count)

    def _idempotent(self,c,a,kind,key,payload,operation):
        key=text(key,'Mã yêu cầu',100)
        fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        old=c.execute('SELECT * FROM requests WHERE actor=? AND kind=? AND request_key=?',(a['id'],kind,key)).fetchone()
        if old:
            require(old['fingerprint']==fingerprint,'REQUEST_KEY_CONFLICT','Mã yêu cầu đã dùng cho dữ liệu khác.',409)
            return json.loads(old['result'])
        result=operation()
        c.execute('INSERT INTO requests VALUES(?,?,?,?,?)',(a['id'],kind,key,fingerprint,json.dumps(result)))
        return result

    def _expire(self,c):
        rows=c.execute("SELECT * FROM reservations WHERE status='READY' AND expires_at<=?",(self.now(),)).fetchall()
        for r in rows:
            c.execute("UPDATE reservations SET status='EXPIRED' WHERE id=?",(r['id'],))
            c.execute("UPDATE book_copies SET status='AVAILABLE' WHERE id=? AND status='HELD'",(r['copy_id'],))
        for book_id in {r['book_id'] for r in rows}:self._allocate(c,book_id)

    def _allocate(self,c,book_id):
        copies=c.execute("SELECT bc.id FROM book_copies bc JOIN books b ON b.id=bc.book_id WHERE bc.book_id=? AND bc.status='AVAILABLE' AND b.status='ACTIVE' ORDER BY bc.id",(book_id,)).fetchall()
        for cp in copies:
            waiting=c.execute("SELECT * FROM reservations WHERE book_id=? AND status='WAITING' ORDER BY id",(book_id,)).fetchall()
            winner=next((r for r in waiting if self._eligibility(c,r['member_id'],1)['eligible']),None)
            if not winner:break
            expires=(self.clock()+timedelta(hours=self._policy(c)['pickup_hours'])).isoformat(timespec='seconds')
            c.execute("UPDATE reservations SET status='READY',copy_id=?,expires_at=? WHERE id=?",(cp['id'],expires,winner['id']))
            c.execute("UPDATE book_copies SET status='HELD' WHERE id=?",(cp['id'],))

    def reserve(self,token,book_id):
        with self.db.transaction() as c:
            a=self._actor(c,token,('MEMBER',));mid=self._own_member(c,a);m=self._member(c,mid)
            require(m['status']=='ACTIVE','INACTIVE_MEMBER','Thẻ độc giả không hoạt động.')
            self._expire(c)
            require(c.execute("SELECT id FROM books WHERE id=? AND status='ACTIVE'",(book_id,)).fetchone() is not None,'NOT_FOUND','Đầu sách không hoạt động.',404)
            require(not c.execute("SELECT id FROM book_copies WHERE book_id=? AND status='AVAILABLE'",(book_id,)).fetchone(),'AVAILABLE_TITLE','Sách còn bản sẵn sàng; vui lòng đến quầy mượn.')
            try:
                rid=c.execute('INSERT INTO reservations(member_id,book_id,created_at) VALUES(?,?,?)',(mid,book_id,self.now())).lastrowid
            except sqlite3.IntegrityError as e:raise RuleError('DUPLICATE_RESERVATION','Bạn đã đặt trước đầu sách này.',409) from e
            self._audit(c,a,'RESERVE',rid)
            return dict(id=rid)

    def reservations(self,token):
        with self.db.transaction() as c:
            a=self._actor(c,token);self._expire(c)
            mid=self._own_member(c,a) if a['role']=='MEMBER' else None
            where='WHERE r.member_id=?' if mid else ''
            return [dict(r) for r in c.execute('SELECT r.*,b.title,m.full_name,bc.barcode,(SELECT COUNT(*) FROM reservations q WHERE q.book_id=r.book_id AND q.status="WAITING" AND q.id<=r.id) queue_position FROM reservations r JOIN books b ON b.id=r.book_id JOIN members m ON m.id=r.member_id LEFT JOIN book_copies bc ON bc.id=r.copy_id '+where+' ORDER BY r.id DESC LIMIT 200', (mid,) if mid else ())]

    def cancel_reservation(self,token,reservation_id):
        with self.db.transaction() as c:
            a=self._actor(c,token,('MEMBER',));mid=self._own_member(c,a);self._expire(c)
            r=c.execute('SELECT * FROM reservations WHERE id=?',(reservation_id,)).fetchone()
            require(r is not None,'NOT_FOUND','Không tìm thấy đặt trước.',404)
            require(r['member_id']==mid,'FORBIDDEN','Không phải đặt trước của bạn.',403)
            require(r['status'] in ('WAITING','READY'),'CONFLICT','Đặt trước không còn hoạt động.',409)
            c.execute("UPDATE reservations SET status='CANCELLED' WHERE id=?",(reservation_id,))
            if r['status']=='READY':c.execute("UPDATE book_copies SET status='AVAILABLE' WHERE id=?",(r['copy_id'],))
            self._allocate(c,r['book_id']);self._audit(c,a,'CANCEL_RESERVATION',reservation_id)
            return dict(cancelled=True)

    def checkout(self,token,member_id,barcodes,key):
        require(isinstance(barcodes,list) and 1<=len(barcodes)<=100 and all(isinstance(x,str) and x.strip() for x in barcodes),'INVALID_INPUT','Cần từ 1 đến 100 mã vạch.')
        barcodes=[x.strip() for x in barcodes]
        require(len(barcodes)==len(set(barcodes)),'DUPLICATE_COPY','Một bản sao bị quét hai lần.')
        with self.db.transaction() as c:
            a=self._actor(c,token,STAFF)
            def perform():
                self._expire(c)
                for r in c.execute("SELECT DISTINCT book_id FROM reservations WHERE status='WAITING'").fetchall():self._allocate(c,r['book_id'])
                decision=self._eligibility(c,member_id,len(barcodes))
                require(decision['eligible'],'INELIGIBLE','Không đủ điều kiện: '+', '.join(decision['reasons']),409)
                copies=[]
                for barcode in barcodes:
                    cp=c.execute('SELECT bc.*,b.status book_status FROM book_copies bc JOIN books b ON b.id=bc.book_id WHERE barcode=?',(barcode,)).fetchone()
                    require(cp is not None,'NOT_FOUND','Không tìm thấy bản sao: '+barcode,404)
                    owned=c.execute("SELECT id FROM reservations WHERE copy_id=? AND member_id=? AND status='READY'",(cp['id'],member_id)).fetchone()
                    require(cp['book_status']=='ACTIVE' and (cp['status']=='AVAILABLE' or (cp['status']=='HELD' and owned)),'COPY_UNAVAILABLE','Bản sao không sẵn sàng: '+barcode,409)
                    copies.append(cp)
                p=self._policy(c);due=(self.clock()+timedelta(days=p['loan_days'])).isoformat(timespec='seconds')
                loan_id=c.execute('INSERT INTO loans(member_id,staff_id,loan_date) VALUES(?,?,?)',(member_id,self._staff_id(c,a),self.now())).lastrowid
                details=[]
                for cp in copies:
                    details.append(c.execute('INSERT INTO loan_details(loan_id,copy_id,due_date,policy_snapshot) VALUES(?,?,?,?)',(loan_id,cp['id'],due,json.dumps(p))).lastrowid)
                    c.execute("UPDATE book_copies SET status='ON_LOAN' WHERE id=?",(cp['id'],))
                    c.execute("UPDATE reservations SET status='FULFILLED' WHERE copy_id=? AND member_id=? AND status='READY'",(cp['id'],member_id))
                self._audit(c,a,'CHECKOUT',loan_id)
                return dict(loan_id=loan_id,detail_ids=details,due_date=due,barcodes=barcodes)
            return self._idempotent(c,a,'CHECKOUT',key,[member_id,barcodes],perform)

    def history(self,token,member_id=None):
        with self.db.transaction() as c:
            a=self._actor(c,token)
            if a['role']=='MEMBER':member_id=self._own_member(c,a,member_id)
            elif member_id is not None:self._member(c,member_id)
            where='WHERE l.member_id=?' if member_id is not None else ''
            return [dict(r) for r in c.execute('SELECT d.id,d.loan_id,l.member_id,m.full_name,b.title,bc.barcode,d.due_date,d.return_date,d.renewal_count,d.status,l.loan_date,s.full_name staff_name,COALESCE(f.amount,0) fine FROM loan_details d JOIN loans l ON l.id=d.loan_id JOIN staff s ON s.id=l.staff_id JOIN members m ON m.id=l.member_id JOIN book_copies bc ON bc.id=d.copy_id JOIN books b ON b.id=bc.book_id LEFT JOIN fines f ON f.detail_id=d.id '+where+' ORDER BY d.id DESC LIMIT 500',(member_id,) if member_id is not None else ())]

    def renew(self,token,detail_id,key):
        with self.db.transaction() as c:
            a=self._actor(c,token,('MEMBER',));mid=self._own_member(c,a)
            def perform():
                self._expire(c)
                d=c.execute('SELECT d.*,l.member_id,bc.book_id FROM loan_details d JOIN loans l ON l.id=d.loan_id JOIN book_copies bc ON bc.id=d.copy_id WHERE d.id=?',(detail_id,)).fetchone()
                require(d is not None,'NOT_FOUND','Không tìm thấy chi tiết mượn.',404)
                require(d['member_id']==mid,'FORBIDDEN','Không phải phiếu mượn của bạn.',403)
                require(d['status']=='OPEN','CONFLICT','Sách đã được trả.',409)
                check=self._eligibility(c,mid,0);require(check['eligible'],'INELIGIBLE','Không đủ điều kiện: '+', '.join(check['reasons']),409)
                p=json.loads(d['policy_snapshot'])
                require(d['renewal_count']<p['max_renewals'],'RENEWAL_LIMIT','Đã hết lượt gia hạn.',409)
                require(not c.execute("SELECT id FROM reservations WHERE book_id=? AND member_id<>? AND status IN ('WAITING','READY')",(d['book_id'],mid)).fetchone(),'RESERVATION_CONFLICT','Có độc giả đang chờ đầu sách này.',409)
                due=(datetime.fromisoformat(d['due_date'])+timedelta(days=p['renewal_days'])).isoformat(timespec='seconds')
                c.execute('UPDATE loan_details SET due_date=?,renewal_count=renewal_count+1 WHERE id=?',(due,detail_id));self._audit(c,a,'RENEW',detail_id)
                return dict(detail_id=detail_id,due_date=due,renewal_count=d['renewal_count']+1)
            return self._idempotent(c,a,'RENEW',key,detail_id,perform)

    def return_copy(self,token,barcode,condition,key):
        require(condition in ('AVAILABLE','DAMAGED','LOST'),'INVALID_INPUT','Tình trạng trả sách không hợp lệ.')
        with self.db.transaction() as c:
            a=self._actor(c,token,STAFF)
            def perform():
                self._expire(c)
                d=c.execute('SELECT d.*,bc.book_id FROM loan_details d JOIN book_copies bc ON bc.id=d.copy_id WHERE bc.barcode=? ORDER BY d.id DESC LIMIT 1',(barcode,)).fetchone()
                require(d is not None,'NOT_ON_LOAN','Bản sao chưa có phiếu mượn.',404)
                if d['status']=='RETURNED':
                    f=c.execute('SELECT id,amount FROM fines WHERE detail_id=?',(d['id'],)).fetchone()
                    return dict(detail_id=d['id'],fine_id=f['id'] if f else None,fine=f['amount'] if f else 0,already_returned=True)
                require(self.now()>=c.execute('SELECT loan_date FROM loans WHERE id=?',(d['loan_id'],)).fetchone()['loan_date'],'INVALID_DATE','Ngày trả không thể trước ngày mượn.')
                delta=self.clock()-datetime.fromisoformat(d['due_date'])
                days=LoanDetail(datetime.fromisoformat(d['due_date'])).overdue_days(self.clock())
                amount,breakdown=fine_amount(days,json.loads(d['policy_snapshot']))
                c.execute("UPDATE loan_details SET status='RETURNED',return_date=? WHERE id=?",(self.now(),d['id']))
                fid=None
                if amount:
                    fid=c.execute('INSERT INTO fines(detail_id,amount,overdue_days,breakdown,issued_at) VALUES(?,?,?,?,?)',(d['id'],amount,days,json.dumps(breakdown),self.now())).lastrowid
                if not c.execute("SELECT id FROM loan_details WHERE loan_id=? AND status='OPEN'",(d['loan_id'],)).fetchone():c.execute("UPDATE loans SET status='CLOSED' WHERE id=?",(d['loan_id'],))
                c.execute('UPDATE book_copies SET status=? WHERE id=?',(condition,d['copy_id']))
                if condition=='AVAILABLE':self._allocate(c,d['book_id'])
                self._audit(c,a,'RETURN',d['id'])
                return dict(detail_id=d['id'],fine_id=fid,fine=amount,overdue_days=days,breakdown=breakdown,condition=condition)
            return self._idempotent(c,a,'RETURN',key,[barcode,condition],perform)

    def fines(self,token,member_id=None):
        with self.db.transaction() as c:
            a=self._actor(c,token)
            if a['role']=='MEMBER':member_id=self._own_member(c,a,member_id)
            where='WHERE l.member_id=?' if member_id is not None else ''
            rows=c.execute('SELECT f.*,l.member_id,m.full_name,b.title,bc.barcode,(SELECT COALESCE(SUM(amount),0) FROM fine_payments p WHERE p.fine_id=f.id) paid FROM fines f JOIN loan_details d ON d.id=f.detail_id JOIN loans l ON l.id=d.loan_id JOIN members m ON m.id=l.member_id JOIN book_copies bc ON bc.id=d.copy_id JOIN books b ON b.id=bc.book_id '+where+' ORDER BY f.id DESC LIMIT 500',(member_id,) if member_id is not None else ()).fetchall()
            result=[]
            for r in rows:
                item=dict(r);item['balance']=Fine(item['amount'],item['paid']).balance;item['breakdown']=json.loads(item['breakdown']);result.append(item)
            return result

    def pay(self,token,fine_id,amount,method,key):
        integer(amount,'Số tiền',1);require(method in ('CASH','TRANSFER'),'INVALID_INPUT','Phương thức không hợp lệ.')
        with self.db.transaction() as c:
            a=self._actor(c,token,STAFF)
            def perform():
                f=c.execute('SELECT *,amount-(SELECT COALESCE(SUM(amount),0) FROM fine_payments WHERE fine_id=f.id) balance FROM fines f WHERE id=?',(fine_id,)).fetchone()
                require(f is not None,'NOT_FOUND','Không tìm thấy khoản phạt.',404)
                require(amount<=f['balance'],'OVERPAYMENT','Số tiền vượt dư nợ còn lại.',409)
                pid=c.execute('INSERT INTO fine_payments(fine_id,amount,method,staff_id,paid_at) VALUES(?,?,?,?,?)',(fine_id,amount,method,self._staff_id(c,a),self.now())).lastrowid
                self._audit(c,a,'PAYMENT',pid)
                return dict(payment_id=pid,fine_id=fine_id,amount=amount,balance=f['balance']-amount)
            return self._idempotent(c,a,'PAYMENT',key,[fine_id,amount,method],perform)

    def report(self,token,start,end):
        try:
            begin=datetime.fromisoformat(start);finish=datetime.fromisoformat(end)
            require(begin.tzinfo is not None and finish.tzinfo is not None and begin<finish,'INVALID_DATE','Khoảng ngày cần ngày bắt đầu < ngày kết thúc và có múi giờ.')
        except (TypeError,ValueError) as e:raise RuleError('INVALID_DATE','Ngày tháng không hợp lệ.') from e
        start=begin.astimezone(timezone.utc).isoformat(timespec='seconds');end=finish.astimezone(timezone.utc).isoformat(timespec='seconds')
        with self.db.transaction() as c:
            self._actor(c,token,STAFF)
            groups=[dict(r) for r in c.execute('SELECT ca.name category,COUNT(*) borrowed FROM loan_details d JOIN loans l ON l.id=d.loan_id JOIN book_copies bc ON bc.id=d.copy_id JOIN books b ON b.id=bc.book_id JOIN categories ca ON ca.id=b.category_id WHERE l.loan_date>=? AND l.loan_date<? GROUP BY ca.id ORDER BY borrowed DESC',(start,end))]
            payments=[dict(r) for r in c.execute('SELECT p.*,m.full_name FROM fine_payments p JOIN fines f ON f.id=p.fine_id JOIN loan_details d ON d.id=f.detail_id JOIN loans l ON l.id=d.loan_id JOIN members m ON m.id=l.member_id WHERE p.paid_at>=? AND p.paid_at<? ORDER BY p.id',(start,end))]
            inventory=[dict(r) for r in c.execute('SELECT status,COUNT(*) quantity FROM book_copies GROUP BY status')]
            returned=c.execute("SELECT COUNT(*) FROM loan_details WHERE return_date>=? AND return_date<?",(start,end)).fetchone()[0]
            open_count=c.execute("SELECT COUNT(*) FROM loan_details d JOIN loans l ON l.id=d.loan_id WHERE l.loan_date>=? AND l.loan_date<? AND d.status='OPEN'",(start,end)).fetchone()[0]
            overdue_count=c.execute("SELECT COUNT(*) FROM loan_details d JOIN loans l ON l.id=d.loan_id WHERE l.loan_date>=? AND l.loan_date<? AND d.status='OPEN' AND d.due_date<?",(start,end,self.now())).fetchone()[0]
            return dict(returned=returned,open=open_count,overdue=overdue_count,start=start,end=end,generated_at=self.now(),borrowed=sum(g['borrowed'] for g in groups),by_category=groups,payments=payments,collected=sum(p['amount'] for p in payments),inventory=inventory)

    def lookup_copy(self, token, barcode):
        """Resolve a scanned barcode without exposing private borrower data."""
        barcode = text(barcode, 'Mã vạch', 50)
        with self.db.transaction() as c:
            self._actor(c, token, STAFF)
            row = c.execute('SELECT bc.*,b.title,b.publisher_id FROM book_copies bc JOIN books b ON b.id=bc.book_id WHERE bc.barcode=?', (barcode,)).fetchone()
            require(row is not None, 'NOT_FOUND', 'Không tìm thấy mã vạch.', 404)
            return dict(row)

    def loan_policy(self, token):
        with self.db.transaction() as c:
            self._actor(c, token, STAFF)
            policy = self._policy(c)
            return {key: policy[key] for key in ('loan_days', 'max_active_copies')}

    def member_summary(self, token):
        with self.db.transaction() as c:
            actor = self._actor(c, token, ('MEMBER',))
            return self._eligibility(c, self._own_member(c, actor), 0)

    def payments(self, token):
        """Receipt history, restricted to the signed-in reader when applicable."""
        with self.db.transaction() as c:
            actor = self._actor(c, token)
            params = ()
            where = ''
            if actor['role'] == 'MEMBER':
                where = 'WHERE l.member_id=?'
                params = (self._own_member(c, actor),)
            return [dict(row) for row in c.execute(
                'SELECT p.id,p.fine_id,p.amount,p.method,p.paid_at,m.full_name '
                'FROM fine_payments p JOIN fines f ON f.id=p.fine_id '
                'JOIN loan_details d ON d.id=f.detail_id JOIN loans l ON l.id=d.loan_id '
                'JOIN members m ON m.id=l.member_id '+where+' ORDER BY p.id DESC LIMIT 500', params)]

    def dashboard(self, token):
        with self.db.transaction() as c:
            self._actor(c, token, STAFF)
            today = self.clock().astimezone(timezone(timedelta(hours=7))).date()
            start = datetime.combine(today, datetime.min.time(), tzinfo=timezone(timedelta(hours=7))).astimezone(timezone.utc).isoformat(timespec='seconds')
            return dict(new_loans=c.execute('SELECT COUNT(*) FROM loans WHERE loan_date>=?', (start,)).fetchone()[0],
                        open=c.execute("SELECT COUNT(*) FROM loan_details WHERE status='OPEN'").fetchone()[0],
                        overdue=c.execute("SELECT COUNT(*) FROM loan_details WHERE status='OPEN' AND due_date<?", (self.now(),)).fetchone()[0])

    def backup(self,token,path,password):
        """Consistent snapshot, integrity validation, password-based authenticated encryption."""
        import base64
        import tempfile
        from pathlib import Path
        from cryptography.fernet import Fernet
        require(isinstance(password,str) and len(password)>=12,'INVALID_INPUT','Mật khẩu bản sao lưu tối thiểu 12 ký tự.')
        with self.db.transaction() as c:self._actor(c,token,('ADMINISTRATOR',))
        with tempfile.TemporaryDirectory() as tmp:
            snapshot=Path(tmp)/'snapshot.sqlite3'
            with closing(self.db.connect()) as src,closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
                require(dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not dst.execute('PRAGMA foreign_key_check').fetchall(),'BACKUP_FAILED','Kiểm tra bản sao lưu thất bại.')
            salt=secrets.token_bytes(16);derived=base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000))
            payload=b'LIBRARY1'+salt+Fernet(derived).encrypt(snapshot.read_bytes())
            Path(path).parent.mkdir(parents=True,exist_ok=True)
            Path(path).write_bytes(payload)
        return dict(file=Path(path).name,bytes=len(payload))

    @staticmethod
    def restore_backup(source,password,destination):
        """Offline restore only; never overwrite a running database."""
        import base64
        from pathlib import Path
        from cryptography.fernet import Fernet,InvalidToken
        target=Path(destination);require(not target.exists(),'CONFLICT','Chỉ khôi phục sang file mới.',409)
        raw=Path(source).read_bytes();require(raw[:8]==b'LIBRARY1','INVALID_BACKUP','Định dạng bản sao lưu không đúng.')
        key=base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256',password.encode(),raw[8:24],600000))
        try:plain=Fernet(key).decrypt(raw[24:])
        except InvalidToken as e:raise RuleError('INVALID_BACKUP','Mật khẩu sai hoặc bản sao lưu bị hỏng.') from e
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(plain)
        try:
            with closing(sqlite3.connect(target)) as c:
                require(c.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not c.execute('PRAGMA foreign_key_check').fetchall(),'INVALID_BACKUP','Cơ sở dữ liệu khôi phục không hợp lệ.')
                c.execute('DELETE FROM sessions');c.commit()
        except BaseException:
            target.unlink(missing_ok=True);raise
        return str(target)

    def seed_demo(self):
        with self.db.transaction() as c:
            if c.execute('SELECT id FROM accounts LIMIT 1').fetchone():return
            for username,role,name in [('admin','ADMINISTRATOR','Quản trị viên'),('librarian','LIBRARIAN','Nguyễn Phúc Thịnh'),('member','MEMBER','Nguyễn Phúc Thịnh')]:
                self._create_account(c,dict(username=username,email=username+'@library.example',full_name=name,password='LibraryDemo!2026'),role)
            c.execute("INSERT INTO categories(name) VALUES('Giáo khoa')");c.execute("INSERT INTO publishers(name) VALUES('Giáo dục Việt Nam')");c.execute("INSERT INTO authors(name) VALUES('Nhiều tác giả')")
            for i,title in enumerate(['Ngữ văn 6 · Tập 2','Toán 7 · Tập 1','Khoa học tự nhiên 8'],1):
                bid=c.execute('INSERT INTO books(isbn,title,category_id,publisher_id,publication_year,description) VALUES(?,?,1,1,2024,?)',(f'97860400000{i:02}',title,'Tài liệu học tập trong thư viện.')).lastrowid
                c.execute('INSERT INTO book_authors VALUES(?,1)',(bid,))
                for j in range(1,4):c.execute('INSERT INTO book_copies(book_id,barcode,location) VALUES(?,?,?)',(bid,f'BK{i:02}-{j:03}',f'Kệ A{i} / Ngăn {j}'))


# 3. DỮ LIỆU MINH HỌA

"""Reproducible demo fixture for the supplied UI, separate from test fixtures.

Dates are relative to the first launch; subsequent launches never overwrite data.
"""
from datetime import timedelta
import json


def seed_figma_demo(service):
    with service.db.transaction() as c:
        if c.execute('SELECT id FROM accounts LIMIT 1').fetchone():
            return
        password = 'LibraryDemo!2026'
        people = [
            ('admin', 'admin@library.example', 'Quản trị thư viện', 'ADMINISTRATOR'),
            ('thinh.nguyen', 'nguyenphucthinh23062006@gmail.com', 'Nguyễn Phúc Thịnh', 'LIBRARIAN'),
            ('phucthinh', 'phucthinh.reader@library.example', 'Nguyễn Phúc Thịnh', 'MEMBER'),
            ('hoangnam', 'hoangnam@example.com', 'Trần Hoàng Nam', 'MEMBER'),
        ]
        member_ids = []
        for username, email, name, role in people:
            result = service._create_account(c, dict(username=username, email=email,
                full_name=name, password=password), role)
            table = 'members' if role == 'MEMBER' else 'staff'
            c.execute(f'UPDATE {table} SET phone=? WHERE id=?', ('0901234567', result['profile_id']))
            if role == 'MEMBER':
                member_ids.append(result['profile_id'])
        # Match the card identifiers displayed in the reference screens.
        c.execute('UPDATE members SET id=24 WHERE id=?', (member_ids[0],))
        c.execute('UPDATE members SET id=18 WHERE id=?', (member_ids[1],))
        categories = ['Sách giáo khoa', 'Văn học', 'Khoa học']
        for name in categories:
            c.execute('INSERT INTO categories(name) VALUES(?)', (name,))
        c.execute("INSERT INTO publishers(name) VALUES('Giáo dục Việt Nam')")
        c.execute("INSERT INTO authors(name) VALUES('Nhiều tác giả')")
        titles = [('Ngữ văn 6 · Tập 2',12,1), ('Ngữ văn 7 · Tập 1',5,1),
                  ('Ngữ văn 8 · Tập 2',3,1), ('Dế Mèn phiêu lưu ký',1,2),
                  ('Tôi thấy hoa vàng trên cỏ xanh',1,2)]
        for i,(title,total,category) in enumerate(titles,1):
            c.execute('INSERT INTO books(id,isbn,title,category_id,publisher_id,publication_year,description) VALUES(?,?,?,?,1,2024,?)',
                (i, '978-604-0-18234-1' if i==1 else f'97860400000{i:02}', title, category,
                 'Tài liệu học tập môn Ngữ văn dành cho học sinh lớp 6.' if i==1 else 'Sách trong thư viện.'))
            c.execute('INSERT INTO book_authors VALUES(?,1)', (i,))
            for j in range(total):
                barcode = f'NV6-{18+j:04}' if i==1 else f'B{i:02}-{j+1:04}'
                c.execute('INSERT INTO book_copies(book_id,barcode,location) VALUES(?,?,?)',
                    (i,barcode,'Kệ A2 / Ngăn 3'))
        policy = json.dumps(service._policy(c))
        now = service.clock()
        staff_id = c.execute("SELECT s.id FROM staff s JOIN accounts a ON a.id=s.account_id WHERE a.username='thinh.nguyen'").fetchone()['id']
        def loan(mid, barcode, due, age):
            loan_id = c.execute("INSERT INTO loans(member_id,staff_id,loan_date) VALUES(?,?,?)",(mid,staff_id,(now-timedelta(days=age)).isoformat(timespec='seconds'))).lastrowid
            copy_id = c.execute('SELECT id FROM book_copies WHERE barcode=?',(barcode,)).fetchone()['id']
            c.execute('INSERT INTO loan_details(loan_id,copy_id,due_date,policy_snapshot) VALUES(?,?,?,?)',(loan_id,copy_id,due.isoformat(timespec='seconds'),policy))
            c.execute("UPDATE book_copies SET status='ON_LOAN' WHERE id=?",(copy_id,))
        # The late example is just under eight complete days: ceil() = eight.
        loan(18,'NV6-0018',now-timedelta(days=8)+timedelta(hours=12),22)
        loan(24,'NV6-0022',now+timedelta(days=14),0)
        loan(18,'NV6-0019',now+timedelta(days=10),4)
        loan(18,'NV6-0020',now+timedelta(days=10),4)
        loan(18,'B04-0001',now+timedelta(days=10),4)
        c.execute("INSERT INTO reservations(member_id,book_id,created_at,status) VALUES(24,4,?,'WAITING')",(service.now(),))
        copy_id=c.execute("SELECT id FROM book_copies WHERE barcode='B05-0001'").fetchone()['id']
        c.execute("UPDATE book_copies SET status='HELD' WHERE id=?",(copy_id,))
        c.execute("INSERT INTO reservations(member_id,book_id,created_at,status,copy_id,expires_at) VALUES(24,5,?,'READY',?,?)",
                  (service.now(),copy_id,(now+timedelta(hours=48)).isoformat(timespec='seconds')))
