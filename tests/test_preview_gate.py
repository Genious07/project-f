import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.check_preview import run_gate


class PreviewGateTests(unittest.TestCase):
    def run_case(self, effects):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('tools.check_preview.subprocess.run', side_effect=effects) as run:
                code = run_gate([('first', ['test']), ('second', ['test'])], output, {'source_commit': 'example'})
            return code, json.loads((output / 'summary.json').read_text()), run.call_count

    def test_success_does_not_authorize_publication(self):
        code, report, count = self.run_case([subprocess.CompletedProcess([], 0)] * 2)
        self.assertEqual((code, report['status'], count), (0, 'passed', 2))
        self.assertFalse(report['publication_authorized'])

    def test_failure_stops_and_records_evidence(self):
        code, report, count = self.run_case([subprocess.CompletedProcess([], 1)])
        self.assertEqual((code, report['status'], count), (1, 'failed', 1))
        self.assertEqual(report['steps'][0]['exit_code'], 1)

    def test_missing_tool_and_timeout_fail_closed(self):
        for error in (FileNotFoundError('missing'), subprocess.TimeoutExpired(['test'], 600)):
            with self.subTest(error=error):
                code, report, count = self.run_case([error])
                self.assertEqual((code, report['status'], count), (1, 'failed', 1))
                self.assertIn('error', report['steps'][0])
