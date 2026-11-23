"""Verify the HTTPS proxy contract without contacting GitHub."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from Source_code import LibraryService
from Source_code import make_handler
from test_library import case


class CodespacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.service=LibraryService(Path(cls.tmp.name)/'proxy.db')
        cls.service.seed_demo()
        cls.origin='https://effective-spork-test-8765.app.github.dev'
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.service,cls.origin))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()

    def request(self,path,body=None,host=None,origin=None):
        headers={'Host':host or self.origin.removeprefix('https://')}
        if origin:headers['Origin']=origin
        if body is not None:headers.update({'Content-Type':'application/json','X-Requested-With':'LibraryUI'})
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            connection.request('POST' if body is not None else 'GET',path,json.dumps(body).encode() if body is not None else None,headers)
            response=connection.getresponse();return response.status,dict(response.getheaders()),response.read()
        finally:connection.close()

    @case('TC-118','CODESPACES','Tên miền proxy chính xác','Host HTTPS của Codespace truy cập health thành công.')
    def test_forwarded_host(self):
        self.assertEqual(self.request('/api/health')[0],200)

    @case('TC-119','CODESPACES','Đăng nhập qua HTTPS proxy','Origin đúng đăng nhập được, cookie có Secure, HttpOnly và SameSite=Strict.')
    def test_https_login_cookie(self):
        status,headers,_=self.request('/api/login',dict(identity='librarian',password='LibraryDemo!2026'),origin=self.origin)
        self.assertEqual(status,200)
        for value in ['Secure','HttpOnly','SameSite=Strict']:self.assertIn(value,headers['Set-Cookie'])

    @case('TC-120','CODESPACES','Origin giả mạo bị chặn','Không chấp nhận HTTP, tên miền gần giống hoặc website khác.')
    def test_wrong_origins(self):
        for origin in [self.origin.replace('https:','http:'),self.origin+'.evil.example','https://evil.example']:
            self.assertEqual(self.request('/api/login',dict(identity='librarian',password='LibraryDemo!2026'),origin=origin)[0],403)

    @case('TC-121','CODESPACES','Host khác Codespace bị chặn','Không nhận wildcard app.github.dev hoặc tên miền nối thêm.')
    def test_unlisted_host(self):
        for host in ['other-8765.app.github.dev',self.origin.removeprefix('https://')+'.evil.example']:
            self.assertEqual(self.request('/api/health',host=host)[0],403)

    @case('TC-122','CODESPACES','Healthcheck bên trong container','Localhost vẫn truy cập health; cấu hình origin phải là HTTPS thuần.')
    def test_local_health_and_config(self):
        self.assertEqual(self.request('/api/health',host='localhost:'+str(self.server.server_port))[0],200)
        for origin in ['http://example.com','https://example.com/path','https://user:password@example.com']:
            with self.assertRaises(ValueError):make_handler(self.service,origin)
