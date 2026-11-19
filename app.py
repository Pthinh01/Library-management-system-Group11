"""HTTP controller. Local development server; run behind HTTPS for deployment."""
import argparse
import csv
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from Source_code import LibraryService, RuleError, require, seed_figma_demo

STATIC=Path(__file__).with_name('static')

def codespace_origin(port):
    """Trust only this codespace's exact forwarded HTTPS address."""
    if os.environ.get('CODESPACES') != 'true':
        return None
    name = os.environ.get('CODESPACE_NAME', '')
    domain = os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'app.github.dev')
    if not re.fullmatch(r'[a-z0-9-]+', name) or not re.fullmatch(r'[a-z0-9.-]+', domain):
        raise ValueError('Invalid Codespaces forwarding configuration')
    return f'https://{name}-{port}.{domain}'


def make_handler(service, external_origin=None):
    external_host = None
    if external_origin:
        parsed_origin = urlsplit(external_origin)
        if (parsed_origin.scheme != 'https' or not parsed_origin.netloc or parsed_origin.username
                or parsed_origin.password or parsed_origin.path or parsed_origin.query or parsed_origin.fragment):
            raise ValueError('External origin must be an exact HTTPS origin')
        external_host = parsed_origin.netloc.lower()
    cookie_security = '; Secure' if external_origin else ''
    class Handler(BaseHTTPRequestHandler):
        server_version='Library/1.0'

        def log_message(self, fmt, *args):
            logging.info('%s %s',self.command,urlsplit(self.path).path)

        def send(self, status, payload, content_type='application/json; charset=utf-8', extra=None):
            body=json.dumps(payload,ensure_ascii=False).encode() if content_type.startswith('application/json') else payload
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store')
            for k,v in (extra or {}).items():self.send_header(k,v)
            self.end_headers();self.wfile.write(body)

        def do_GET(self):self.dispatch(False)
        def do_POST(self):self.dispatch(True)

        def dispatch(self, mutation):
            try:
                authority=self.headers.get('Host','').lower()
                host=authority.split(':')[0]
                local_request=host in ('127.0.0.1','localhost')
                require(local_request or (external_host is not None and authority==external_host),'HOST_DENIED','Tên miền truy cập không được cho phép.',403)
                parsed=urlsplit(self.path);route=parsed.path;q=parse_qs(parsed.query)
                def query(name,default=None):return q.get(name,[default])[0]
                def num(value):
                    try:return int(value)
                    except (ValueError,TypeError):raise RuleError('INVALID_INPUT','Mã hoặc số lượng không hợp lệ.')
                jar=cookies.SimpleCookie()
                try:jar.load(self.headers.get('Cookie',''))
                except cookies.CookieError:pass
                token=jar['library_session'].value if 'library_session' in jar else ''
                data={}
                if mutation:
                    size=num(self.headers.get('Content-Length','0'));require(0<size<=100000,'INVALID_INPUT','Nội dung yêu cầu quá lớn hoặc trống.',413)
                    # Consume the bounded body before rejecting its headers. On Windows,
                    # closing with unread bytes can reset the socket and hide the 415.
                    raw_body=self.rfile.read(size)
                    require(self.headers.get('X-Requested-With')=='LibraryUI','CSRF_DENIED','Yêu cầu không hợp lệ.',403)
                    require(self.headers.get('Content-Type','').split(';')[0]=='application/json','INVALID_INPUT','Cần nội dung JSON.',415)
                    try:data=json.loads(raw_body)
                    except (json.JSONDecodeError,UnicodeDecodeError):raise RuleError('INVALID_INPUT','JSON không hợp lệ.')
                    require(isinstance(data,dict),'INVALID_INPUT','Cần đối tượng JSON.')
                    origin=self.headers.get('Origin')
                    allowed_origins={external_origin} if external_origin else set()
                    if local_request:allowed_origins.add('http://'+self.headers.get('Host'))
                    require(origin is None or origin in allowed_origins,'CSRF_DENIED','Nguồn yêu cầu không hợp lệ.',403)
                    if route not in ('/api/login','/api/register'):
                        me=service.me(token,touch=False)
                        require(secrets.compare_digest(me['csrf'],self.headers.get('X-CSRF-Token','')),'CSRF_DENIED','Mã xác thực thao tác không hợp lệ.',403)
                result=None;extra={}
                if not mutation and route in ('/','/app.js','/screens.js','/style.css','/figma.css','/cover.png','/Roboto.ttf'):
                    name='index.html' if route=='/' else route[1:]
                    mime={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8','figma.css':'text/css; charset=utf-8','screens.js':'text/javascript; charset=utf-8','cover.png':'image/png','Roboto.ttf':'font/ttf'}[name]
                    return self.send(200,(STATIC/name).read_bytes(),mime)
                if not mutation and route=='/api/health':
                    with service.db.transaction(False) as c:c.execute('SELECT COUNT(*) FROM books').fetchone()
                    result=dict(status='ok')
                elif mutation and route=='/api/register':result=service.register(data)
                elif mutation and route=='/api/login':
                    result=service.login(data.get('identity',''),data.get('password',''),self.client_address[0])
                    extra['Set-Cookie']='library_session='+result.pop('token')+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400'+cookie_security
                elif not mutation and route=='/api/me':result=service.me(token,touch=False)
                elif mutation and route=='/api/logout':
                    result=service.logout(token);extra['Set-Cookie']='library_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+cookie_security
                elif not mutation and route=='/api/catalog':result=service.catalog(query('q',''),num(query('category')) if query('category') else None,num(query('page','1')),num(query('page_size','20')),query('availability','all'))
                elif not mutation and route=='/api/dashboard':result=service.dashboard(token)
                elif not mutation and route=='/api/lookup-copy':result=service.lookup_copy(token,query('barcode',''))
                elif not mutation and route=='/api/loan-policy':result=service.loan_policy(token)
                elif not mutation and route=='/api/payments':result=service.payments(token)
                elif not mutation and route=='/api/member-summary':result=service.member_summary(token)
                elif not mutation and route=='/api/book':result=service.book(num(query('id')))
                elif mutation and route=='/api/book':result=service.save_book(token,data,num(data['id']) if data.get('id') else None)
                elif mutation and route=='/api/copy':result=service.save_copy(token,data,num(data['id']) if data.get('id') else None)
                elif not mutation and route=='/api/members':result=service.members(token,query('q',''))
                elif mutation and route=='/api/member':result=service.save_member(token,data,num(data['id']) if data.get('id') else None)
                elif not mutation and route=='/api/accounts':result=service.accounts(token)
                elif mutation and route=='/api/account':result=service.save_account(token,data,num(data['id']) if data.get('id') else None)
                elif not mutation and route=='/api/settings':result=service.settings(token)
                elif mutation and route=='/api/settings':result=service.settings(token,data)
                elif not mutation and route=='/api/eligibility':result=service.eligibility(token,num(query('member_id')),num(query('count','1')))
                elif mutation and route=='/api/checkout':result=service.checkout(token,num(data.get('member_id')),data.get('barcodes'),data.get('request_key'))
                elif not mutation and route=='/api/history':result=service.history(token,num(query('member_id')) if query('member_id') else None)
                elif mutation and route=='/api/renew':result=service.renew(token,num(data.get('detail_id')),data.get('request_key'))
                elif not mutation and route=='/api/return-preview':result=service.preview_return(token,query('barcode',''))
                elif mutation and route=='/api/return':result=service.return_copy(token,data.get('barcode'),data.get('condition','AVAILABLE'),data.get('request_key'))
                elif not mutation and route=='/api/reservations':result=service.reservations(token)
                elif mutation and route=='/api/reserve':result=service.reserve(token,num(data.get('book_id')))
                elif mutation and route=='/api/cancel-reservation':result=service.cancel_reservation(token,num(data.get('id')))
                elif not mutation and route=='/api/fines':result=service.fines(token,num(query('member_id')) if query('member_id') else None)
                elif mutation and route=='/api/payment':result=service.pay(token,num(data.get('fine_id')),data.get('amount'),data.get('method'),data.get('request_key'))
                elif not mutation and route in ('/api/report','/api/report.csv'):
                    result=service.report(token,query('start'),query('end'))
                    if route.endswith('.csv'):
                        stream=io.StringIO(newline='');writer=csv.writer(stream);writer.writerow(['Thể loại','Số bản mượn'])
                        for r in result['by_category']:
                            # Neutralize spreadsheet formula injection in catalog labels.
                            name=r['category'];writer.writerow(["'"+name if name.startswith(('=','+','-','@')) else name,r['borrowed']])
                        writer.writerow(['Tổng',result['borrowed']]);writer.writerow(['Tiền đã thu (VND)',result['collected']])
                        return self.send(200,('\ufeff'+stream.getvalue()).encode(),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="library-report.csv"'})
                elif mutation and route=='/api/profile':result=service.update_profile(token,data)
                elif mutation and route=='/api/password':
                    result=service.change_password(token,data.get('old',''),data.get('new',''));extra['Set-Cookie']='library_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+cookie_security
                elif mutation and route=='/api/backup':
                    with tempfile.TemporaryDirectory() as tmp:
                        target=Path(tmp)/'library-backup.lmb'
                        service.backup(token,target,data.get('password',''))
                        return self.send(200,target.read_bytes(),'application/octet-stream',{'Content-Disposition':'attachment; filename="library-backup.lmb"'})
                else:raise RuleError('NOT_FOUND','Không tìm thấy chức năng.',404)
                self.send(200,dict(ok=True,data=result),extra=extra)
            except RuleError as e:self.send(e.status,dict(ok=False,error=e.code,message=str(e)))
            except sqlite3.Error:
                logging.exception('Database operation failed')
                self.send(503,dict(ok=False,error='DATABASE_ERROR',message='Không thể truy cập dữ liệu. Vui lòng thử lại.'))
            except (KeyError,TypeError,ValueError):
                self.send(400,dict(ok=False,error='INVALID_INPUT',message='Dữ liệu không hợp lệ.'))
            except Exception:
                logging.exception('Unhandled operation')
                self.send(500,dict(ok=False,error='INTERNAL_ERROR',message='Không thể hoàn tất thao tác.'))
    return Handler

def main():
    parser=argparse.ArgumentParser(description='Library Management System Group 11')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='127.0.0.1',help='Bind address; use 0.0.0.0 inside Docker.')
    parser.add_argument('--db',default=str(Path(__file__).resolve().parent/'data'/'library.sqlite3'))
    parser.add_argument('--no-demo',action='store_true')
    parser.add_argument('--restore', metavar='BACKUP', help='Khôi phục bản sao lưu sang DB mới.')
    parser.add_argument('--destination', metavar='NEW_DATABASE', help='Đường dẫn DB mới khi khôi phục.')
    args=parser.parse_args()
    if args.restore:
        if not args.destination:parser.error('--restore cần --destination là đường dẫn DB mới.')
        from getpass import getpass
        print(LibraryService.restore_backup(args.restore,getpass('Mật khẩu bản sao lưu: '),args.destination))
        return
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    service=LibraryService(args.db)
    if not args.no_demo:
        seed_figma_demo(service)
    public_origin=codespace_origin(args.port)
    server=ThreadingHTTPServer((args.host,args.port),make_handler(service,public_origin))
    print(f'Library: http://127.0.0.1:{args.port}',flush=True)
    if public_origin:print(f'Codespaces: {public_origin}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
