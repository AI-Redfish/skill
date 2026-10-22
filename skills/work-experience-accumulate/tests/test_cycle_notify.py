import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import work_experience as we
import dingtalk_notify as dn

SOURCE = {'executable': 'dws', 'profile': 'corp:me', 'notify_user_id': 'me', 'notify_enabled': True}
AUTH = {'authenticated': True, 'corp_id': 'corp', 'user_id': 'me'}
ACCEPT = {'success': True, 'sendReceipt': {'openTaskId': 'task'}}
SUCCESS = {'success': True, 'result': {'sendStatus': 'SUCCESS'}, 'messageRef': {'openMessageId': 'msg', 'openConversationId': 'conv'}}
def response(value):
    return 0, json.dumps(value), ''

class NotifyTests(unittest.TestCase):
    def test_disabled_or_identity_mismatch_never_sends(self):
        with tempfile.TemporaryDirectory() as td:
            runner = Mock()
            self.assertIsNotNone(dn.notify({}, Path(td), runner, we.write_json)[1])
            runner.assert_not_called()
            runner.return_value = response({**AUTH, 'user_id': 'other'})
            self.assertIsNotNone(dn.notify(SOURCE, Path(td), runner, we.write_json)[1])
            self.assertEqual(runner.call_count, 1)

    def test_accept_receipt_success_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            runner = Mock(side_effect=[response(AUTH), response(ACCEPT), response(SUCCESS)])
            state, error = dn.notify(SOURCE, Path(td), runner, we.write_json)
            self.assertIsNone(error)
            self.assertTrue(state['delivered'])
            send = runner.call_args_list[1].args[0]
            self.assertIn('--yes', send)
            self.assertIn('--idempotency-key', send)
            self.assertEqual(send[send.index('--text')+1], dn.TEXT)
            runner = Mock(return_value=response(AUTH))
            self.assertIsNone(dn.notify(SOURCE, Path(td), runner, we.write_json)[1])
            self.assertEqual(runner.call_count, 1)

    def test_status_failure_persists_task_and_resumes_without_send(self):
        with tempfile.TemporaryDirectory() as td:
            runner = Mock(side_effect=[response(AUTH), response(ACCEPT), (1, '', 'private')])
            state, error = dn.notify(SOURCE, Path(td), runner, we.write_json)
            self.assertIsNotNone(error)
            self.assertEqual(state['open_task_id'], 'task')
            self.assertNotIn('private', (Path(td)/'work/notification.json').read_text())
            runner = Mock(side_effect=[response(AUTH), response(SUCCESS)])
            self.assertIsNone(dn.notify(SOURCE, Path(td), runner, we.write_json)[1])
            self.assertNotIn('+messages-send', repr(runner.call_args_list))

    def test_custom_command_uses_bound_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            source = {**SOURCE, 'notify_command': ['{executable}', 'send', '--profile', '{profile}', '--user', '{user_id}', '--text', '{text}', '--key', '{key}']}
            runner = Mock(side_effect=[response(AUTH), response(ACCEPT), response(SUCCESS)])
            state, error = dn.notify(source, Path(td), runner, we.write_json)
            self.assertIsNone(error)
            self.assertTrue(state['delivered'])
            command = runner.call_args_list[1].args[0]
            self.assertEqual(command[0], 'dws')
            self.assertEqual(command[command.index('--profile') + 1], 'corp:me')
            self.assertEqual(command[command.index('--user') + 1], 'me')
            self.assertEqual(command[command.index('--text') + 1], dn.TEXT)
            self.assertTrue(command[command.index('--key') + 1].startswith('work-experience-'))

    def test_unknown_send_never_automatically_retried(self):
        with tempfile.TemporaryDirectory() as td:
            runner = Mock(side_effect=[response(AUTH), (1, '', 'private')])
            self.assertIsNotNone(dn.notify(SOURCE, Path(td), runner, we.write_json)[1])
            runner = Mock(return_value=response(AUTH))
            self.assertIsNotNone(dn.notify(SOURCE, Path(td), runner, we.write_json)[1])
            self.assertEqual(runner.call_count, 1)

    def test_pending_is_bounded_and_then_resumes(self):
        with tempfile.TemporaryDirectory() as td:
            pending = response({'success': True, 'result': {'sendStatus': 'SENDING'}})
            runner = Mock(side_effect=[response(AUTH), response(ACCEPT)]+[pending]*6)
            sleep = Mock()
            state, error = dn.notify(SOURCE, Path(td), runner, we.write_json, sleep=sleep)
            self.assertIsNotNone(error)
            self.assertFalse(state['delivered'])
            self.assertEqual(sleep.call_count, 5)

class PipelineTests(unittest.TestCase):
    def fixture(self, run, failed=True):
        datasets = {'manifest': {'sources': {'dingtalk': not failed, 'zentao': True, 'git': True, 'sessions': True}, 'window': {'start': 's', 'end': 'e'}, 'errors': int(failed)},
                    'git': [{'excluded': [{'reason': 'old', 'path': 'big'}]*10000, 'commits': []}],
                    'dingtalk': {'complete': not failed, 'records': []}, 'zentao': {'complete': True, 'records': []},
                    'sessions': [{'session_id': 's', 'records': [{'text': 'api_key=private', 'type': 'user'}]}],
                    'errors': ['dws source failed'] if failed else []}
        for name, data in datasets.items():
            we.write_json(run/'work'/f'{name}.json', data)
        return datasets

    def test_projection_exclusions_counted_secrets_redacted_and_original_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            self.fixture(run)
            before = (run/'work/git.json').read_bytes()
            data = we.prepare_agent_input(run)
            self.assertEqual(data['sources']['git'][0]['excluded_count'], 10000)
            self.assertNotIn('private', json.dumps(data))
            self.assertEqual(before, (run/'work/git.json').read_bytes())
            self.assertLess((run/'work/agent-input.json').stat().st_size, 10000)

    def test_existing_run_no_collection_no_notification_and_partial_exit(self):
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            run = we.base_dir(wd)/'2000-01-01'/'run'
            self.fixture(run)
            argv = ['pi', '-p', *we.AGENT_SAFETY_FLAGS, '@{run_dir}/work/agent-input.json']
            draft = ("# 工作经验沉淀草稿\n## <analysis>分析\n### 工作项清单\n### 聊天记录逐条细节\n"
                     "## 待确定事项\n## <conclusion>沉淀候选\n### 触发方式与辅助设计\n"
                     "work/manifest.json\n## 审核说明\n待用户审核\n本次不修改任何目标产物。")
            args = argparse.Namespace(workdir=wd, run=str(run), no_notify=True)
            with patch.object(we, 'load_config', return_value={'agent_command': argv}), patch.object(we, 'cmd_collect') as collect, patch.object(we, 'run_argv', return_value=(0,draft,'')), patch.object(we, 'cmd_notify_draft') as notify, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(we.cmd_run_cycle(args), 3)
                collect.assert_not_called()
                notify.assert_not_called()
            self.assertIn('来源不完整', (run/'draft.md').read_text(encoding='utf-8'))
            self.assertFalse((run/'approval.json').exists())

    def test_failed_model_preserves_template_and_no_notification(self):
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            run = we.base_dir(wd)/'2000-01-01'/'run'
            self.fixture(run)
            argv = ['pi', '-p', *we.AGENT_SAFETY_FLAGS]
            args = argparse.Namespace(workdir=wd, run=str(run), no_notify=False)
            with patch.object(we, 'load_config', return_value={'agent_command': argv}), patch.object(we, 'run_argv', return_value=(1,'private','private')), patch.object(we, 'cmd_notify_draft') as notify, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(we.cmd_run_cycle(args), 3)
                notify.assert_not_called()
            self.assertIn('待填写', (run/'draft.md').read_text(encoding='utf-8'))

if __name__ == '__main__':
    unittest.main()
