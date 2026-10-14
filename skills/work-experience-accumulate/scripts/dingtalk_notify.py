"""Self-only dws notifications with persisted asynchronous receipts. No business HTTP."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

TEXT = "沉淀草稿已经生成。"
DEFAULT_SEND = ["{executable}", "chat", "+messages-send", "--as", "user", "--user", "{user_id}",
                "--profile", "{profile}", "--text", "{text}", "--idempotency-key", "{key}", "--yes", "--format", "json"]


def notify(source, run: Path, runner, save, sleep=time.sleep):
    """Never resend an accepted task; unknown delivery stays pending."""
    if source.get('notify_enabled') is not True:
        return None, '本人通知未启用；未发送'
    state_file = run / "work" / "notification.json"
    try:
        exe, profile, user = source['executable'], source['profile'], source['notify_user_id']
        if not all(isinstance(x, str) and x.strip() for x in (exe, profile, user)):
            raise ValueError()
        corp, bound_user = profile.split(':')
        if bound_user != user or not corp:
            raise ValueError()
        code, out, _ = runner([exe, 'auth', 'status', '--profile', profile, '--format', 'json'])
        auth = json.loads(out) if code == 0 else {}
        if auth.get('authenticated') is not True or auth.get('corp_id') != corp or auth.get('user_id') != user:
            return None, '钉钉账号未认证或与本人接收人不一致；未发送'
        state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
        key = 'work-experience-' + hashlib.sha256((str(run.resolve()) + ':' + profile).encode()).hexdigest()[:32]
        if state and (state.get('profile') != profile or state.get('key') != key):
            return None, '通知状态与本次运行或账号不匹配；未发送'
        if state.get('delivered') is True:
            return state, None
        if not state:
            state = {'profile': profile, 'user_id': user, 'key': key, 'delivered': False}
            save(state_file, state)
        if not state.get('open_task_id'):
            # Once transmission is attempted, failure/ambiguity requires manual review.
            if state.get('send_attempted'):
                return state, '通知发送结果不明；禁止自动重复发送，请核对回执'
            state['send_attempted'] = True
            save(state_file, state)
            command = source.get('notify_command') or DEFAULT_SEND
            if (not isinstance(command, list) or not command
                    or any(not isinstance(part, str) or not part.strip() for part in command)):
                return state, '通知命令配置无效；未发送'
            try:
                send_argv = [part.format(executable=exe, profile=profile, user_id=user,
                                         text=TEXT, key=key, run_dir=str(run)) for part in command]
            except (KeyError, ValueError, IndexError):
                return state, '通知命令占位符无效；未发送'
            code, out, _ = runner(send_argv)
            response = json.loads(out) if code == 0 else {}
            nested = response.get('result', {})
            accepted = response.get('success') is True or (response.get('ok') is True and isinstance(nested, dict) and nested.get('success') is True)
            receipt = response.get('sendReceipt', {})
            task = receipt.get('openTaskId') if isinstance(receipt, dict) else None
            if not accepted or not isinstance(task, str) or not task.strip():
                return state, '通知请求未取得有效异步回执；不自动重发'
            state['open_task_id'] = task
            save(state_file, state)
        for attempt in range(6):
            if attempt:
                sleep(2)
            code, out, _ = runner([exe, 'chat', '+messages-query-send-status', '--open-task-id', state['open_task_id'],
                                  '--profile', profile, '--format', 'json'])
            response = json.loads(out) if code == 0 else {}
            result = response.get('result', {})
            if response.get('success') is not True or not isinstance(result, dict):
                return state, '通知回执查询失败；保留任务 ID，未重复发送'
            status = result.get('sendStatus')
            state['send_status'] = status if isinstance(status, str) else 'UNKNOWN'
            if status == 'SUCCESS':
                state['delivered'] = True
                ref = response.get('messageRef', {})
                if isinstance(ref, dict):
                    state['message_ref'] = {k: ref[k] for k in ('openMessageId', 'openConversationId') if isinstance(ref.get(k), str)}
                save(state_file, state)
                return state, None
            save(state_file, state)
            if status not in ('PENDING', 'PROCESSING', 'SENDING', 'INIT', 'RUNNING'):
                return state, '通知投递未确认成功；保留回执，不自动重发'
        return state, '通知仍在处理中；保留任务 ID，未重复发送'
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None, '通知配置或回执无效；未保存原始响应'
