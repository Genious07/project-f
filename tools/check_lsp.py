"""Drive a standalone native language server through an editor-style stdio session."""
import argparse
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def frame(value):
    body = json.dumps(value, ensure_ascii=False).encode()
    return f'Content-Length: {len(body)}\r\n\r\n'.encode() + body


class Client:
    def __init__(self, binary, directory):
        self.process = subprocess.Popen([str(binary)], cwd=directory, env={'PATH': ''}, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.buffer = b''

    def send(self, method, params=None, identifier=None):
        value = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if identifier is not None:
            value['id'] = identifier
        self.process.stdin.write(frame(value))
        self.process.stdin.flush()

    def receive(self):
        deadline = time.monotonic() + 10
        while True:
            if b'\r\n\r\n' in self.buffer:
                header, body = self.buffer.split(b'\r\n\r\n', 1)
                length = int(header.decode().split(':', 1)[1].strip())
                if len(body) >= length:
                    self.buffer = body[length:]
                    return json.loads(body[:length])
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError('language server response timed out')
            part = os.read(self.process.stdout.fileno(), 65536)
            if not part:
                raise RuntimeError('language server closed stdout before response')
            self.buffer += part

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def position(source, needle):
    prefix = source[:source.index(needle)]
    line = prefix.count('\n')
    last_line = prefix.rsplit('\n', 1)[-1]
    return {'line': line, 'character': len(last_line.encode('utf-16-le')) // 2}


def verify(binary):
    with tempfile.TemporaryDirectory() as directory:
        standalone = Path(directory) / 'foresee-lsp'
        shutil.copy2(binary, standalone)
        client = Client(standalone, directory)
        try:
            client.send('initialize', {'capabilities': {}}, 1)
            capabilities = client.receive()['result']['capabilities']
            assert capabilities['positionEncoding'] == 'utf-16'
            assert capabilities['textDocumentSync']['change'] == 1
            client.send('initialized')
            uri = 'file:///not-on-disk/repair.fore'
            base = (ROOT / 'examples/repair.fore').read_text()
            # Place an emoji before the error on the same line to test UTF-16 conversion.
            broken = base.replace('return commit chosen', 'let label = "😀"; return commit missing')
            client.send('textDocument/didOpen', {'textDocument': {'uri': uri, 'languageId': 'foresee', 'version': 1, 'text': broken}})
            diagnostics = client.receive()
            assert diagnostics['method'] == 'textDocument/publishDiagnostics'
            assert diagnostics['params']['version'] == 1
            unknown = next(d for d in diagnostics['params']['diagnostics'] if d['code'] == 'F3004')
            assert unknown['range']['start'] == position(broken, 'missing')
            client.send('textDocument/hover', {'textDocument': {'uri': uri}, 'position': position(broken, 'missing')}, 2)
            assert client.receive()['result'] is None
            fixed = broken.replace('commit missing', 'commit chosen')
            client.send('textDocument/didChange', {'textDocument': {'uri': uri, 'version': 2}, 'contentChanges': [{'text': fixed}]})
            cleared = client.receive()
            assert cleared['params']['version'] == 2 and cleared['params']['diagnostics'] == []
            client.send('textDocument/documentSymbol', {'textDocument': {'uri': uri}}, 3)
            symbols = client.receive()['result']
            assert [s['name'] for s in symbols] == ['catalog', 'planner', 'repair_catalog']
            assert symbols[2]['range']['end']['line'] > symbols[2]['range']['start']['line']
            chosen = position(fixed, 'chosen to catalog')
            client.send('textDocument/hover', {'textDocument': {'uri': uri}, 'position': chosen}, 4)
            hover = client.receive()['result']
            assert 'selected' in hover['contents']['value'] and 'snapshot:1' in hover['contents']['value']
            assert hover['range']['start'] == chosen
            client.send('textDocument/didChange', {'textDocument': {'uri': uri, 'version': 1}, 'contentChanges': [{'text': '@'}]})
            client.send('textDocument/hover', {'textDocument': {'uri': uri}, 'position': chosen}, 5)
            assert client.receive()['id'] == 5  # Stale version did not publish stale diagnostics.
            client.send('textDocument/didClose', {'textDocument': {'uri': uri}})
            assert client.receive()['params']['diagnostics'] == []
            client.send('textDocument/hover', {'textDocument': {'uri': uri}, 'position': chosen}, 6)
            assert client.receive()['result'] is None
            client.send('not/supported', {}, 7)
            assert client.receive()['error']['code'] == -32601
            client.send('shutdown', {}, 8)
            assert client.receive() == {'jsonrpc': '2.0', 'id': 8, 'result': None}
            client.send('exit')
            assert client.process.wait(timeout=5) == 0
            assert client.process.stderr.read() == b''
            assert client.process.stdout.read() == b''
        finally:
            client.close()
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/debug/foresee-lsp')
    args = parser.parse_args()
    verify(args.binary.resolve())
    print('PASS: standalone LSP session initializes, diagnoses, fixes, hovers, lists symbols, closes, and shuts down; UTF-16 spans and stale versions verified.')


if __name__ == '__main__':
    main()
