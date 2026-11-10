#!/usr/bin/env python3
"""mock AgentR gateway：模拟 /gateway-health 与 /api/node/pages/* 接口，用于 skill 端到端测试。"""
import base64
import json
import re
import shutil
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STORE = Path(sys.argv[2]).resolve()
SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload=None, raw=None, ctype='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.end_headers()
        self.wfile.write(raw if raw is not None else json.dumps(payload).encode('utf-8'))

    def do_GET(self):
        if self.path == '/gateway-health':
            return self._send(200, raw=b'ok\n', ctype='text/plain')
        if self.path == '/api/node/pages':
            pages = []
            if STORE.exists():
                for d in sorted(STORE.iterdir()):
                    idx = d / 'index.html'
                    if d.is_dir() and idx.exists():
                        head = idx.read_text('utf-8', errors='ignore')[:4000]
                        m = re.search(r'<title>(.*?)</title>', head, re.S)
                        pages.append({'slug': d.name, 'title': (m.group(1).strip() if m else d.name), 'updatedAt': '2026-01-01T00:00:00Z'})
            return self._send(200, {'pages': pages})
        self._send(404, {'message': 'not found'})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        payload = json.loads(self.rfile.read(length) or b'{}')
        if self.path == '/api/node/pages/upload':
            slug = payload.get('slug', '')
            if not SLUG_RE.match(slug):
                return self._send(400, {'message': '非法页面名: ' + slug})
            total = 0
            dest = STORE / slug
            if dest.exists():
                shutil.rmtree(dest)
            for f in payload.get('files', []):
                rel = Path(f['path'])
                if '..' in rel.parts or rel.is_absolute():
                    return self._send(400, {'message': '非法路径: ' + f['path']})
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                data = base64.b64decode(f['contentBase64'])
                total += len(data)
                target.write_bytes(data)
            return self._send(200, {'slug': slug, 'files': len(payload.get('files', [])), 'totalBytes': total, 'committed': True, 'url': '/pages/%s/index.html' % slug})
        if self.path == '/api/node/pages/delete':
            slug = payload.get('slug', '')
            dest = STORE / slug
            removed = dest.exists()
            if removed:
                shutil.rmtree(dest)
            return self._send(200, {'slug': slug, 'removed': removed, 'committed': True})
        self._send(404, {'message': 'not found'})

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    STORE.mkdir(parents=True, exist_ok=True)
    HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
