import importlib.util
import sys
import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timedelta, timezone

import Source_code as m

class DiagramTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)
        self.s = m.LibraryService(Path(self.tmp.name) / 'test.sqlite3', lambda: self.now)
        m.seed_figma_demo(self.s)
        self.token = self.s.login('thinh.nguyen', 'LibraryDemo!2026')['token']

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_uml_fields_and_methods(self):
        fields = [
            (m.Author(), 'authorId authorName'),
            (m.Publisher(), 'publisherId publisherName phone'),
            (m.Category(), 'categoryId categoryName description'),
            (m.Book(), 'bookId isbn title publicationYear description bookStatus'),
            (m.BookCopy('x', 'AVAILABLE'), 'copyId barcode copyStatus shelfLocation'),
            (m.Account(), 'accountId username email passwordHash role status createdAt updatedAt'),
            (m.Member(), 'memberId fullName phone address registrationDate memberStatus'),
            (m.Staff(), 'staffId fullName phone hireDate'),
            (m.Loan(), 'loanId loanDate loanStatus'),
            (m.LoanDetail(self.now), 'loanDetailId dueDate returnDate renewalCount detailStatus'),
            (m.Reservation(), 'reservationId reservationDate expiryDate queuePosition status'),
            (m.Fine(1000), 'fineId amount reason fineStatus issuedAt'),
            (m.FinePayment(), 'paymentId amount paymentDate paymentMethod'),
            (m.SystemSetting(), 'settingKey settingValue description updatedAt'),
        ]
        for obj, names in fields:
            for name in names.split():
                with self.subTest(cls=type(obj).__name__, field=name):
                    self.assertTrue(hasattr(obj, name))
        self.assertIsInstance(m.Member(), m.Account)
        self.assertIsInstance(m.Staff(), m.Account)
        for cls, names in [(m.Account, 'login logout changePassword'), (m.Member, 'canBorrow viewHistory'), (m.Staff, 'issueLoan processReturn collectFine'), (m.LoanDetail, 'renew isOverdue overdueDays'), (m.BookCopy, 'markBorrowed markAvailable'), (m.Book, 'countAvailable'), (m.Loan, 'addItem')]:
            for name in names.split():
                self.assertTrue(callable(getattr(cls, name)))

    def test_book_graph_and_copy_transition(self):
        book = self.s.load_book(1)
        self.assertEqual(book.countAvailable(), 8)
        self.assertIsInstance(book.authors[0], m.Author)
        self.assertIsInstance(book.category, m.Category)
        self.assertIsInstance(book.publisher, m.Publisher)
        copy = next(c for c in book.copies if c.status == 'AVAILABLE')
        borrowed = copy.markBorrowed()
        self.assertEqual(borrowed.copyId, copy.copyId)
        self.assertEqual(borrowed.shelfLocation, copy.shelfLocation)
        self.assertEqual(borrowed.markAvailable().status, 'AVAILABLE')

    def test_full_object_workflow_and_persistence(self):
        staff = self.s.load_account(self.token)
        self.assertIsInstance(staff, m.Staff)
        member_token = self.s.login('phucthinh', 'LibraryDemo!2026')['token']
        member = self.s.load_account(member_token)
        self.assertTrue(member.registrationDate)
        self.assertTrue(member.canBorrow())
        loan = staff.issueLoan(member.memberId, ['NV6-0021'])
        self.assertIsInstance(loan, m.Loan)
        self.assertIsInstance(loan.member, m.Member)
        self.assertIsInstance(loan.staff, m.Staff)
        self.assertEqual(loan.details[0].copy.copyId, loan.copies[0].copyId)
        detail = self.s.load_loan(member_token, loan.loanId).details[0]
        old_due = detail.dueDate
        self.assertTrue(detail.renew())
        self.assertGreater(detail.dueDate, old_due)
        self.assertEqual(detail.renewalCount, 1)
        self.assertTrue(any(r['loan_id'] == loan.loanId for r in member.viewHistory()))
        self.now = detail.dueDate + timedelta(days=8)
        self.token = self.s.login('thinh.nguyen', 'LibraryDemo!2026')['token']
        staff = self.s.load_account(self.token)
        returned = staff.processReturn('NV6-0021')
        self.assertGreater(returned['fine'], 0)
        partial = staff.collectFine(returned['fine_id'], 1000)
        self.assertEqual(partial['balance'], returned['fine'] - 1000)
        graph = self.s.load_loan(self.token, loan.loanId)
        fine = graph.details[0].fine
        self.assertEqual(fine.fineStatus, 'PARTIAL')
        self.assertEqual(fine.payments[0].paymentId, partial['payment_id'])
        staff.collectFine(fine.fineId, fine.balance)
        restarted = m.LibraryService(self.s.db.path, lambda: self.now)
        self.assertEqual(restarted.load_loan(self.token, loan.loanId).details[0].fine.fineStatus, 'PAID')

    def test_login_logout_change_password(self):
        account = m.Account(username='phucthinh')
        self.assertTrue(account.login('LibraryDemo!2026', self.s))
        account.changePassword('LibraryDemo!2026', 'ChangedDemo!2026')
        with self.assertRaises(m.RuleError):
            self.s.login('phucthinh', 'LibraryDemo!2026')
        account.login('ChangedDemo!2026', self.s)
        token = account._token
        account.logout()
        with self.assertRaises(m.RuleError):
            self.s.me(token)

    def test_object_methods_keep_authorization(self):
        token = self.s.login('phucthinh', 'LibraryDemo!2026')['token']
        forged = m.Staff().bind(self.s, token)
        with self.assertRaises(m.RuleError):
            forged.issueLoan(24, ['NV6-0021'])
        with self.assertRaises(m.RuleError):
            self.s.load_loan(token, 1)
        with self.assertRaises(m.RuleError):
            self.s.load_account(token, 1)

    def test_upgrade_existing_database(self):
        old = Path(self.tmp.name) / 'old.sqlite3'
        with closing(sqlite3.connect(old)) as c, c:
            c.executescript(m.SCHEMA)
            c.execute("INSERT INTO accounts VALUES(1,'old','old@example.com','hash','MEMBER','ACTIVE','2026-01-01')")
            c.execute("INSERT INTO members VALUES(1,1,'Old Name','','','ACTIVE')")
        m.Database(old)
        m.Database(old)
        with closing(sqlite3.connect(old)) as c:
            self.assertEqual(c.execute('SELECT registration_date FROM members').fetchone()[0], '2026-01-01')
            self.assertEqual(c.execute('SELECT updated_at FROM accounts').fetchone()[0], '2026-01-01')

if __name__ == '__main__':
    unittest.main(verbosity=2)
