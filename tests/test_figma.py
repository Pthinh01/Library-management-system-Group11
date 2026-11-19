"""Regression cases for the new screen contracts and the Figma demo."""
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from Source_code import LibraryService, RuleError
from Source_code import seed_figma_demo
from Source_code import LoanDetail, Fine
from tests.test_library import Clock, case


class FigmaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.service = LibraryService(Path(self.tmp.name)/'demo.db', self.clock)
        seed_figma_demo(self.service)
        self.token = self.service.login('thinh.nguyen','LibraryDemo!2026')['token']

    def tearDown(self):
        self.tmp.cleanup()

    @case('TC-106','FIG-02','Đăng ký mật khẩu đúng biên 8 ký tự','8 ký tự hợp lệ; 7 ký tự bị từ chối.')
    def test_password_boundary(self):
        data=dict(username='boundary',email='boundary@example.com',full_name='Test Boundary',password='12345678',confirmation='12345678')
        self.assertGreater(self.service.register(data)['account_id'],0)
        data.update(username='shortpw',email='short@example.com',password='1234567',confirmation='1234567')
        with self.assertRaises(RuleError):self.service.register(data)

    @case('TC-107','FIG-09','Tra cứu mã vạch thực tế','NV6-0021 sẵn sàng và có tên sách; mã sai trả NOT_FOUND.')
    def test_lookup_copy(self):
        copy=self.service.lookup_copy(self.token,'NV6-0021')
        self.assertEqual(copy['status'],'AVAILABLE');self.assertEqual(copy['title'],'Ngữ văn 6 · Tập 2')
        with self.assertRaises(RuleError):self.service.lookup_copy(self.token,'missing')

    @case('TC-108','FIG-10','Chặn người còn sách trễ hạn','DG-0018 bị chặn dù chưa phát sinh hóa đơn phạt; vẫn nhận trả được.')
    def test_blocked_can_return(self):
        result=self.service.eligibility(self.token,18,1)
        self.assertFalse(result['eligible']);self.assertEqual(result['balance'],0)
        self.assertIn('OVERDUE_UNRETURNED',result['reasons'])
        self.assertEqual(self.service.return_copy(self.token,'NV6-0018','AVAILABLE','figma-return')['fine'],9000)

    @case('TC-109','FIG-03','Tổng quan lấy số liệu từ dữ liệu','Số đang mượn giảm sau trả; không hiển thị số cố định từ ảnh.')
    def test_live_dashboard(self):
        before=self.service.dashboard(self.token)
        self.service.return_copy(self.token,'NV6-0018','AVAILABLE','return-dashboard')
        after=self.service.dashboard(self.token)
        self.assertEqual(after['open'],before['open']-1);self.assertEqual(after['overdue'],before['overdue']-1)

    @case('TC-110','FIG-18','Báo cáo sau khi nhận trả','Báo cáo có số trả thực tế và số đang mượn, quá hạn.')
    def test_report_counts(self):
        start=(self.clock()-timedelta(days=60)).isoformat();end=(self.clock()+timedelta(days=1)).isoformat()
        a=self.service.report(self.token,start,end)
        self.service.return_copy(self.token,'NV6-0018','AVAILABLE','return-report')
        b=self.service.report(self.token,start,end)
        self.assertEqual(b['returned'],a['returned']+1);self.assertEqual(b['open'],a['open']-1)

    @case('TC-111','FIG-19','Tài khoản trả đúng họ tên','API tài khoản có full_name và email để tìm kiếm.')
    def test_account_names(self):
        admin=self.service.login('admin','LibraryDemo!2026')['token']
        rows=self.service.accounts(admin)
        thinh=next(a for a in rows if a['username']=='thinh.nguyen')
        self.assertEqual(thinh['full_name'],'Nguyễn Phúc Thịnh')
        self.assertEqual(thinh['email'],'nguyenphucthinh23062006@gmail.com')

    @case('TC-112','FIG-13','Đối tượng chi tiết mượn tính ngày trễ','Đúng hạn 0; trễ một giây 1; đã trả không tiếp tục tăng.')
    def test_domain_days(self):
        now=self.clock();self.assertEqual(LoanDetail(now).overdue_days(now),0)
        self.assertEqual(LoanDetail(now).overdue_days(now+timedelta(seconds=1)),1)
        self.assertEqual(LoanDetail(now,now+timedelta(days=2)).overdue_days(now+timedelta(days=10)),2)
        self.assertEqual(Fine(9000,4000).balance,5000)

    @case('TC-113','FIG-01','Khởi tạo lại không đè dữ liệu','Chạy seed lần hai giữ nguyên số tài khoản và phiếu.')
    def test_seed_idempotent(self):
        with self.service.db.transaction(False) as c:before=c.execute('SELECT COUNT(*) FROM loans').fetchone()[0]
        seed_figma_demo(self.service)
        with self.service.db.transaction(False) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM loans').fetchone()[0],before)

    @case('TC-114','FIG-15','Lịch sử biên nhận và quyền riêng tư','Thủ thư thấy biên nhận; độc giả khác không thấy giao dịch của Nam.')
    def test_payment_history(self):
        returned=self.service.return_copy(self.token,'NV6-0018','AVAILABLE','receipt-return')
        payment=self.service.pay(self.token,returned['fine_id'],9000,'CASH','receipt-pay')
        rows=self.service.payments(self.token)
        self.assertEqual(rows[0]['id'],payment['payment_id']);self.assertEqual(rows[0]['amount'],9000)
        reader=self.service.login('phucthinh','LibraryDemo!2026')['token']
        self.assertEqual(self.service.payments(reader),[])

    @case('TC-115','FIG-04','Lọc sách trước phân trang','Còn sách chỉ có AVAILABLE; Đang mượn chỉ có ON_LOAN, không nhận nhầm HELD.')
    def test_catalog_filters(self):
        available=self.service.catalog(availability='available',page_size=1)
        self.assertEqual(available['total'],3);self.assertEqual(len(available['items']),1)
        borrowed=self.service.catalog(availability='borrowed')
        self.assertEqual({b['id'] for b in borrowed['items']},{1,4})
        with self.assertRaises(RuleError):self.service.catalog(availability='invalid')

    @case('TC-116','FIG-16','Tổng hợp sách mượn của chính độc giả','Trả 1/5 quyển, dư nợ 0; không cho thủ thư gọi nhầm API độc giả.')
    def test_member_summary(self):
        token=self.service.login('phucthinh','LibraryDemo!2026')['token']
        result=self.service.member_summary(token)
        self.assertEqual(result['open_count'],1);self.assertEqual(result['limit'],5)
        self.assertEqual(result['balance'],0);self.assertEqual(result['overdue_details'],[])
        with self.assertRaises(RuleError):self.service.member_summary(self.token)

    @case('TC-117','OOP','Đối tượng nghiệp vụ và kế thừa','Member/Staff kế thừa Account; Book/Loan/Reservation/Fine chuyển trạng thái đúng và chặn dữ liệu sai.')
    def test_entity_behaviors(self):
        from Source_code import Account, Member, Staff, Book, BookCopy, Loan, Reservation, SystemSetting
        self.assertIsInstance(Member(),Account);self.assertIsInstance(Staff(),Account)
        self.assertFalse(Member(overdue_count=1).can_borrow())
        copy=BookCopy('TEST-001','AVAILABLE')
        self.assertEqual(Book().count_available([copy,copy.mark_borrowed()]),1)
        loan=Loan();loan.add_item(copy)
        with self.assertRaises(ValueError):loan.add_item(copy)
        reservation=Reservation(status='READY');reservation.fulfill();self.assertEqual(reservation.status,'FULFILLED')
        with self.assertRaises(ValueError):reservation.cancel()
        self.assertEqual(Fine(9000).pay(4000).balance,5000)
        with self.assertRaises(ValueError):Fine(9000).pay(9001)
        self.assertEqual(SystemSetting('loan_days','14').get('loan_days'),'14')
