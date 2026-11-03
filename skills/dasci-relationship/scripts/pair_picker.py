#!/usr/bin/env python3
"""Local, single-submit X→Y field picker; standard library HTTP transport."""
from __future__ import annotations

import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sys
import time
import webbrowser

import data_relationship as dr
import interaction


class PickerSession:
    def __init__(self, request):
        initial = interaction.advance(request)
        if initial['step'] in {'needs_file', 'needs_sheet'}:
            raise dr.UserError('请先指定文件与工作表，再打开字段选择页。')
        self.initial = initial
        self.state = deepcopy(initial['state'])
        self.state['confirmed'] = False
        self.path = Path(self.state['input'])
        self.fingerprint = self.signature()
        frame, _ = dr.load_table(self.path, sheet_index=self.state['sheet']['index'] if self.state['sheet'] else None)
        frame, _ = dr.normalize_frame(frame)
        columns = dr.prepare_columns(frame)
        semantic_errors = {}
        for bound in self.state['columns']:
            if bound is not None and bound['type'] != 'auto':
                index = bound['index']-1
                try:
                    columns[index] = dr.prepare_frame_column(frame, index, kind=bound['type'], order=bound['order'])
                except dr.UserError as exc:
                    semantic_errors[bound['index']] = str(exc)
        catalog, preview = dr.column_view(frame, columns, all_columns=True)
        for column in catalog['items']:
            if column['index'] in semantic_errors:
                column.update(selectable=False, reason=semantic_errors[column['index']])
        self.model = {'filename': self.path.name, 'sheet': self.state['sheet'],
                      'columns': catalog['items'], 'preview': preview,
                      'selected': self.state['columns'],
                      'plot': initial['summary']['plot'] if initial['summary'] else None}
        template = (Path(__file__).resolve().parents[1]/'assets/field-picker.html').read_text(encoding='utf-8')
        data = json.dumps(self.model, ensure_ascii=False, default=str).replace('<', '\\u003c')
        self.page = template.replace('__FIELD_DATA__', data).encode('utf-8')
        self.result = None
        self.session_path = '/'+secrets.token_urlsafe(24)+'/'

    def signature(self):
        stat = self.path.stat()
        return stat.st_size, stat.st_mtime_ns


class PairPicker(HTTPServer):
    def __init__(self, request):
        self.session = PickerSession(request)
        super().__init__(('127.0.0.1', 0), PickerHandler)
        self.timeout = 0.5
        self.session.origin = f'http://127.0.0.1:{self.server_port}'
        self.selection_url = self.session.origin+self.session.session_path

    def serve_selection(self, timeout=900):
        deadline = time.monotonic()+timeout
        while self.session.result is None and time.monotonic() < deadline:
            self.handle_request()
        if self.session.result is None:
            raise dr.UserError('字段选择等待超时，尚未开始分析；可重新打开选择页。')
        return self.session.result


class PickerHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not mix HTTP access logs with the CLI JSON protocol.

    def reply(self, status, payload, content_type='application/json; charset=utf-8'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != self.server.session.session_path:
            self.reply(404, {'ok': False, 'error': '页面不存在。'})
            return
        self.reply(200, self.server.session.page, 'text/html; charset=utf-8')

    def do_POST(self):
        server = self.server.session
        if self.path not in (server.session_path+'pair', server.session_path+'cancel'):
            self.reply(404, {'ok': False, 'error': '操作不存在。'})
            return
        if self.headers.get('Origin', server.origin) != server.origin:
            self.reply(403, {'ok': False, 'error': '请在本次字段选择页提交。'})
            return
        if self.path.endswith('/cancel'):
            server.result = {**server.initial, 'state': server.state, 'analysis_args': None,
                             'step': 'cancelled', 'question': None, 'cancelled': True}
            self.reply(200, server.result)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536 or self.headers.get_content_type() != 'application/json':
                raise dr.UserError('请提交有效的字段选择。')
            pair = json.loads(self.rfile.read(length))
            if server.signature() != server.fingerprint:
                server.result = {**server.initial, 'ok': False, 'state': server.state,
                                 'analysis_args': None, 'step': 'needs_columns',
                                 'error': '源文件已变化，请重新打开字段选择页。'}
                self.reply(409, server.result)
                return
            result = interaction.advance({'state': server.state, 'action': {'pair': pair}})
        except (dr.UserError, ValueError, UnicodeError) as exc:
            self.reply(400, {'ok': False, 'error': str(exc)})
            return
        if result['step'] == 'needs_columns':
            self.reply(400, {**result, 'error': result['error'] or '请选择两个有效的不同字段。'})
            return
        server.result = result
        self.reply(200, result)


def main():
    parser = argparse.ArgumentParser(description='在一个页面选择 X/Y 字段，点击箭头交换并提交。')
    parser.add_argument('--request', required=True, help='既有 select 请求或返回 state 的 JSON 文件')
    parser.add_argument('--open', action='store_true', help='同时尝试打开本机浏览器，仍输出链接')
    parser.add_argument('--timeout', type=int, default=900, help='等待用户提交的秒数，默认 900')
    args = parser.parse_args()
    try:
        if args.timeout < 1:
            raise dr.UserError('等待时间必须大于 0。')
        request = json.loads(Path(args.request).expanduser().read_text(encoding='utf-8'))
        with PairPicker(request) as server:
            print(json.dumps({'ok': True, 'step': 'awaiting_pair', 'selection_url': server.selection_url}, ensure_ascii=False), flush=True)
            if args.open:
                webbrowser.open(server.selection_url)
            result = server.serve_selection(args.timeout)
        return dr.emit(result, 0 if result['ok'] else 1)
    except (dr.UserError, OSError, ValueError) as exc:
        return dr.emit({'ok': False, 'error': str(exc)}, 1)


if __name__ == '__main__':
    sys.exit(main())
