"""Client-side framing and coordinate expectations used by editor integration."""
import json
import unittest
from tools.check_lsp import frame, position


class LspProtocolTests(unittest.TestCase):
    def test_content_length_is_utf8_bytes(self):
        value = {'text': '😀茶'}
        header, payload = frame(value).split(b'\r\n\r\n', 1)
        self.assertEqual(int(header.split(b':')[1]), len(payload))
        self.assertEqual(json.loads(payload), value)
        self.assertGreater(len(payload), len(payload.decode()))

    def test_utf16_position_after_emoji_and_crlf(self):
        self.assertEqual(position('line\r\n😀missing', 'missing'), {'line': 1, 'character': 2})


if __name__ == '__main__':
    unittest.main()
