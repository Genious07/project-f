"""Wire framing guards for the disposable database fault harness."""
import unittest

from tools.postgres_fault_proxy import FrontendFrames


def message(kind, payload):
    return kind + (len(payload) + 4).to_bytes(4, 'big') + payload


class FrontendFramesTests(unittest.TestCase):
    def parser(self):
        parser = FrontendFrames()
        startup = b'\x00\x03\x00\x00user\x00postgres\x00\x00'
        self.assertFalse(parser.feed((len(startup) + 4).to_bytes(4, 'big') + startup))
        return parser

    def test_fragmented_commit_and_combined_frames(self):
        parser = self.parser()
        commit = message(b'Q', b'COMMIT\x00')
        results = [parser.feed(bytes([byte])) for byte in commit]
        self.assertEqual(results, [False] * (len(commit) - 1) + [True])
        self.assertTrue(parser.feed(message(b'Q', b'BEGIN\x00') + commit))

    def test_only_exact_simple_query_commit_is_intercepted(self):
        parser = self.parser()
        for kind, payload in ((b'Q', b"SELECT 'COMMIT'\x00"), (b'P', b'COMMIT\x00'),
                              (b'Q', b'ROLLBACK\x00'), (b'Q', b'COMMIT EXTRA\x00')):
            self.assertFalse(parser.feed(message(kind, payload)))

    def test_invalid_lengths_fail_without_waiting_for_payload(self):
        for length in (0, 3, 16 * 1024 * 1024 + 1):
            with self.subTest(length=length):
                parser = self.parser()
                with self.assertRaises(ValueError):
                    parser.feed(b'Q' + length.to_bytes(4, 'big'))
