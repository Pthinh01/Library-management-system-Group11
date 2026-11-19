"""Executable acceptance cases, each linked to the testing workbook."""
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Source_code import LibraryService, RuleError, DEFAULT_POLICY, fine_amount, password_hash, password_matches

CASES=[]
def case(cid,req,title,expected):
    def decorate(fn):
        fn.case_id=cid
        CASES.append(dict(id=cid,requirement=req,title=title,expected=expected,test=fn.__module__+'.'+fn.__qualname__,steps=(fn.__doc__ or title).strip()))
        return fn
    return decorate

class Clock:
    def __init__(self):self.value=datetime(2026,11,14,8,0,tzinfo=timezone.utc)
    def __call__(self):return self.value
    def advance(self,**kwargs):self.value+=timedelta(**kwargs)

class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_dir=tempfile.TemporaryDirectory();cls.template=Path(cls.template_dir.name)/'template.db'
        s=LibraryService(cls.template,Clock());s.seed_demo()
        with s.db.transaction() as c:
            s._create_account(c,dict(username='second',email='second@library.example',full_name='Độc giả thứ hai',password='LibraryDemo!2026'))
        with closing(s.db.connect()) as c:c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # Snapshot through SQLite rather than copying a live WAL database.
        cls.snapshot=Path(cls.template_dir.name)/'snapshot.db'
        with closing(s.db.connect()) as src,closing(sqlite3.connect(cls.snapshot)) as dst:src.backup(dst)

    @classmethod
    def tearDownClass(cls):cls.template_dir.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'library.db';shutil.copy2(self.snapshot,self.path)
        self.clock=Clock();self.s=LibraryService(self.path,self.clock)
        # Login still uses the real password verifier; sessions are prepared without repeated logins.
        self.tokens={}
        import secrets,hashlib
        with self.s.db.transaction() as c:
            for a in c.execute('SELECT id,username FROM accounts').fetchall():
                token=secrets.token_urlsafe(24);self.tokens[a['username']]=token
                c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),a['id'],self.s.now(),'test-csrf'))
        self.staff=self.tokens['librarian'];self.admin=self.tokens['admin'];self.member=self.tokens['member'];self.second=self.tokens['second']

    def tearDown(self):self.tmp.cleanup()
    def error(self,code,fn,*args,**kwargs):
        with self.assertRaises(RuleError) as e:fn(*args,**kwargs)
        self.assertEqual(code,e.exception.code)
    def count(self,table):
        with self.s.db.transaction(False) as c:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def sql(self,query,args=()):
        with self.s.db.transaction() as c:return [dict(r) for r in c.execute(query,args)]
    def issue(self,codes=None,member_id=1,key='issue-1'):
        return self.s.checkout(self.staff,member_id,codes or ['BK01-001'],key)
    def late(self,days=8):
        result=self.issue();self.clock.advance(days=14+days)
        # Reauthenticate after test clock advances, as a real user would have to do.
        self.sql('UPDATE sessions SET last_active=?',(self.s.now(),))
        return result
    def fine(self,days=8):self.late(days);return self.s.return_copy(self.staff,'BK01-001','AVAILABLE','return-1')
    def book_data(self,**changes):
        d=dict(title='Tác phẩm mới',isbn='9786049999999',authors=['Tác giả A','Tác giả B'],category='Văn học',publisher='',publication_year=2025,description='Mô tả')
        d.update(changes);return d

    @case('TC-001','FR-01','Đăng ký độc giả hợp lệ','Tạo một tài khoản MEMBER và một hồ sơ liên kết.')
    def test_register(self):
        """Đăng ký họ tên, email, tên đăng nhập, mật khẩu 12 ký tự trở lên và xác nhận trùng nhau; đọc tài khoản vừa tạo."""
        d=dict(username='reader',email='reader@example.com',full_name='Bạn đọc',password='Passphrase!2026',confirmation='Passphrase!2026',role='ADMINISTRATOR')
        r=self.s.register(d);a=self.sql('SELECT role FROM accounts WHERE id=?',(r['account_id'],))[0];self.assertEqual(a['role'],'MEMBER');self.assertEqual(self.count('members'),3)
    @case('TC-002','FR-01','Tên đăng nhập trùng không phân biệt hoa thường','Từ chối DUPLICATE_IDENTITY và không tạo hồ sơ mồ côi.')
    def test_register_duplicate(self):
        n=self.count('members');self.error('DUPLICATE_IDENTITY',self.s.register,dict(username='MEMBER',email='new@example.com',full_name='N',password='Passphrase!2026',confirmation='Passphrase!2026'));self.assertEqual(n,self.count('members'))
    @case('TC-003','FR-01','Email trùng','Từ chối email trùng dù khác tên đăng nhập.')
    def test_duplicate_email(self):self.error('DUPLICATE_IDENTITY',self.s.register,dict(username='newreader',email='MEMBER@LIBRARY.EXAMPLE',full_name='N',password='Passphrase!2026',confirmation='Passphrase!2026'))
    @case('TC-004','FR-01','Mật khẩu xác nhận không khớp','Không tạo tài khoản.')
    def test_confirmation(self):self.error('INVALID_INPUT',self.s.register,dict(password='Passphrase!2026',confirmation='different'))
    @case('TC-005','FR-01','Thông tin đăng ký không hợp lệ','Từ chối email sai, mật khẩu ngắn, tên rỗng và username sai.')
    def test_registration_invalid(self):
        valid=dict(username='reader',email='reader@example.com',full_name='Reader',password='Passphrase!2026',confirmation='Passphrase!2026')
        for patch in [dict(email='invalid'),dict(password='short',confirmation='short'),dict(full_name=' '),dict(username='bad user')]:
            self.error('INVALID_INPUT',self.s.register,valid|patch)
    @case('TC-006','FR-01','Đăng nhập bằng username và email','Cả hai định danh hợp lệ đều tạo phiên cùng vai trò.')
    def test_login(self):
        for identity in ['member','MEMBER@library.example']:
            r=self.s.login(identity,'LibraryDemo!2026');self.assertEqual(self.s.me(r['token'])['role'],'MEMBER')
    @case('TC-007','FR-01','Sai mật khẩu hoặc tài khoản không tồn tại','Trả cùng thông báo AUTH_FAILED.')
    def test_login_generic(self):
        messages=[]
        for identity in ['member','unknown']:
            try:self.s.login(identity,'wrong-password')
            except RuleError as e:messages.append((e.code,str(e)))
        self.assertEqual(messages[0],messages[1]);self.assertEqual(messages[0][0],'AUTH_FAILED')
    @case('TC-008','FR-01','Tài khoản bị vô hiệu hóa','Không đăng nhập được và phiên cũ bị thu hồi.')
    def test_deactivate(self):
        self.s.save_account(self.admin,dict(role='MEMBER',status='INACTIVE'),3)
        self.error('AUTH_FAILED',self.s.login,'member','LibraryDemo!2026');self.error('SESSION_EXPIRED',self.s.me,self.member)
    @case('TC-009','FR-01','Đăng xuất và phát lại phiên','Phiên cũ không còn dùng được, đăng xuất lại an toàn.')
    def test_logout(self):self.s.logout(self.member);self.error('SESSION_EXPIRED',self.s.me,self.member);self.assertTrue(self.s.logout(self.member)['signed_out'])
    @case('TC-010','NFR-05','Hash mật khẩu có salt độc lập','Cùng mật khẩu cho hash khác nhau; xác minh đúng/sai chính xác.')
    def test_password_hash(self):
        a=password_hash('Passphrase!2026');b=password_hash('Passphrase!2026');self.assertNotEqual(a,b);self.assertTrue(password_matches('Passphrase!2026',a));self.assertFalse(password_matches('wrong',a));self.assertNotIn('Passphrase',a)
    @case('TC-011','NFR-05','Giới hạn đăng nhập sai','Lần thứ sáu trong 5 phút trả RATE_LIMIT; hết thời gian được thử lại.')
    def test_rate_limit(self):
        for _ in range(5):self.error('AUTH_FAILED',self.s.login,'member','wrong')
        self.error('RATE_LIMIT',self.s.login,'member','LibraryDemo!2026');self.clock.advance(minutes=5);self.assertIn('token',self.s.login('member','LibraryDemo!2026'))
    @case('TC-012','NFR-06','Hết hạn sau đúng 15 phút không hoạt động','Tại 14:59 còn hiệu lực; tại 15:00 phiên hết hạn.')
    def test_idle_boundary(self):
        self.clock.advance(minutes=14,seconds=59);self.s.me(self.member,touch=False);self.clock.advance(seconds=1);self.error('SESSION_EXPIRED',self.s.me,self.member)
    @case('TC-013','NFR-06','Tác vụ xác thực làm mới thời gian; polling không làm mới','Tác vụ gia hạn phiên, me(touch=False) không gia hạn.')
    def test_idle_refresh(self):
        self.clock.advance(minutes=14);self.s.history(self.member);self.clock.advance(minutes=14);self.s.me(self.member,touch=False);self.clock.advance(minutes=1);self.error('SESSION_EXPIRED',self.s.me,self.member)
    @case('TC-014','FR-02','Tra cứu theo tên / tác giả / ISBN','Trả đúng đầu sách và số bản sẵn sàng.')
    def test_search(self):
        for q in ['Ngữ văn','Nhiều tác giả','9786040000001']:
            r=self.s.catalog(q);self.assertGreater(r['total'],0)
        self.assertEqual(self.s.catalog('Ngữ văn')['items'][0]['available'],3)
    @case('TC-015','FR-02','Tìm không có kết quả','Trả danh sách trống và total bằng 0.')
    def test_empty_search(self):self.assertEqual(self.s.catalog('Không tồn tại')['total'],0)
    @case('TC-016','FR-02','Phân trang và lọc thể loại','Trang 1 và 2 không trùng; thể loại không có trả rỗng.')
    def test_pagination(self):
        self.assertNotEqual(self.s.catalog(page=1,page_size=1)['items'][0]['id'],self.s.catalog(page=2,page_size=1)['items'][0]['id']);self.assertEqual(self.s.catalog(category=999)['total'],0)
    @case('TC-017','FR-02','Đầu vào phân trang sai','Từ chối trang 0, page size 101 và từ khóa quá dài.')
    def test_search_validation(self):
        for args in [dict(page=0),dict(page_size=101),dict(query='x'*201)]:self.error('INVALID_INPUT',self.s.catalog,**args)
    @case('TC-018','NFR-05','Chuỗi SQL injection trong tìm kiếm','Không mở rộng kết quả và không sửa cơ sở dữ liệu.')
    def test_sql_injection(self):self.assertEqual(self.s.catalog("' OR 1=1; DROP TABLE books;--")['total'],0);self.assertEqual(self.count('books'),3)
    @case('TC-019','FR-02','Xem chi tiết sách và bản sao','Trả metadata, tác giả và ba mã vạch riêng biệt.')
    def test_book_detail(self):r=self.s.book(1);self.assertEqual(len(r['copies']),3);self.assertEqual(r['book']['authors'],'Nhiều tác giả')
    @case('TC-020','FR-06','Thêm đầu sách và nhiều tác giả','Tạo metadata, tác giả, thể loại và liên kết chính xác.')
    def test_add_book(self):
        r=self.s.save_book(self.staff,self.book_data());b=self.s.book(r['id'])['book'];self.assertEqual(b['category'],'Văn học');self.assertIn('Tác giả B',b['authors']);self.assertIsNone(b['publisher'])
    @case('TC-021','FR-06','ISBN trùng','Từ chối và rollback metadata / tác giả / thể loại mới.')
    def test_duplicate_isbn(self):
        n=self.count('categories');self.error('DUPLICATE_ISBN',self.s.save_book,self.staff,self.book_data(isbn='9786040000001'));self.assertEqual(n,self.count('categories'));self.assertEqual(self.count('books'),3)
    @case('TC-022','FR-06','Sửa metadata đầu sách','Đổi tên và danh sách tác giả; giữ bản sao và lịch sử.')
    def test_edit_book(self):
        self.s.save_book(self.staff,self.book_data(title='Tên mới'),1);self.assertEqual(self.s.book(1)['book']['title'],'Tên mới');self.assertEqual(len(self.s.book(1)['copies']),3)
    @case('TC-023','FR-06','Đầu sách thiếu dữ liệu / năm sai / ISBN sai','Từ chối và không thêm đầu sách.')
    def test_book_validation(self):
        for patch in [dict(title=''),dict(authors=[]),dict(publication_year=999),dict(publication_year=9999),dict(isbn='abc'),dict(category='')]:self.error('INVALID_INPUT',self.s.save_book,self.staff,self.book_data(**patch))
    @case('TC-024','FR-06','Thêm bản sao có mã vạch riêng','Lưu đúng vị trí, trạng thái AVAILABLE.')
    def test_add_copy(self):r=self.s.save_copy(self.staff,dict(book_id=1,barcode='NEW-001',location='Kệ B'));self.assertEqual(self.sql('SELECT status FROM book_copies WHERE id=?',(r['id'],))[0]['status'],'AVAILABLE')
    @case('TC-025','FR-06','Mã vạch trùng','Từ chối DUPLICATE_BARCODE, không thêm bản sao.')
    def test_duplicate_barcode(self):self.error('DUPLICATE_BARCODE',self.s.save_copy,self.staff,dict(book_id=1,barcode='BK01-001',location='Kệ B'));self.assertEqual(self.count('book_copies'),9)
    @case('TC-026','FR-06','Sửa bản sao đang mượn','Từ chối và giữ nguyên ON_LOAN.')
    def test_copy_on_loan(self):self.issue();self.error('CONFLICT',self.s.save_copy,self.staff,dict(book_id=1,barcode='BK01-001',location='B'),1)
    @case('TC-027','FR-06','Không tự đặt ON_LOAN / HELD qua sửa kho','Chỉ các quy trình mượn trả / đặt trước được đổi trạng thái này.')
    def test_copy_status_validation(self):
        for status in ['ON_LOAN','HELD','BAD']:self.error('INVALID_INPUT',self.s.save_copy,self.staff,dict(book_id=1,barcode='NEW',location='B',status=status))
    @case('TC-028','FR-06','Ngừng lưu hành đầu sách có phiếu mở','Từ chối; không phá lịch sử.')
    def test_withdraw_on_loan(self):self.issue();self.error('CONFLICT',self.s.save_book,self.staff,self.book_data(status='WITHDRAWN'),1)
    @case('TC-029','FR-06','Ngừng lưu hành sách không có ràng buộc','Không hiện trong tra cứu công khai; dữ liệu vẫn tồn tại.')
    def test_withdraw(self):self.s.save_book(self.staff,self.book_data(status='WITHDRAWN'),1);self.assertEqual(self.s.catalog()['total'],2);self.assertEqual(self.count('books'),3)
    @case('TC-030','FR-07','Mượn một bản hợp lệ','Một phiếu / chi tiết OPEN, bản sao ON_LOAN, hạn trả sau 14 ngày.')
    def test_checkout(self):
        r=self.issue();self.assertEqual(self.count('loans'),1);self.assertEqual(self.count('loan_details'),1);self.assertEqual(datetime.fromisoformat(r['due_date']),self.clock()+timedelta(days=14));self.assertEqual(self.sql('SELECT status FROM book_copies WHERE id=1')[0]['status'],'ON_LOAN')
    @case('TC-031','FR-07','Mượn nhiều bản nguyên tử','Tất cả chi tiết thuộc cùng phiếu và được ghi một lần.')
    def test_batch(self):r=self.issue(['BK01-001','BK02-001']);self.assertEqual(len(r['detail_ids']),2);self.assertEqual(self.count('loans'),1)
    @case('TC-032','FR-07','Mã vạch không tồn tại trong batch','Rollback cả batch; bản hợp lệ vẫn AVAILABLE.')
    def test_batch_rollback(self):self.error('NOT_FOUND',self.issue,['BK01-001','UNKNOWN']);self.assertEqual(self.count('loans'),0);self.assertEqual(self.s.book(1)['copies'][0]['status'],'AVAILABLE')
    @case('TC-033','FR-07','Quét trùng bản sao','Từ chối DUPLICATE_COPY và không tạo phiếu.')
    def test_duplicate_scan(self):self.error('DUPLICATE_COPY',self.issue,['BK01-001','BK01-001']);self.assertEqual(self.count('loans'),0)
    @case('TC-034','FR-07','Mượn bản đang ON_LOAN','Từ chối COPY_UNAVAILABLE.')
    def test_double_checkout(self):self.issue();self.error('COPY_UNAVAILABLE',self.issue,['BK01-001'],2,'another')
    @case('TC-035','FR-08','Số đang mượn cộng batch đúng giới hạn','Bốn đang mượn cộng một được phép, cộng hai bị từ chối.')
    def test_limit_boundary(self):
        self.issue(['BK01-001','BK01-002','BK02-001','BK02-002']);self.assertTrue(self.s.eligibility(self.staff,1,1)['eligible']);self.assertIn('BORROWING_LIMIT_EXCEEDED',self.s.eligibility(self.staff,1,2)['reasons']);self.issue(['BK03-001'],key='fifth');self.error('INELIGIBLE',self.issue,['BK03-002'],1,'sixth')
    @case('TC-036','FR-08','Batch vượt giới hạn không ghi một phần','Sáu bản trong một batch bị từ chối toàn bộ.')
    def test_batch_limit(self):self.error('INELIGIBLE',self.issue,['BK01-001','BK01-002','BK01-003','BK02-001','BK02-002','BK02-003']);self.assertEqual(self.count('loans'),0)
    @case('TC-037','FR-08','Có sách quá hạn nhưng chưa lập phạt','Chặn mượn mới bằng OVERDUE_UNRETURNED dù dư nợ bằng 0.')
    def test_overdue_unassessed(self):self.late(1);e=self.s.eligibility(self.staff,1);self.assertIn('OVERDUE_UNRETURNED',e['reasons']);self.assertEqual(e['balance'],0);self.error('INELIGIBLE',self.issue,['BK02-001'],1,'blocked')
    @case('TC-038','FR-08','Thẻ độc giả INACTIVE','Chặn mượn dù tài khoản còn ACTIVE.')
    def test_inactive_member(self):self.sql("UPDATE members SET status='INACTIVE' WHERE id=1");self.error('INELIGIBLE',self.issue)
    @case('TC-039','FR-08','Dư nợ bằng ngưỡng / vượt ngưỡng','Bằng ngưỡng được mượn; thấp hơn dư nợ thì bị chặn.')
    def test_fine_threshold(self):
        f=self.fine(1);self.s.settings(self.admin,dict(fine_block_threshold=1000));self.assertTrue(self.s.eligibility(self.staff,1)['eligible']);self.s.settings(self.admin,dict(fine_block_threshold=999));self.assertIn('OUTSTANDING_FINE_BLOCK',self.s.eligibility(self.staff,1)['reasons']);self.assertEqual(f['fine'],1000)
    @case('TC-040','FR-07','Gửi lại yêu cầu mượn cùng key','Trả phiếu cũ, chỉ có một phiếu và một chi tiết.')
    def test_checkout_idempotent(self):a=self.issue();b=self.issue();self.assertEqual(a,b);self.assertEqual(self.count('loans'),1)
    @case('TC-041','FR-07','Key mượn cũ với dữ liệu khác','Từ chối REQUEST_KEY_CONFLICT.')
    def test_request_key_conflict(self):self.issue();self.error('REQUEST_KEY_CONFLICT',self.issue,['BK02-001'])
    @case('TC-042','FR-07','Hai yêu cầu cạnh tranh một bản sao','Chỉ một thành công; không có hai chi tiết OPEN cho cùng bản.')
    def test_concurrent_checkout(self):
        barrier=threading.Barrier(2)
        def run(mid):
            barrier.wait()
            try:self.issue(['BK01-001'],mid,'race-'+str(mid));return True
            except RuleError:return False
        with ThreadPoolExecutor(2) as pool:out=list(pool.map(run,[1,2]))
        self.assertEqual(sum(out),1);self.assertEqual(self.count('loan_details'),1)
    @case('TC-043','FR-07','Trả đúng hạn','Không tạo phạt; đóng chi tiết / phiếu; bản sao AVAILABLE.')
    def test_return_ontime(self):self.issue();r=self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');self.assertEqual(r['fine'],0);self.assertEqual(self.count('fines'),0);self.assertEqual(self.sql('SELECT status FROM loans')[0]['status'],'CLOSED')
    @case('TC-044','FR-07','Trả một phần phiếu nhiều bản','Phiếu còn OPEN đến khi trả bản cuối.')
    def test_partial_return(self):self.issue(['BK01-001','BK02-001']);self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r1');self.assertEqual(self.sql('SELECT status FROM loans')[0]['status'],'OPEN');self.s.return_copy(self.staff,'BK02-001','AVAILABLE','r2');self.assertEqual(self.sql('SELECT status FROM loans')[0]['status'],'CLOSED')
    @case('TC-045','FR-07','Độc giả bị chặn vẫn được trả','Trả thành công khi thẻ INACTIVE và sách quá hạn.')
    def test_blocked_return(self):self.late(8);self.sql("UPDATE members SET status='INACTIVE' WHERE id=1");self.assertEqual(self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r')['fine'],9000)
    @case('TC-046','FR-07','Trả bản hỏng / mất','Không đưa bản sao vào trạng thái có thể cho mượn; không tự tính phí hư hỏng.')
    def test_return_damaged(self):
        self.issue(['BK01-001','BK02-001']);self.s.return_copy(self.staff,'BK01-001','DAMAGED','d');self.s.return_copy(self.staff,'BK02-001','LOST','l');self.assertEqual(self.sql('SELECT status FROM book_copies WHERE id=1')[0]['status'],'DAMAGED');self.assertEqual(self.count('fines'),0)
    @case('TC-047','FR-07','Trả lại cùng key hoặc bản đã trả','Không tạo thêm phạt hoặc thay đổi ngày trả.')
    def test_return_idempotent(self):
        self.late(8);a=self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');b=self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');c=self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r2');self.assertEqual(a,b);self.assertTrue(c['already_returned']);self.assertEqual(self.count('fines'),1)
    @case('TC-048','FR-09','Phạt lũy tiến các mốc 0,1,7,8,30,31 ngày','Kết quả 0,1000,7000,9000,53000,56000 VND.')
    def test_fine_boundaries(self):
        for d,expected in [(0,0),(1,1000),(7,7000),(8,9000),(30,53000),(31,56000)]:self.assertEqual(fine_amount(d,DEFAULT_POLICY)[0],expected)
    @case('TC-049','FR-09','Trễ một giây được làm tròn lên một ngày','Trả tại hạn đúng bằng 0; sau hạn một giây bằng 1000 VND.')
    def test_fine_rounding(self):
        self.issue();self.clock.advance(days=14,seconds=1);self.sql('UPDATE sessions SET last_active=?',(self.s.now(),));self.assertEqual(self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r')['fine'],1000)
    @case('TC-050','FR-09','Thay đổi chính sách không viết lại phạt phiếu cũ','Phiếu chụp mức 1000 vẫn phạt 9000 sau thay đổi mức 5000.')
    def test_policy_snapshot(self):
        self.issue();self.s.settings(self.admin,dict(daily_fine_rate=5000));self.clock.advance(days=22);self.sql('UPDATE sessions SET last_active=?',(self.s.now(),));self.assertEqual(self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r')['fine'],9000)
    @case('TC-051','FR-09','Ước tính trả sách không ghi phạt','Hiển thị dự kiến, không đổi phiếu hoặc kho.')
    def test_preview(self):self.late(8);r=self.s.preview_return(self.staff,'BK01-001');self.assertEqual(r['fine'],9000);self.assertTrue(r['estimate']);self.assertEqual(self.count('fines'),0);self.assertEqual(self.s.history(self.member)[0]['status'],'OPEN')
    @case('TC-052','FR-09','Thu một phần rồi thu hết','Sổ thu đúng tổng; dư nợ giảm về 0.')
    def test_payment_partial(self):f=self.fine();self.assertEqual(self.s.pay(self.staff,f['fine_id'],4000,'CASH','p1')['balance'],5000);self.assertEqual(self.s.pay(self.staff,f['fine_id'],5000,'TRANSFER','p2')['balance'],0);self.assertEqual(self.s.fines(self.member)[0]['paid'],9000)
    @case('TC-053','FR-09','Thu vượt dư nợ','Từ chối OVERPAYMENT và không ghi giao dịch.')
    def test_overpayment(self):f=self.fine();self.error('OVERPAYMENT',self.s.pay,self.staff,f['fine_id'],9001,'CASH','p');self.assertEqual(self.count('fine_payments'),0)
    @case('TC-054','FR-09','Số tiền 0, âm, thập phân, bool hoặc phương thức sai','Từ chối và giữ nguyên số dư.')
    def test_payment_validation(self):
        f=self.fine()
        for amount in [0,-1,1.2,True,'1000']:self.error('INVALID_INPUT',self.s.pay,self.staff,f['fine_id'],amount,'CASH','p')
        self.error('INVALID_INPUT',self.s.pay,self.staff,f['fine_id'],1,'CARD','p')
    @case('TC-055','FR-09','Gửi lại thanh toán cùng key','Chỉ một giao dịch được ghi, trả cùng biên nhận.')
    def test_payment_idempotent(self):f=self.fine();a=self.s.pay(self.staff,f['fine_id'],9000,'CASH','p');self.assertEqual(a,self.s.pay(self.staff,f['fine_id'],9000,'CASH','p'));self.assertEqual(self.count('fine_payments'),1)
    @case('TC-056','FR-09','Hai khoản thu đồng thời cùng dư nợ','Chỉ một khoản toàn dư nợ thành công; tổng thu không vượt phạt.')
    def test_payment_race(self):
        f=self.fine();barrier=threading.Barrier(2)
        def run(i):
            barrier.wait()
            try:self.s.pay(self.staff,f['fine_id'],9000,'CASH','p'+str(i));return True
            except RuleError:return False
        with ThreadPoolExecutor(2) as pool:out=list(pool.map(run,[1,2]))
        self.assertEqual(sum(out),1);self.assertEqual(self.count('fine_payments'),1)
    @case('TC-057','FR-03','Đặt trước đầu sách còn bản AVAILABLE','Từ chối AVAILABLE_TITLE.')
    def test_reserve_available(self):self.error('AVAILABLE_TITLE',self.s.reserve,self.member,1)
    @case('TC-058','FR-03','Đặt trước khi hết sách','Tạo WAITING, vị trí hàng chờ bằng 1.')
    def test_reserve(self):self.issue(['BK01-001','BK01-002','BK01-003'],2);self.s.reserve(self.member,1);r=self.s.reservations(self.member)[0];self.assertEqual(r['status'],'WAITING');self.assertEqual(r['queue_position'],1)
    @case('TC-059','FR-03','Đặt trước trùng đầu sách','Chỉ giữ một yêu cầu hoạt động cho cùng độc giả / sách.')
    def test_reserve_duplicate(self):self.issue(['BK01-001','BK01-002','BK01-003'],2);self.s.reserve(self.member,1);self.error('DUPLICATE_RESERVATION',self.s.reserve,self.member,1)
    @case('TC-060','FR-03','Trả sách phân bổ theo FIFO','Độc giả chờ trước nhận READY và copy HELD.')
    def test_fifo(self):
        self.issue(['BK01-001','BK01-002','BK01-003']);r=self.s.reserve(self.member,1);self.s.reserve(self.second,1);self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');row=self.sql('SELECT status,copy_id FROM reservations WHERE id=?',(r['id'],))[0];self.assertEqual(row,dict(status='READY',copy_id=1));self.assertEqual(self.s.book(1)['copies'][0]['status'],'HELD')
    @case('TC-061','FR-03','Hủy READY chuyển bản giữ cho người tiếp theo','Yêu cầu đầu CANCELLED, yêu cầu sau READY cùng bản sao.')
    def test_cancel_reallocate(self):
        self.issue(['BK01-001','BK01-002','BK01-003']);r=self.s.reserve(self.member,1);r2=self.s.reserve(self.second,1);self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');self.s.cancel_reservation(self.member,r['id']);self.assertEqual(self.sql('SELECT status FROM reservations WHERE id=?',(r2['id'],))[0]['status'],'READY')
    @case('TC-062','FR-03','Hết hạn giữ chỗ sau đúng pickup_hours','READY hết hạn thành EXPIRED và chuyển bản cho người tiếp theo.')
    def test_expire_hold(self):
        self.issue(['BK01-001','BK01-002','BK01-003']);r=self.s.reserve(self.member,1);r2=self.s.reserve(self.second,1);self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');self.clock.advance(hours=48);self.sql('UPDATE sessions SET last_active=?',(self.s.now(),));self.s.reservations(self.member);self.assertEqual(self.sql('SELECT status FROM reservations WHERE id=?',(r['id'],))[0]['status'],'EXPIRED');self.assertEqual(self.sql('SELECT status FROM reservations WHERE id=?',(r2['id'],))[0]['status'],'READY')
    @case('TC-063','FR-03','Người khác không được mượn bản HELD','Chặn copy giữ cho độc giả khác, chủ sở hữu được nhận.')
    def test_hold_ownership(self):
        self.issue(['BK01-001','BK01-002','BK01-003'],2);self.s.reserve(self.member,1);self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');self.error('COPY_UNAVAILABLE',self.issue,['BK01-001'],2,'wrong');self.issue(['BK01-001'],1,'own');self.assertEqual(self.s.reservations(self.member)[0]['status'],'FULFILLED')
    @case('TC-064','FR-03','Không hủy đặt trước người khác','Từ chối FORBIDDEN và không đổi trạng thái.')
    def test_cancel_ownership(self):self.issue(['BK01-001','BK01-002','BK01-003']);r=self.s.reserve(self.member,1);self.error('FORBIDDEN',self.s.cancel_reservation,self.second,r['id'])
    @case('TC-065','FR-03','Bỏ qua người chờ không đủ điều kiện khi phân bổ','Người hợp lệ kế tiếp được READY; người bị khóa vẫn WAITING.')
    def test_allocate_eligible(self):
        self.issue(['BK01-001','BK01-002','BK01-003']);r=self.s.reserve(self.member,1);r2=self.s.reserve(self.second,1);self.sql("UPDATE members SET status='INACTIVE' WHERE id=1");self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');self.assertEqual(self.sql('SELECT status FROM reservations WHERE id=?',(r['id'],))[0]['status'],'WAITING');self.assertEqual(self.sql('SELECT status FROM reservations WHERE id=?',(r2['id'],))[0]['status'],'READY')
    @case('TC-066','FR-04','Gia hạn hợp lệ','Cộng 7 ngày vào hạn cũ, tăng renewal_count một lần.')
    def test_renew(self):r=self.issue();out=self.s.renew(self.member,r['detail_ids'][0],'renew');self.assertEqual(datetime.fromisoformat(out['due_date']),datetime.fromisoformat(r['due_date'])+timedelta(days=7));self.assertEqual(out['renewal_count'],1)
    @case('TC-067','FR-04','Gia hạn gửi lại cùng key','Không cộng thêm ngày hoặc thêm lượt.')
    def test_renew_idempotent(self):r=self.issue();a=self.s.renew(self.member,r['detail_ids'][0],'renew');self.assertEqual(a,self.s.renew(self.member,r['detail_ids'][0],'renew'));self.assertEqual(self.s.history(self.member)[0]['renewal_count'],1)
    @case('TC-068','FR-04','Hết lượt gia hạn','Từ chối RENEWAL_LIMIT, giữ nguyên hạn đã gia hạn.')
    def test_renew_limit(self):r=self.issue();self.s.renew(self.member,r['detail_ids'][0],'r1');self.error('RENEWAL_LIMIT',self.s.renew,self.member,r['detail_ids'][0],'r2')
    @case('TC-069','FR-04','Gia hạn phiếu của người khác','Từ chối FORBIDDEN.')
    def test_renew_ownership(self):r=self.issue();self.error('FORBIDDEN',self.s.renew,self.second,r['detail_ids'][0],'r')
    @case('TC-070','FR-04','Gia hạn khi có đầu sách đang chờ','Từ chối RESERVATION_CONFLICT.')
    def test_renew_queue(self):r=self.issue(['BK01-001','BK01-002','BK01-003']);self.s.reserve(self.second,1);self.error('RESERVATION_CONFLICT',self.s.renew,self.member,r['detail_ids'][0],'r')
    @case('TC-071','FR-04','Gia hạn khi có sách quá hạn','Từ chối INELIGIBLE dù còn lượt gia hạn.')
    def test_renew_overdue(self):r=self.late(1);self.error('INELIGIBLE',self.s.renew,self.member,r['detail_ids'][0],'r')
    @case('TC-072','FR-04','Gia hạn bản đã trả','Từ chối CONFLICT.')
    def test_renew_returned(self):r=self.issue();self.s.return_copy(self.staff,'BK01-001','AVAILABLE','r');self.error('CONFLICT',self.s.renew,self.member,r['detail_ids'][0],'new')
    @case('TC-073','FR-05','Lịch sử chỉ có dữ liệu của chính độc giả','Không lộ phiếu của người khác; tham số member_id khác bị từ chối.')
    def test_history_ownership(self):self.issue();self.issue(['BK02-001'],2,'second');self.assertEqual(len(self.s.history(self.member)),1);self.error('FORBIDDEN',self.s.history,self.member,2)
    @case('TC-074','FR-09','Bảng phạt giới hạn theo độc giả','Không lộ khoản phạt của người khác.')
    def test_fine_ownership(self):self.fine();self.assertEqual(self.s.fines(self.second),[]);self.error('FORBIDDEN',self.s.fines,self.member,2)
    @case('TC-075','FR-12','Thủ thư tạo độc giả','Tạo đồng thời tài khoản MEMBER và hồ sơ.')
    def test_create_member(self):r=self.s.save_member(self.staff,dict(username='reader',email='r@example.com',full_name='R',password='Passphrase!2026'));self.assertEqual(self.sql('SELECT role FROM accounts WHERE id=?',(r['account_id'],))[0]['role'],'MEMBER')
    @case('TC-076','FR-12','Sửa hồ sơ và vô hiệu hóa thẻ','Lưu họ tên / liên hệ, giữ lịch sử và thu hồi phiên độc giả.')
    def test_edit_member(self):self.issue();self.s.save_member(self.staff,dict(full_name='Tên mới',phone='0901234567',address='Địa chỉ',status='INACTIVE'),1);self.assertEqual(self.count('loans'),1);self.error('SESSION_EXPIRED',self.s.me,self.member);self.assertEqual(self.s.members(self.staff)[0]['full_name'],'Tên mới')
    @case('TC-077','FR-12','Liên hệ sai hoặc thẻ không tồn tại','Từ chối, không thay đổi dữ liệu.')
    def test_member_validation(self):self.error('INVALID_INPUT',self.s.save_member,self.staff,dict(full_name='R',phone='abc'),1);self.error('NOT_FOUND',self.s.save_member,self.staff,dict(full_name='R'),999)
    @case('TC-078','FR-10','Quản trị tạo thủ thư','Tài khoản LIBRARIAN có hồ sơ staff tương thích.')
    def test_create_staff(self):r=self.s.save_account(self.admin,dict(username='staff2',email='staff2@example.com',full_name='Staff',password='Passphrase!2026',role='LIBRARIAN'));self.assertEqual(self.sql('SELECT account_id FROM staff WHERE id=?',(r['profile_id'],))[0]['account_id'],r['account_id'])
    @case('TC-079','FR-10','Không bỏ quản trị viên cuối cùng','Từ chối LAST_ADMIN khi khóa hoặc giáng quyền.')
    def test_last_admin(self):
        for d in [dict(role='ADMINISTRATOR',status='INACTIVE'),dict(role='LIBRARIAN',status='ACTIVE')]:self.error('LAST_ADMIN',self.s.save_account,self.admin,d,1)
    @case('TC-080','FR-10','Không đổi chéo MEMBER và STAFF','Từ chối PROFILE_CONFLICT.')
    def test_profile_role(self):self.error('PROFILE_CONFLICT',self.s.save_account,self.admin,dict(role='LIBRARIAN'),3);self.error('PROFILE_CONFLICT',self.s.save_account,self.admin,dict(role='MEMBER'),2)
    @case('TC-081','FR-10','Đổi vai trò nhân viên thu hồi phiên cũ','Thủ thư lên ADMINISTRATOR nhưng token cũ mất hiệu lực.')
    def test_role_revoke(self):self.s.save_account(self.admin,dict(role='ADMINISTRATOR'),2);self.error('SESSION_EXPIRED',self.s.me,self.staff)
    @case('TC-082','FR-10','Lưu chính sách hợp lệ','Lưu đồng bộ và dùng cho phiếu mượn mới.')
    def test_settings(self):self.s.settings(self.admin,dict(loan_days=21,max_active_copies=3));r=self.issue();self.assertEqual(datetime.fromisoformat(r['due_date']),self.clock()+timedelta(days=21))
    @case('TC-083','FR-10','Chính sách mốc / hệ số / kiểu dữ liệu không hợp lệ','Từ chối toàn bộ thay đổi; chính sách cũ còn nguyên.')
    def test_policy_invalid(self):
        for d in [dict(band1_days=30,band2_days=7),dict(multiplier2=1),dict(multiplier2=4,multiplier3=3),dict(loan_days=0),dict(max_active_copies=True),dict(unknown=1)]:
            with self.assertRaises(RuleError):self.s.settings(self.admin,d)
        self.assertEqual(self.s.settings(self.admin),DEFAULT_POLICY)
    @case('TC-084','NFR-05','Ma trận phân quyền cho độc giả','Chặn quản trị / kho / mượn trả / thu tiền / báo cáo / hồ sơ người khác.')
    def test_member_permissions(self):
        calls=[(self.s.accounts,(self.member,)),(self.s.settings,(self.member,)),(self.s.members,(self.member,)),(self.s.save_book,(self.member,self.book_data())),(self.s.checkout,(self.member,1,['BK01-001'],'k')),(self.s.return_copy,(self.member,'BK01-001','AVAILABLE','k')),(self.s.pay,(self.member,1,1,'CASH','k')),(self.s.report,(self.member,self.s.now(),(self.clock()+timedelta(days=1)).isoformat()))]
        for fn,args in calls:self.error('FORBIDDEN',fn,*args)
    @case('TC-085','NFR-05','Thủ thư không được quản trị tài khoản / chính sách','Từ chối FORBIDDEN dù giao diện bị bỏ qua.')
    def test_librarian_permissions(self):self.error('FORBIDDEN',self.s.accounts,self.staff);self.error('FORBIDDEN',self.s.settings,self.staff,dict(loan_days=2));self.error('FORBIDDEN',self.s.save_account,self.staff,dict(role='MEMBER'))
    @case('TC-086','NFR-05','Yêu cầu bảo vệ không có token','Từ chối SESSION_EXPIRED; catalog vẫn công khai.')
    def test_guest_permissions(self):self.error('SESSION_EXPIRED',self.s.history,'');self.error('SESSION_EXPIRED',self.s.members,'');self.assertGreater(self.s.catalog()['total'],0)
    @case('TC-087','FR-11','Báo cáo theo khoảng nửa mở [start,end)','Khoản đúng start được tính; đúng end bị loại.')
    def test_report_dates(self):
        self.issue();start=self.s.now();end=(self.clock()+timedelta(days=1)).isoformat();r=self.s.report(self.staff,start,end);self.assertEqual(r['borrowed'],1);r2=self.s.report(self.staff,(self.clock()-timedelta(days=1)).isoformat(),start);self.assertEqual(r2['borrowed'],0)
    @case('TC-088','FR-11','Báo cáo đối soát thể loại và tiền thu','Tổng nhóm bằng tổng mượn; nhiều thanh toán không nhân đôi lượt mượn.')
    def test_report_reconcile(self):
        f=self.fine();self.s.pay(self.staff,f['fine_id'],4000,'CASH','p1');self.s.pay(self.staff,f['fine_id'],5000,'CASH','p2');r=self.s.report(self.admin,'2026-01-01T00:00:00+00:00','2027-01-01T00:00:00+00:00');self.assertEqual(r['borrowed'],1);self.assertEqual(sum(g['borrowed'] for g in r['by_category']),1);self.assertEqual(r['collected'],9000);self.assertEqual(len(r['payments']),2)
    @case('TC-089','FR-11','Báo cáo rỗng / khoảng sai','Khoảng hợp lệ rỗng trả 0; khoảng đảo ngược hoặc thiếu múi giờ bị từ chối.')
    def test_report_validation(self):
        r=self.s.report(self.staff,'2025-01-01T00:00:00+00:00','2025-02-01T00:00:00+00:00');self.assertEqual(r['borrowed'],0)
        for dates in [('bad','bad'),('2026-02-01','2026-01-01')]:self.error('INVALID_DATE',self.s.report,self.staff,*dates)
    @case('TC-090','FR-01','Cập nhật hồ sơ cá nhân','Lưu họ tên / liên hệ của chính tài khoản.')
    def test_profile(self):self.s.update_profile(self.member,dict(full_name='Người đọc',phone='0901234567',address='Thư viện'));self.assertEqual(self.s.me(self.member)['profile']['full_name'],'Người đọc')
    @case('TC-091','FR-01','Đổi mật khẩu','Mật khẩu cũ hết hiệu lực; mật khẩu mới dùng được; mọi phiên cũ bị thu hồi.')
    def test_password_change(self):self.s.change_password(self.member,'LibraryDemo!2026','NewPassphrase!2026');self.error('SESSION_EXPIRED',self.s.me,self.member);self.error('AUTH_FAILED',self.s.login,'member','LibraryDemo!2026');self.assertIn('token',self.s.login('member','NewPassphrase!2026'))
    @case('TC-092','FR-01','Đổi mật khẩu sai mật khẩu hiện tại / mật khẩu mới ngắn','Từ chối, mật khẩu hiện tại không đổi.')
    def test_password_change_invalid(self):self.error('AUTH_FAILED',self.s.change_password,self.member,'wrong','NewPassphrase!2026');self.error('INVALID_INPUT',self.s.change_password,self.member,'LibraryDemo!2026','short');self.s.me(self.member)
    @case('TC-093','NFR-07','Sao lưu mã hóa và khôi phục sang DB mới','Snapshot hợp lệ, số bản ghi / tổng tiền giữ nguyên; phiên cũ không phục hồi.')
    def test_backup_restore(self):
        f=self.fine();self.s.pay(self.staff,f['fine_id'],9000,'CASH','p');backup=Path(self.tmp.name)/'backup.lmb';self.s.backup(self.admin,backup,'BackupPassword!2026');self.assertNotIn(b'SQLite format 3',backup.read_bytes());restored=Path(self.tmp.name)/'restored.db';self.s.restore_backup(backup,'BackupPassword!2026',restored)
        with closing(sqlite3.connect(restored)) as c:self.assertEqual(c.execute('SELECT SUM(amount) FROM fine_payments').fetchone()[0],9000);self.assertEqual(c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    @case('TC-094','NFR-07','Khôi phục sai mật khẩu / ghi đè DB','Từ chối và không tạo file đích lỗi; không ghi đè database hiện hữu.')
    def test_backup_invalid(self):
        backup=Path(self.tmp.name)/'backup.lmb';self.s.backup(self.admin,backup,'BackupPassword!2026');target=Path(self.tmp.name)/'restore.db';self.error('INVALID_BACKUP',self.s.restore_backup,backup,'wrong',target);self.assertFalse(target.exists());self.error('CONFLICT',self.s.restore_backup,backup,'BackupPassword!2026',self.path)
    @case('TC-095','NFR-07','Chỉ quản trị được tạo backup','Thủ thư bị từ chối; mật khẩu backup ngắn bị từ chối.')
    def test_backup_permissions(self):self.error('FORBIDDEN',self.s.backup,self.staff,Path(self.tmp.name)/'b','BackupPassword!2026');self.error('INVALID_INPUT',self.s.backup,self.admin,Path(self.tmp.name)/'b','short')
    @case('TC-096','FR-07','Giữ toàn vẹn dữ liệu và audit sau quy trình hoàn chỉnh','Foreign key check rỗng, không mất lịch sử, audit có thao tác mượn trả thu tiền.')
    def test_integrity_audit(self):
        f=self.fine();self.s.pay(self.staff,f['fine_id'],9000,'CASH','p');self.assertEqual(self.sql('PRAGMA foreign_key_check'),[]);self.assertEqual(self.count('loans'),1);actions={r['action'] for r in self.sql('SELECT action FROM audit')};self.assertTrue({'CHECKOUT','RETURN','PAYMENT'}<=actions)
