"""Thin CLI transport: credentials stay in the existing lark-cli installation."""
import json
import os
from pathlib import Path
import signal
import subprocess
import uuid
from datetime import datetime, timezone


class UnknownWrite(RuntimeError):
    """A remote write may have happened. Reconcile before any new write."""


class CLIError(RuntimeError):
    pass


class LarkCLI:
    def __init__(self, root, timeout=120, attachment_timeout=300):
        self.root = Path(root)
        self.timeout = timeout
        self.attachment_timeout = attachment_timeout
        self.local = self.root / '.local'
        self.local.mkdir(exist_ok=True)

    def _journal(self, entry):
        entry['time'] = datetime.now(timezone.utc).isoformat()
        with (self.local / 'writes.ndjson').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def _assert_writes_resolved(self):
        journal = self.local / 'writes.ndjson'
        states = {}
        if journal.exists():
            for line in journal.read_text().splitlines():
                entry = json.loads(line)
                states[entry['operation']] = entry['state']
        if any(state in {'started', 'unknown'} for state in states.values()):
            raise UnknownWrite('有尚未对账的写入。先只读核对并记录结论，不能继续写入。')

    @staticmethod
    def decode(completed, *, allow_manifest=False):
        raw = completed.stdout if completed.returncode == 0 else completed.stderr
        try:
            value = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise CLIError('CLI response is not JSON') from exc
        if (allow_manifest and completed.returncode == 0 and isinstance(value, dict)
                and value.get('manifest_version') == 'v1' and value.get('format') == 'ndjson'
                and isinstance(value.get('records_count'), int)
                and isinstance(value.get('has_more'), bool)
                and isinstance(value.get('record_file'), str)):
            return {'ok': True, 'data': value}
        if not isinstance(value, dict):
            raise CLIError('CLI response must be an object')
        if completed.returncode != 0 or value.get('ok') is not True:
            raise CLIError(json.dumps(value.get('error', value), ensure_ascii=False))
        data = value.get('data', {})
        if isinstance(data, dict) and data.get('code', 0) != 0:
            raise CLIError('Nested remote error: ' + str(data['code']))
        return value

    def call(self, args, *, write=False, attachment=False):
        operation = uuid.uuid4().hex
        argv = ['lark-cli', *args, '--as', 'user']
        if write:
            self._assert_writes_resolved()
            self._journal({'operation': operation, 'state': 'started', 'argv': argv})
        env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1',
                   LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
        process = subprocess.Popen(argv, cwd=self.root, env=env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=self.attachment_timeout if attachment else self.timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            if write:
                self._journal({'operation': operation, 'state': 'unknown', 'reason': 'timeout'})
                raise UnknownWrite('写入超时：先读回对账；禁止直接重发。') from exc
            raise CLIError('Read timed out') from exc
        completed = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        (self.local / (operation + '.json')).write_text(
            json.dumps({'argv': argv, 'exit_code': process.returncode,
                        'stdout': stdout, 'stderr': stderr}, ensure_ascii=False, indent=2))
        try:
            envelope = self.decode(completed, allow_manifest=not write and 'ndjson' in args)
        except CLIError as exc:
            if write:
                self._journal({'operation': operation, 'state': 'unknown', 'reason': str(exc)})
                raise UnknownWrite('写入未确认：先读取远端核对，禁止盲重试。' + str(exc)) from exc
            raise
        if write:
            self._journal({'operation': operation, 'state': 'acknowledged', 'response_file': operation + '.json'})
        return envelope
