#!/usr/bin/env python3
"""Dashboard server for Swarm cron outputs."""

import http.server
import json
import os
import sys
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / 'data'
LOGOS_DIR = DATA_DIR / 'logos'
DASHBOARD_DIR = Path(__file__).parent

# Known output files
OUTPUT_FILES = {
    'research-digest': DATA_DIR / 'research-digest-latest.md',
    'hn': DATA_DIR / 'hn-latest.md',
    'polymarket': DATA_DIR / 'polymarket-latest.md',
    'techblogs': DATA_DIR / 'techblogs-latest.md',
    'papers': DATA_DIR / 'papers-latest.md',
    'competitors': DATA_DIR / 'competitors-latest.md',
}

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/output/'):
            key = self.path.split('/')[-1]
            self.serve_output(key)
        elif self.path == '/api/competitors-data':
            self.serve_competitors_data()
        elif self.path == '/api/competitor-news':
            self.serve_competitor_news()
        elif self.path == '/api/curated-digest':
            self.serve_curated_digest()
        elif self.path == '/api/politics':
            self.serve_politics()
        elif self.path.startswith('/data/logos/'):
            self.serve_logo(self.path)
        elif self.path == '/api/status':
            self.serve_status()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/write':
            self.handle_write()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_write(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
            key = data.get('key')
            content = data.get('content', '')
        except Exception:
            self.send_json(400, {'error': 'Invalid JSON'})
            return

        # Allow any key - write to data dir
        filepath = DATA_DIR / f'{key}-latest.md'
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        self.send_json(200, {'status': 'ok', 'key': key})

    def serve_output(self, key):
        if key not in OUTPUT_FILES:
            self.send_json(404, {'error': 'Unknown key'})
            return

        filepath = OUTPUT_FILES[key]
        if not filepath.exists():
            self.send_json(404, {'error': 'No data yet'})
            return

        try:
            content = filepath.read_text(encoding='utf-8', errors='replace')
        except Exception:
            self.send_json(500, {'error': 'Could not read file'})
            return

        mtime = filepath.stat().st_mtime

        self.send_json(200, {
            'key': key,
            'content': content.strip(),
            'timestamp': int(mtime * 1000),
            'filename': filepath.name,
        })

    def serve_status(self):
        status = {}
        for key, filepath in OUTPUT_FILES.items():
            if filepath.exists():
                stat = filepath.stat()
                status[key] = {
                    'exists': True,
                    'size': stat.st_size,
                    'modified': int(stat.st_mtime * 1000),
                    'age_minutes': (datetime.now().timestamp() - stat.st_mtime) / 60,
                }
            else:
                status[key] = {'exists': False}
        self.send_json(200, status)

    def serve_competitors_data(self):
        filepath = DATA_DIR / 'competitors-data.json'
        if not filepath.exists():
            self.send_json(404, {'error': 'Competitor data not found'})
            return
        try:
            content = filepath.read_text(encoding='utf-8', errors='replace')
            data = json.loads(content)
        except Exception:
            self.send_json(500, {'error': 'Could not parse competitor data'})
            return
        self.send_json(200, data)

    def serve_competitor_news(self):
        filepath = DATA_DIR / 'competitor_news.json'
        if not filepath.exists():
            self.send_json(404, {'error': 'Competitor news not found'})
            return
        try:
            content = filepath.read_text(encoding='utf-8', errors='replace')
            data = json.loads(content)
        except Exception:
            self.send_json(500, {'error': 'Could not parse competitor news'})
            return
        self.send_json(200, data)

    def serve_curated_digest(self):
        """Serve the curated research digest."""
        digest_dir = Path('/Users/joshswarm/research-digest/output')
        if not digest_dir.exists():
            self.send_json(404, {'error': 'Research digest directory not found'})
            return
        
        curated_files = sorted(digest_dir.glob('curated-*.json'), reverse=True)
        if not curated_files:
            self.send_json(404, {'error': 'No curated digest found'})
            return
        
        try:
            data = json.loads(curated_files[0].read_text())
            self.send_json(200, data)
        except Exception as e:
            self.send_json(500, {'error': str(e)})

    def serve_politics(self):
        """Serve the latest political headlines."""
        filepath = DATA_DIR / 'politics-latest.json'
        if not filepath.exists():
            self.send_json(404, {'error': 'Politics data not found'})
            return
        try:
            content = filepath.read_text(encoding='utf-8', errors='replace')
            data = json.loads(content)
        except Exception:
            self.send_json(500, {'error': 'Could not parse politics data'})
            return
        self.send_json(200, data)

    def serve_logo(self, path):
        filename = path.split('/')[-1]
        filepath = LOGOS_DIR / filename
        if not filepath.exists():
            self.send_response(404)
            self.end_headers()
            return
        if filename.endswith('.svg'):
            content_type = 'image/svg+xml'
        elif filename.endswith('.png'):
            content_type = 'image/png'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            content_type = 'image/jpeg'
        else:
            content_type = 'application/octet-stream'
        try:
            data = filepath.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(500)
            self.end_headers()

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.HTTPServer(('127.0.0.1', port), DashboardHandler)
    print(f'📊 Swarm Dashboard → http://127.0.0.1:{port}')
    print(f'   Data dir: {DATA_DIR}')
    print(f'   Press Ctrl+C to stop\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
        server.server_close()
