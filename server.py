#!/usr/bin/env python3
"""Boaba Coffee demo server: static site + small admin API. Python 3 stdlib only.

Run:  ADMIN_PASSWORD='parola-ta' python3 server.py
Without ADMIN_PASSWORD a random password is generated and printed at start.
"""
import hmac
import json
import os
import secrets
import shutil
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'site.json'
BACKUPS = ROOT / 'data' / 'backups'
UPLOADS = ROOT / 'uploads'
HOST = os.environ.get('HOST', '127.0.0.1')
PORT = int(os.environ.get('PORT', '4173'))
PASSWORD = os.environ.get('ADMIN_PASSWORD') or secrets.token_urlsafe(9)
SESSION_TTL = 8 * 3600
MAX_JSON = 512 * 1024
MAX_UPLOAD = 6 * 1024 * 1024
IMAGE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
IMAGE_MAGIC = {'.jpg': (b'\xff\xd8\xff',), '.png': (b'\x89PNG',), '.webp': (b'RIFF',)}
PUBLIC_FILES = {'index.html', 'admin.html', 'styles.css', 'admin.css', 'script.js', 'admin.js', 'robots.txt'}
PUBLIC_DIRS = {'assets', 'uploads'}

sessions = {}
failed_logins = {}
lock = threading.Lock()


def load_data():
    with DATA.open(encoding='utf-8') as f:
        return json.load(f)


def clean_text(value, limit):
    return str(value or '').strip()[:limit]


def clean_price(value):
    if value in (None, ''):
        return None
    price = round(float(value), 2)
    if price < 0 or price > 100000:
        raise ValueError('preț invalid')
    return price


def clean_src(value):
    src = clean_text(value, 300)
    if not (src.startswith('assets/') or src.startswith('uploads/')) or '..' in src:
        raise ValueError('imagine invalidă')
    return src


def validate(payload):
    """Return a sanitized copy of the site data or raise ValueError."""
    settings = payload.get('settings') or {}
    products, offers, gallery = [], [], []
    for item in payload.get('products', [])[:300]:
        name = clean_text(item.get('name'), 80)
        if not name:
            raise ValueError('fiecare produs are nevoie de nume')
        products.append({
            'id': clean_text(item.get('id'), 40) or 'p-' + secrets.token_hex(4),
            'category': clean_text(item.get('category'), 40) or 'Altele',
            'name': name,
            'description': clean_text(item.get('description'), 240),
            'price': clean_price(item.get('price')),
            'available': bool(item.get('available', True)),
            'featured': bool(item.get('featured', False)),
        })
    for item in payload.get('offers', [])[:50]:
        title = clean_text(item.get('title'), 80)
        if not title:
            raise ValueError('fiecare ofertă are nevoie de titlu')
        offers.append({
            'id': clean_text(item.get('id'), 40) or 'o-' + secrets.token_hex(4),
            'title': title,
            'description': clean_text(item.get('description'), 240),
            'price': clean_text(item.get('price'), 40),
            'validUntil': clean_text(item.get('validUntil'), 10),
            'active': bool(item.get('active', True)),
        })
    for item in payload.get('gallery', [])[:40]:
        gallery.append({
            'id': clean_text(item.get('id'), 40) or 'g-' + secrets.token_hex(4),
            'src': clean_src(item.get('src')),
            'alt': clean_text(item.get('alt'), 200),
            'caption': clean_text(item.get('caption'), 80),
            'concept': bool(item.get('concept', False)),
        })
    return {
        'settings': {
            'announcement': clean_text(settings.get('announcement'), 160),
            'phone': clean_text(settings.get('phone'), 30),
            'hoursWeek': clean_text(settings.get('hoursWeek'), 30),
            'hoursSunday': clean_text(settings.get('hoursSunday'), 30),
        },
        'products': products,
        'offers': offers,
        'gallery': gallery,
        'updatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def save_data(data):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    if DATA.exists():
        shutil.copy2(DATA, BACKUPS / f"site-{time.strftime('%Y%m%d-%H%M%S')}.json")
        for old in sorted(BACKUPS.glob('site-*.json'))[:-30]:
            old.unlink()
    tmp = DATA.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(DATA)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f'{self.address_string()} {fmt % args}')

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        if self.path.startswith('/api/') or self.path.startswith('/admin'):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    # Helpers
    def send_json(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_body(self, limit):
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > limit:
            raise ValueError('dimensiune invalidă')
        return self.rfile.read(length)

    def session_token(self):
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        return cookie['admin_session'].value if 'admin_session' in cookie else None

    def is_admin(self):
        token = self.session_token()
        with lock:
            expires = sessions.get(token)
            if expires and expires > time.time():
                return True
            sessions.pop(token, None)
        return False

    def same_origin(self):
        # Writes require the custom header (blocked cross-site without CORS) and a matching Origin.
        origin = self.headers.get('Origin')
        host = self.headers.get('Host')
        return self.headers.get('X-Requested-With') == 'boaba-admin' and (origin is None or origin.split('://', 1)[-1] == host)

    def guard(self):
        if not self.same_origin():
            self.send_json(HTTPStatus.FORBIDDEN, {'error': 'Cerere respinsă.'})
            return False
        if not self.is_admin():
            self.send_json(HTTPStatus.UNAUTHORIZED, {'error': 'Autentificare necesară.'})
            return False
        return True

    # Routes
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/site':
            return self.send_json(HTTPStatus.OK, load_data())
        if path == '/api/me':
            return self.send_json(HTTPStatus.OK, {'admin': self.is_admin()})
        if path in ('/', '/admin'):
            self.path = '/index.html' if path == '/' else '/admin.html'
            return super().do_GET()
        parts = path.lstrip('/').split('/')
        allowed = (len(parts) == 1 and parts[0] in PUBLIC_FILES) \
            or (len(parts) == 2 and parts[0] in PUBLIC_DIRS and '..' not in parts[1]) \
            or (len(parts) == 3 and parts[:2] == ['assets', 'found'] and '..' not in parts[2] and parts[2] != 'credits.json')
        if not allowed:
            return self.send_error(HTTPStatus.NOT_FOUND)
        return super().do_GET()

    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/login':
            return self.login()
        if path == '/api/logout':
            token = self.session_token()
            with lock:
                sessions.pop(token, None)
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header('Set-Cookie', 'admin_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
            return self.end_headers()
        if path == '/api/upload':
            return self.upload()
        return self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        if self.path.split('?', 1)[0] != '/api/site':
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not self.guard():
            return
        try:
            data = validate(json.loads(self.read_body(MAX_JSON)))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json(HTTPStatus.BAD_REQUEST, {'error': f'Date invalide: {error}'})
        with lock:
            save_data(data)
        return self.send_json(HTTPStatus.OK, data)

    def login(self):
        if not self.same_origin():
            return self.send_json(HTTPStatus.FORBIDDEN, {'error': 'Cerere respinsă.'})
        ip = self.client_address[0]
        with lock:
            count, since = failed_logins.get(ip, (0, time.time()))
            if time.time() - since > 900:
                count, since = 0, time.time()
            if count >= 8:
                return self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {'error': 'Prea multe încercări. Revino în 15 minute.'})
        try:
            password = json.loads(self.read_body(4096)).get('password', '')
        except (ValueError, json.JSONDecodeError):
            password = ''
        if not hmac.compare_digest(str(password).encode(), PASSWORD.encode()):
            with lock:
                failed_logins[ip] = (count + 1, since)
            time.sleep(0.6)
            return self.send_json(HTTPStatus.UNAUTHORIZED, {'error': 'Parolă greșită.'})
        token = secrets.token_urlsafe(32)
        with lock:
            failed_logins.pop(ip, None)
            sessions[token] = time.time() + SESSION_TTL
        raw = b'{"ok":true}'
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Set-Cookie', f'admin_session={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict')
        self.end_headers()
        self.wfile.write(raw)

    def upload(self):
        if not self.guard():
            return
        kind = (self.headers.get('Content-Type') or '').split(';', 1)[0].strip()
        ext = IMAGE_TYPES.get(kind)
        if not ext:
            return self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {'error': 'Doar JPG, PNG sau WebP.'})
        try:
            body = self.read_body(MAX_UPLOAD)
        except ValueError:
            return self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {'error': 'Imagine prea mare (max. 6 MB).'})
        if not body.startswith(IMAGE_MAGIC[ext]):
            return self.send_json(HTTPStatus.BAD_REQUEST, {'error': 'Fișierul nu pare o imagine validă.'})
        UPLOADS.mkdir(exist_ok=True)
        name = f'{time.strftime("%Y%m%d")}-{secrets.token_hex(6)}{ext}'
        (UPLOADS / name).write_bytes(body)
        return self.send_json(HTTPStatus.CREATED, {'src': f'uploads/{name}'})


if __name__ == '__main__':
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Boaba Coffee: http://{HOST}:{PORT}  ·  admin: http://{HOST}:{PORT}/admin')
    if 'ADMIN_PASSWORD' not in os.environ:
        print(f'Parolă admin generată pentru această pornire: {PASSWORD}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nOprit.')
