"""HTTP-level integration tests against a real loopback server."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

from Source_code import LibraryService
from Source_code import make_handler
from test_library import case

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.service=LibraryService(Path(cls.tmp.name)/'http.db');cls.service.seed_demo()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.service))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.port=cls.server.server_port
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()
    def request(self,path,body=None,headers=None,method=None):
        h={'Host':f'127.0.0.1:{self.port}'}
        if body is not None:h.update({'Content-Type':'application/json','X-Requested-With':'LibraryUI'})
        h.update(headers or {})
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        try:
            c.request(method or ('POST' if body is not None else 'GET'),path,json.dumps(body).encode() if body is not None else None,h)
            r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def login(self,identity='member'):
        status,h,b=self.request('/api/login',dict(identity=identity,password='LibraryDemo!2026'));self.assertEqual(status,200)
        cookie=h['Set-Cookie'].split(';')[0];csrf=json.loads(b)['data']['csrf'];return dict(Cookie=cookie,**{'X-CSRF-Token':csrf})
    @case('TC-097','NFR-05','Cookie phiên và security headers','Cookie HttpOnly, SameSite=Strict; không trả session token trong JSON.')
    def test_cookie_headers(self):
        status,h,b=self.request('/api/login',dict(identity='member',password='LibraryDemo!2026'));self.assertEqual(status,200);self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie']);self.assertNotIn('token',json.loads(b)['data']);self.assertEqual(h['X-Content-Type-Options'],'nosniff');self.assertIn("frame-ancestors 'none'",h['Content-Security-Policy'])
    @case('TC-098','NFR-05','Mutation không có mã CSRF','Đăng nhập rồi POST thiếu CSRF bị từ chối 403.')
    def test_csrf_missing(self):
        h=self.login();h.pop('X-CSRF-Token');status,_,body=self.request('/api/profile',dict(full_name='N'),h);self.assertEqual(status,403);self.assertEqual(json.loads(body)['error'],'CSRF_DENIED')
    @case('TC-099','NFR-05','Origin khác nguồn và Host không hợp lệ','Yêu cầu từ website khác / Host không localhost bị chặn.')
    def test_origin_host(self):
        h=self.login();h['Origin']='https://example.org';self.assertEqual(self.request('/api/profile',dict(full_name='N'),h)[0],403);self.assertEqual(self.request('/api/catalog',headers={'Host':'evil.example'})[0],403)
    @case('TC-100','FR-01','Đăng xuất qua HTTP','Cookie bị xóa và phát lại cookie cũ trả 401.')
    def test_logout_cookie(self):
        h=self.login();self.assertEqual(self.request('/api/logout',{},h)[0],200);self.assertEqual(self.request('/api/history',headers=h)[0],401)
    @case('TC-101','FR-02','Catalog và health thực sự qua HTTP','200 JSON đúng dữ liệu, health có đọc database.')
    def test_catalog_health(self):
        self.assertEqual(json.loads(self.request('/api/health')[2])['data']['status'],'ok');self.assertEqual(json.loads(self.request('/api/catalog?q=9786040000001')[2])['data']['total'],1)
    @case('TC-102','NFR-05','Chặn gọi API quản trị trực tiếp bằng cookie MEMBER','GET accounts trả 403 dù bỏ qua giao diện.')
    def test_authorization_http(self):self.assertEqual(self.request('/api/accounts',headers=self.login())[0],403)
    @case('TC-103','FR-01','JSON sai dạng / Content-Type sai / id sai','Trả 400 hoặc 415 rõ ràng, không lộ traceback.')
    def test_invalid_contract(self):
        self.assertEqual(self.request('/api/login',[],{})[0],400);self.assertEqual(self.request('/api/login',{}, {'Content-Type':'text/plain'})[0],415);s,_,b=self.request('/api/book?id=bad');self.assertEqual(s,400);self.assertNotIn(b'Traceback',b)
    @case('TC-104','NFR-08','Tài nguyên giao diện thực tế','HTML tiếng Việt, CSS responsive và JS được tải đúng MIME; đường dẫn file tùy ý bị chặn.')
    def test_static(self):
        s,h,b=self.request('/');self.assertEqual(s,200);self.assertIn(b'lang="vi"',b);self.assertIn('text/html',h['Content-Type']);self.assertIn(b'@media',self.request('/style.css')[2]);self.assertIn('javascript',self.request('/app.js')[1]['Content-Type']);self.assertEqual(self.request('/../../library/service.py')[0],404)
    @case('TC-105','FR-11','Xuất CSV báo cáo','CSV có BOM UTF-8, Content-Disposition tải file và tổng dữ liệu.')
    def test_csv(self):
        h=self.login('librarian');s,headers,b=self.request('/api/report.csv?start=2026-01-01T00:00:00%2B00:00&end=2027-01-01T00:00:00%2B00:00',headers=h);self.assertEqual(s,200);self.assertTrue(b.startswith(b'\xef\xbb\xbf'));self.assertIn('attachment',headers['Content-Disposition']);self.assertIn('Tổng',b.decode('utf-8-sig'))
