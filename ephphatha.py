#!/usr/bin/env python3
"""Ephphatha: review recorded lines (TTS or studio takes) one by one in the browser and hand back a list of what
must be recorded or written again.

    python3 ephphatha.py review.json                 serve the review page on http://127.0.0.1:8790/?t=<token>
    python3 ephphatha.py review.json --lan           also reachable from a phone in the same network
    python3 ephphatha.py review.json --port 8800
    python3 ephphatha.py review.json --todo          print what the reviewer marked (status, note, take) and exit

The manifest (review.json) lists the lines; the reviewer's verdicts are written next to it as review.verdict.json and
nowhere else. Audio files are served only from the manifest's media folder. Every request needs the token printed at
start (a new one each run, or --token). Python standard library only. See README.md for the manifest format.
"""
import argparse, json, mimetypes, os, re, secrets, socket, sys, threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

HERE = Path(__file__).resolve().parent
STATUS = ('ok', 'redo', 'text')


def load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def verdict_path(manifest):
    return manifest.with_name(manifest.stem + '.verdict.json')


def todo(manifest):
    """The items the reviewer did not accept, for whoever renders the lines again."""
    m = load(manifest, {}); v = load(verdict_path(manifest), {}).get('items', {})
    items = {i['id']: i for i in m.get('items', [])}
    out = []
    for iid, r in v.items():
        if r.get('status') in ('redo', 'text') or r.get('note') or r.get('take'):
            it = items.get(iid, {})
            out.append({'id': iid, 'status': r.get('status'), 'take': r.get('take', 0), 'note': r.get('note', ''),
                        'ref': it.get('ref', ''), 'speaker': it.get('speaker', ''), 'where': it.get('where', ''),
                        'text': (it.get('after') or {}).get('text', '')})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = 'Ephphatha/1'

    def log_message(self, fmt, *args):  # quiet: only errors
        if args and str(args[1]).startswith(('4', '5')):
            sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))

    def _authorized(self, q):
        t = self.headers.get('X-Token') or (q.get('t') or [''])[0]
        return secrets.compare_digest(t, self.server.token)

    def _send(self, code, body=b'', ctype='application/json; charset=utf-8', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path in ('/', '/index.html'):
            body = (HERE / 'index.html').read_bytes()
            return self._send(200, body, 'text/html; charset=utf-8', {'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; media-src 'self'; img-src 'self' data:"})
        if not self._authorized(q):
            return self._send(403, b'{"error":"token"}')
        if u.path == '/api/manifest':
            m = load(self.server.manifest, {})
            m.pop('media', None)
            return self._send(200, json.dumps(m, ensure_ascii=False).encode())
        if u.path == '/api/verdict':
            return self._send(200, json.dumps(load(verdict_path(self.server.manifest), {'items': {}}), ensure_ascii=False).encode())
        if u.path.startswith('/media/'):
            return self._media(unquote(u.path[len('/media/'):]))
        self._send(404, b'{"error":"not found"}')

    def _media(self, rel):
        root = self.server.media
        p = (root / rel).resolve()
        if root not in p.parents or not p.is_file():
            return self._send(404, b'{"error":"not found"}')
        size = p.stat().st_size
        ctype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        m = re.match(r'bytes=(\d*)-(\d*)$', rng or '')
        if m:  # iPhone Safari plays audio only from a server that answers byte ranges
            a = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2) or 0))
            b = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
            b = min(b, size - 1)
            if a > b:
                return self._send(416, b'', ctype, {'Content-Range': f'bytes */{size}'})
            with open(p, 'rb') as f:
                f.seek(a); data = f.read(b - a + 1)
            return self._send(206, data, ctype, {'Content-Range': f'bytes {a}-{b}/{size}', 'Accept-Ranges': 'bytes'})
        self._send(200, p.read_bytes(), ctype, {'Accept-Ranges': 'bytes'})

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if not self._authorized(q):
            return self._send(403, b'{"error":"token"}')
        if u.path != '/api/verdict':
            return self._send(404, b'{"error":"not found"}')
        n = int(self.headers.get('Content-Length') or 0)
        if n > 2_000_000:
            return self._send(413, b'{"error":"too large"}')
        try:
            patch = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, b'{"error":"json"}')
        ids = {i['id'] for i in load(self.server.manifest, {}).get('items', [])}
        with self.server.lock:
            path = verdict_path(self.server.manifest)
            v = load(path, {'items': {}})
            for iid, r in (patch.get('items') or {}).items():
                if iid not in ids or not isinstance(r, dict):
                    continue
                rec = {}
                if r.get('status') in STATUS: rec['status'] = r['status']
                if isinstance(r.get('note'), str) and r['note'].strip(): rec['note'] = r['note'][:4000]
                if isinstance(r.get('take'), int) and r['take'] > 0: rec['take'] = r['take']
                if rec:
                    rec['at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    v['items'][iid] = rec
                else:
                    v['items'].pop(iid, None)
            v['manifest'] = self.server.manifest.name
            v['updated'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, path)
        self._send(200, json.dumps({'ok': True, 'updated': v['updated']}).encode())


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('192.0.2.1', 9)); return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('manifest'); ap.add_argument('--port', type=int, default=8790)
    ap.add_argument('--lan', action='store_true', help='listen on all interfaces (phone in the same network)')
    ap.add_argument('--token'); ap.add_argument('--todo', action='store_true')
    a = ap.parse_args()
    manifest = Path(a.manifest).resolve()
    if a.todo:
        print(json.dumps(todo(manifest), ensure_ascii=False, indent=1)); return
    m = load(manifest, None)
    if not m:
        sys.exit(f'No manifest at {manifest}')
    media = (manifest.parent / m.get('media', '.')).resolve()
    srv = ThreadingHTTPServer(('0.0.0.0' if a.lan else '127.0.0.1', a.port), Handler)
    srv.manifest, srv.media, srv.lock = manifest, media, threading.Lock()
    srv.token = a.token or secrets.token_urlsafe(16)
    host = lan_ip() if a.lan else '127.0.0.1'
    print(f'Ephphatha: {len(m.get("items", []))} lines, verdicts in {verdict_path(manifest).name}')
    print(f'  http://{host}:{a.port}/?t={srv.token}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
