import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lark_cli import LarkCLI, CLIError, UnknownWrite


class TransportTests(unittest.TestCase):
    def test_success_envelope_needs_no_code_zero(self):
        result = subprocess.CompletedProcess([], 0, '{"ok":true,"data":{"id":"one"}}', '')
        self.assertEqual(LarkCLI.decode(result)['data']['id'], 'one')

    def test_nested_error_cannot_be_reported_as_success(self):
        result = subprocess.CompletedProcess([], 0, '{"ok":true,"data":{"code":1254291}}', '')
        with self.assertRaises(CLIError):
            LarkCLI.decode(result)

    def test_ndjson_manifest_is_accepted_only_for_requested_read_format(self):
        manifest = {'manifest_version': 'v1', 'format': 'ndjson', 'records_count': 0,
                    'has_more': False, 'record_file': 'records.ndjson'}
        result = subprocess.CompletedProcess([], 0, json.dumps(manifest), '')
        with self.assertRaises(CLIError):
            LarkCLI.decode(result)
        self.assertEqual(LarkCLI.decode(result, allow_manifest=True)['data']['records_count'], 0)

    def test_timeout_is_journaled_and_never_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock(pid=1234)
            process.communicate.side_effect = [subprocess.TimeoutExpired('lark-cli', 1), ('', '')]
            with patch('lark_cli.subprocess.Popen', return_value=process) as launch, patch('lark_cli.os.killpg'):
                cli = LarkCLI(directory, timeout=1)
                with self.assertRaises(UnknownWrite):
                    cli.call(['base', '+record-batch-create'], write=True)
                with self.assertRaises(UnknownWrite):
                    cli.call(['base', '+record-batch-create'], write=True)
                self.assertEqual(launch.call_count, 1)
            entries = [json.loads(line) for line in (Path(directory) / '.local/writes.ndjson').read_text().splitlines()]
            self.assertEqual([entry['state'] for entry in entries], ['started', 'unknown'])

    def test_interrupted_write_blocks_next_process(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = LarkCLI(directory)
            cli._journal({'operation': 'interrupted', 'state': 'started'})
            with patch('lark_cli.subprocess.Popen') as launch:
                with self.assertRaises(UnknownWrite):
                    cli.call(['base', '+table-create'], write=True)
                launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
