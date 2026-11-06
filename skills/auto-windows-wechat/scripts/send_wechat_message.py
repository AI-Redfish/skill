#!/usr/bin/env python3
"""send_wechat_message.py — 给微信指定联系人 / 群 / 文件传输助手发送文本消息。

通过 Win32 API + 系统 UIA（PowerShell 子进程，零第三方依赖）驱动本机微信客户端：
等键鼠空闲（已空闲则零等待）→ 激活窗口 → UIA 就绪探测（探测进程内轮询）→
单次 UIA 调用完成：回聊天页 / 定位会话（列表精确匹配 / 搜索功能入口）→
会话验证 → 聚焦输入框 → 剪贴板粘贴正文 → 回车发送 → 恢复剪贴板。

性能设计（v1.3.0）：
- 空闲等待用 GetLastInputInfo 判系统级空闲：已空闲 >= 阈值时零等待直接开始；
- UIA 就绪轮询并入导航脚本（单进程完成就绪 + 导航 + 验证 + 聚焦），
  失明时 Python 侧「最小化→还原」恢复后重跑；
- 列表模式单轮判定（主列表一次枚举即可确认目标在否，不空等），
  搜索模式进程内轮询（下拉异步渲染）；
- 典型发送 = 2 次 PowerShell 调用（导航 + 搜索路径导航），已在会话时 1 次。
  典型耗时：搜索路径约 5~6 秒，已在会话约 2.5 秒（不含空闲等待）。

用法:
    uv run send_wechat_message.py -t <联系人备注名|群名|文件传输助手> -m "<消息>"
    uv run send_wechat_message.py <联系人> "<消息>"        # 位置参数
    uv run send_wechat_message.py -m "<消息>"              # 默认发文件传输助手
    uv run send_wechat_message.py -m "<消息>" --no-wait    # 跳过键鼠空闲等待
    uv run send_wechat_message.py -m "<消息>" --restart-wechat
    # UIA 深度失明且常规恢复无效时自动重启微信客户端后继续发送
    echo '{"inputs":{"target":"...","message":"..."}}' | uv run send_wechat_message.py

依赖: 仅 Python 3.10+ 标准库（ctypes/subprocess/json/argparse）+ 系统 PowerShell；
仅 Windows，本机微信客户端需已登录并保持打开（最小化可以）。
退出码: 0=发送成功；1=失败（stdout 末行 JSON 的 output.error 含原因）。
stdout: 末行输出 {"output": {"ok": bool, "target": str, "error": str(仅失败时)}}；
诊断日志走 stderr（[wechat_send] 前缀）。
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes

_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_KERNEL32.GlobalAlloc.restype = ctypes.c_void_p
_KERNEL32.GlobalLock.argtypes = [ctypes.c_void_p]
# 适配 1：必须显式声明 64 位返回类型，否则指针截断导致读剪贴板越界。
_KERNEL32.GlobalLock.restype = ctypes.c_void_p
_KERNEL32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_KERNEL32.GlobalSize.argtypes = [ctypes.c_void_p]
_KERNEL32.GlobalSize.restype = ctypes.c_size_t
_KERNEL32.GetTickCount.restype = wintypes.DWORD
_USER32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
_USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
_USER32.GetForegroundWindow.restype = wintypes.HWND


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_USER32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]

# 微信主窗口候选类名：3.9（Win32/Qt 混合）与 4.0（mmui/Qt）。
_MAIN_WINDOW_CLASSES = {"WeChatMainWndForPC", "Qt51514QWindowIcon", "mmui::MainWindow"}
_LOGIN_WINDOW_CLASS = "mmui::LoginWindow"

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_VK_CONTROL = 0x11
_VK_RETURN = 0x0D
_VK_F = 0x46
_VK_V = 0x56
_VK_ESCAPE = 0x1B
_SW_RESTORE = 9
_SW_SHOW = 5

# 发送前等待用户键鼠空闲：系统级连续 2.5 秒无输入视为间隙，最多等 120 秒。
# 用 GetLastInputInfo 取全局最后输入时间：用户早已空闲时零等待直接通过。
_USER_IDLE_SECONDS = 2.5
_USER_IDLE_MAX_WAIT = 120.0

# 导航脚本（单进程完成 就绪轮询 + 定位 + 验证 + 聚焦输入框）：
# 1) 点左栏「聊天」按钮回聊天页（__SKIP_HOME__=1 时跳过：搜索路径二次调用时
#    已处于搜索覆盖层，点主页会关闭搜索）；
# 2) 进程内点击会话入口：列表模式（__SINGLE_SHOT__=1）一次枚举即判定，
#    不存在的目标不空等；搜索模式轮询最多 __POLL_SEC__ 秒（下拉异步渲染，
#    条目出现即点），替代 Python 侧固定长 sleep；
# 3) 进程内轮询验证会话切换（最多 4 秒）；
# 4) 点击聊天输入框确保键盘焦点（激活窗口不等于聚焦输入框，焦点不在输入框时
#    Ctrl+V/回车会落空，导致 ok:true 但消息未发出的假成功）。
# 入口匹配规则：功能卡片 Button（名以目标开头且含「前往」）优先于 ListItem
# （聊天记录条目第一行也是会话名，先匹配会点开聊天记录预览）；ListItem 取
# 「第一行精确等于目标」，搜索建议分组（点击会进搜一搜页）一律跳过。
_UIA_NAVIGATE_SCRIPT = '''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -Namespace W -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);'
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '微信')
# 就绪轮询：窗口唤出/重启后 Qt 的 UIA 树可能长期失明（实测持续 10 秒以上只有
# 1 个元素），元素数 <= 30 时每 0.5 秒重查，最多等 8 秒（超时输出 NOT_READY，
# 由 Python 侧「最小化→还原」触发窗口重绘强制 UIA 重注册后重跑，实测可恢复）。
$readyDeadline = (Get-Date).AddSeconds(8)
$win = $null
while ($true) {
    $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
    if ($win) {
        $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
        # 元素数达标还不够：Qt 半失明期元素存在但 Name 不可读（实测导致会话
        # 判定全部误判、入口误点收起当前会话），要求至少 5 个元素带非空
        # Name 才算就绪。
        $named = 0
        foreach ($a in $all) { if ($a.Current.Name) { $named++; if ($named -ge 5) { break } } }
        if ($all.Count -gt 30 -and $named -ge 5) { break }
    }
    if ((Get-Date) -ge $readyDeadline) { Write-Output 'NOT_READY'; exit }
    Start-Sleep -Milliseconds 500
}

function Test-InSession {
    # 微信聊天输入框的可访问名 = 当前会话名（Edit.Name）；本机微信 4.0 输入框
    # Name 为空，补充 Document 名判定（「会话名 - 昵称」前缀规则）；搜索框
    # value == 目标不作为肯定判定（搜索残留防护由「- 搜一搜」排除规则承担）。
    $editCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
    foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCond)) {
        if ($e.Current.Name -eq '__TARGET__') { return $true }
    }
    $docCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
    foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $docCond)) {
        $n = $e.Current.Name
        if (-not $n) { continue }
        if ($n -eq '__TARGET__') { return $true }
        if ($n -eq '__TARGET__ - 搜一搜') { return $false }
        if ($n.StartsWith('__TARGET__ - ')) { return $true }
    }
    return $false
}

function Invoke-ClickAt([double]$cx, [double]$cy) {
    [W.U]::SetCursorPos([int]$cx, [int]$cy) | Out-Null
    Start-Sleep -Milliseconds 80
    [W.U]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero)
    [W.U]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
}

$inSession = Test-InSession
if (-not $inSession) {
    # 二次确认：Qt UIA 属性偶发短暂读到空/旧值，实测曾把已打开会话误判为
    # 不在会话，随后的入口点击会收起当前会话导致发送失败。隔 0.5 秒重读
    # 一次，两次一致才认定不在会话、允许导航点击。
    Start-Sleep -Milliseconds 500
    $inSession = Test-InSession
}
if ($inSession) {
    Write-Output 'SESSION=IN_SESSION'
    Write-Output 'ENTRY=ALREADY'
} else {
    # 1) 回聊天页：微信重启后可能停留在内容流等视图，Ctrl+F 在那里无效。
    #    按钮限定窗口左缘 200px 内，避免误点内容区同名元素。
    if ('__SKIP_HOME__' -ne '1') {
        $wr = $win.Current.BoundingRectangle
        $btnCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
        $homeDone = $false
        foreach ($homeName in @('聊天', '微信')) {
            foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)) {
                if ($e.Current.Name -ne $homeName) { continue }
                $r = $e.Current.BoundingRectangle
                if ($r.IsEmpty -or $r.Width -le 0) { continue }
                if ($r.X - $wr.X -gt 200) { continue }
                Invoke-ClickAt ($r.X + $r.Width / 2) ($r.Y + $r.Height / 2)
                Write-Output 'HOME=CLICKED'
                $homeDone = $true
                break
            }
            if ($homeDone) { break }
        }
        if (-not $homeDone) { Write-Output 'HOME=SKIP' }
        Start-Sleep -Milliseconds 300
    }

    # 2) 轮询点击会话入口：不用 ↓+回车（其选中「最佳匹配」第一条，同名群聊 /
    #    相似群排前时会误开群聊，实测发错）；条目点不到则由验证失败兜底取消，
    #    宁可不发不发错。
    $entryDone = $false
    $entryDeadline = (Get-Date).AddSeconds('__POLL_SEC__')
    while ($true) {
        $hit = $null
        $btnCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
        foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)) {
            $name = $e.Current.Name
            if (-not $name) { continue }
            if ($name.StartsWith('__TARGET__') -and $name.Contains('前往')) { $hit = $e; break }
        }
        if (-not $hit) {
            # 搜索下拉里各分组同属一个列表，分组标题行也是 ListItem。「搜索网络
            # 结果」分组下是搜索建议行，点击会进搜一搜页而不是会话（实测踩坑：
            # 文件传输助手的建议行与功能入口首行同名且排在前面）。按当前所在
            # 分组过滤：建议分组下的行一律不点；主会话列表无分组头，不受影响。
            $suggestSections = @('搜索网络结果', '搜索结果', '网络结果', '搜一搜')
            $sectionHeaders = $suggestSections + @('功能', '联系人', '群聊', '群组', '聊天记录')
            $section = ''
            $listCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)
            foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $listCond)) {
                $name = $e.Current.Name
                if ($sectionHeaders -contains $name.Trim()) { $section = $name.Trim(); continue }
                $first = ($name -split "`n")[0].Trim()
                if ($first -eq '__TARGET__') {
                    if ($suggestSections -contains $section) { continue }
                    $hit = $e
                    break
                }
            }
        }
        if ($hit) {
            $rect = $hit.Current.BoundingRectangle
            if (-not $rect.IsEmpty -and $rect.Width -gt 0) {
                Invoke-ClickAt ($rect.X + $rect.Width / 2) ($rect.Y + $rect.Height / 2)
                Write-Output 'ENTRY=CLICKED'
                $entryDone = $true
                break
            }
        }
        if ($entryDone) { break }
        # 列表模式单轮判定：主会话列表一次性枚举即可确认目标在否（与原单次
        # 点击实现行为一致），不存在的目标不空等；搜索下拉异步渲染需轮询。
        if ('__SINGLE_SHOT__' -eq '1') { break }
        if ((Get-Date) -ge $entryDeadline) { break }
        Start-Sleep -Milliseconds 400
    }
    if (-not $entryDone) { Write-Output 'ENTRY=NO_MATCH'; exit }

    # 3) 轮询验证会话切换（点击后切换有延迟）；未进入则取消（未粘贴正文，
    #    微信停留当前状态无副作用；不按 Esc：实测微信 4.0 收到 Esc 会隐藏主窗口）。
    $inSession = $false
    $vDeadline = (Get-Date).AddSeconds(6)
    while ($true) {
        Start-Sleep -Milliseconds 350
        if (Test-InSession) { $inSession = $true; break }
        if ((Get-Date) -ge $vDeadline) { break }
    }
    if (-not $inSession) { Write-Output 'SESSION=NOT_IN_SESSION'; exit }
    Write-Output 'SESSION=IN_SESSION'
}

# 4) 聚焦聊天输入框：识别规则 Edit.Name == 目标（独立聊天窗口形态）；否则
#    Name 为空且宽 >= 200 高 >= 30（主窗口内嵌形态）。搜索框（Name=搜索 /
#    value=搜索词 / 窄条）不匹配。
$inputDone = $false
$iDeadline = (Get-Date).AddSeconds(2)
while ((Get-Date) -lt $iDeadline) {
    $editCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
    foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCond)) {
        $r = $e.Current.BoundingRectangle
        if ($r.IsEmpty -or $r.Width -le 0) { continue }
        $nm = $e.Current.Name
        $v = ''
        $vp = $null
        if ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp)) { $v = $vp.Current.Value }
        $isTarget = $nm -eq '__TARGET__'
        $isChatBox = (-not $nm) -and ($r.Width -ge 200) -and ($r.Height -ge 30) -and ($v -ne '__TARGET__')
        if (-not ($isTarget -or $isChatBox)) { continue }
        Invoke-ClickAt ($r.X + $r.Width / 2) ($r.Y + $r.Height / 2)
        Write-Output 'INPUT=CLICKED'
        $inputDone = $true
        break
    }
    if ($inputDone) { break }
    Start-Sleep -Milliseconds 300
}
if (-not $inputDone) { Write-Output 'INPUT=NO_MATCH' }
'''


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_byte * 32)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _log(message: str) -> None:
    """诊断输出走 stderr（UTF-8），stdout 保留给工作流 JSON。"""
    stream = getattr(sys.stderr, "buffer", None)
    if stream is not None:
        stream.write(f"[wechat_send] {message}\n".encode("utf-8", errors="replace"))
        stream.flush()
    else:  # pragma: no cover
        print(f"[wechat_send] {message}", file=sys.stderr)


# ------------------------------ 对外接口 ------------------------------


def send_message(target: str, text: str, wait_idle: bool = True,
                 restart_wechat: bool = False) -> None:
    """向 target 会话发送文本 text。成功返回；失败抛异常（信息即原因）。"""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target 不能为空（联系人备注名 / 群名 / 文件传输助手）")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text 不能为空（要发送的消息文本）")
    target = target.strip()

    hwnd = _find_wechat_hwnd()
    # 发送前先等用户键鼠空闲：避免与用户争抢鼠标导致消息发错窗口。
    # 已空闲（系统级空闲 >= 阈值）时零等待直接通过。
    if wait_idle and not _wait_user_idle():
        raise RuntimeError(
            f"等待 {_USER_IDLE_MAX_WAIT:.0f} 秒用户仍在使用键鼠，已取消发送（宁可不发也不抢鼠标）"
        )
    _activate_window(hwnd)
    original_clipboard = _get_clipboard_text()

    try:
        # 1. 导航 + 验证 + 聚焦输入框：单次 PowerShell 调用完成（脚本开头内置
        #    UIA 就绪轮询，失明时恢复后重跑）。已在目标会话时脚本内直接跳到
        #    聚焦（重复点击当前会话条目会收起会话，导致发送失败）。列表模式
        #    单轮判定：主列表一次枚举即可确认目标在否，不存在的目标不空等。
        nav = _navigate_with_recovery(hwnd, target, skip_home=False,
                                      entry_poll_seconds=3, single_shot=True,
                                      restart_on_blind=restart_wechat)
        if nav.get("entry") not in ("CLICKED", "ALREADY"):
            # 2. 目标会话不在可见列表：搜索路径。
            #    Ctrl+F → 剪贴板粘贴目标名 → 再跑一次导航（跳过回主页——搜索
            #    覆盖层下点主页会关闭搜索；入口轮询延长到 6 秒等下拉渲染）。
            _set_clipboard_text(target)
            _combo(_VK_CONTROL, _VK_F)
            time.sleep(0.3)
            _combo(_VK_CONTROL, _VK_V)
            time.sleep(0.3)
            nav = _navigate_with_recovery(hwnd, target, skip_home=True,
                                          entry_poll_seconds=6, single_shot=False,
                                          restart_on_blind=restart_wechat)
        if nav.get("session") != "IN_SESSION":
            raise RuntimeError(f"未能确认微信已进入「{target}」会话，已取消发送以避免发错窗口")
        if nav.get("input") != "CLICKED":
            _log("未定位到聊天输入框，按原状态直接粘贴发送")

        # 3. 正文走剪贴板粘贴，规避输入法与特殊字符问题。输入框已在导航脚本内
        #    点击聚焦，这里只留短间隔保证输入落定。
        time.sleep(0.1)
        _set_clipboard_text(text)
        time.sleep(0.15)
        _combo(_VK_CONTROL, _VK_V)
        time.sleep(0.25)
        _press(_VK_RETURN)
        time.sleep(0.2)
    finally:
        # 尽力恢复用户剪贴板；恢复失败不影响发送结果。稍等微信读完剪贴板
        # （粘贴后其读取可能尚未结束，立即覆写偶发 access violation）。
        time.sleep(0.4)
        if original_clipboard is not None:
            try:
                _set_clipboard_text(original_clipboard)
            except Exception:  # noqa: BLE001
                pass


# ------------------------------ Win32 基础操作 ------------------------------


def _enum_windows(visible_only: bool = True) -> list[tuple[int, str, str]]:
    results: list[tuple[int, str, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def on_window(hwnd: int, _lparam: int) -> bool:
        if visible_only and not _USER32.IsWindowVisible(hwnd):
            return True
        length = _USER32.GetWindowTextLengthW(hwnd)
        title = ""
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            _USER32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
        class_buffer = ctypes.create_unicode_buffer(256)
        _USER32.GetClassNameW(hwnd, class_buffer, 256)
        results.append((hwnd, class_buffer.value, title))
        return True

    _USER32.EnumWindows(callback_type(on_window), 0)
    return results


def _find_wechat_hwnd() -> int:
    """定位微信主窗口；返回句柄。未登录 / 未找到时抛出明确错误。

    微信 4.0 点 X / 收到 Esc 会把主窗口隐藏到托盘（SW_HIDE），导致
    「未找到微信主窗口」。可见窗口找不到时按类名在隐藏窗口中找主窗口并
    自动唤出（ShowWindow 恢复），避免一次取消后后续全部失败。
    """
    candidates: list[int] = []
    hidden_candidate: int | None = None
    login_hwnd: int | None = None

    for hwnd, class_name, title in _enum_windows(visible_only=False):
        if "微信" not in title and "WeChat" not in title and "Weixin" not in title:
            continue
        if class_name == _LOGIN_WINDOW_CLASS:
            login_hwnd = hwnd
            continue
        if class_name in _MAIN_WINDOW_CLASSES and title.strip() in ("微信", "WeChat", "Weixin"):
            if _USER32.IsWindowVisible(hwnd):
                candidates.append(hwnd)
            elif hidden_candidate is None:
                hidden_candidate = hwnd

    if candidates:
        return candidates[0]
    if hidden_candidate is not None:
        _USER32.ShowWindow(hidden_candidate, _SW_RESTORE)
        _USER32.ShowWindow(hidden_candidate, _SW_SHOW)
        time.sleep(0.6)
        if _USER32.IsWindowVisible(hidden_candidate):
            _log("微信主窗口已隐藏到托盘，已自动唤出")
            return hidden_candidate
    if login_hwnd is not None:
        raise RuntimeError("微信当前停在登录窗口，请先登录微信")
    raise RuntimeError("未找到微信主窗口（请确认微信已登录并保持打开）")


def _activate_window(hwnd: int) -> None:
    if _USER32.IsIconic(hwnd):
        _USER32.ShowWindow(hwnd, _SW_RESTORE)
        time.sleep(0.3)
    _USER32.SetForegroundWindow(hwnd)
    time.sleep(0.1)
    if _USER32.GetForegroundWindow() != hwnd:
        # 前台切换限制：模拟一次 Alt 按下以获得 SetForegroundWindow 权限。
        _USER32.keybd_event(0x12, 0, 0, 0)
        _USER32.SetForegroundWindow(hwnd)
        _USER32.keybd_event(0x12, 0, _KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)
    if _USER32.GetForegroundWindow() != hwnd:
        # 激活失败就中止：后续按键会落到当前前台窗口（如编辑器），造成误操作。
        raise RuntimeError("无法把微信窗口带到前台（正被其他窗口/全屏应用占用），已取消本次发送")
    time.sleep(0.2)


def _press(vk: int) -> None:
    _USER32.keybd_event(vk, 0, 0, 0)
    _USER32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def _combo(vk: int, action_vk: int) -> None:
    _USER32.keybd_event(vk, 0, 0, 0)
    _USER32.keybd_event(action_vk, 0, 0, 0)
    _USER32.keybd_event(action_vk, 0, _KEYEVENTF_KEYUP, 0)
    _USER32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def _set_clipboard_text(text: str) -> None:
    if not _USER32.OpenClipboard(None):
        raise OSError("打开剪贴板失败")
    try:
        _USER32.EmptyClipboard()
        size = (len(text) + 1) * 2
        handle = _KERNEL32.GlobalAlloc(_GMEM_MOVEABLE, size)
        if not handle:
            raise OSError("GlobalAlloc 失败")
        pointer = _KERNEL32.GlobalLock(handle)
        if not pointer:
            raise OSError(f"GlobalLock 失败：{ctypes.GetLastError()}")
        ctypes.memmove(pointer, ctypes.create_unicode_buffer(text), size)
        _KERNEL32.GlobalUnlock(handle)
        if not _USER32.SetClipboardData(_CF_UNICODETEXT, handle):
            _KERNEL32.GlobalFree(handle)
            raise OSError("SetClipboardData 失败")
    finally:
        _USER32.CloseClipboard()


def _get_clipboard_text() -> str | None:
    """读取当前剪贴板文本（仅 CF_UNICODETEXT），用于发送后恢复。"""
    if not _USER32.OpenClipboard(None):
        return None
    try:
        _USER32.GetClipboardData.restype = ctypes.c_void_p
        handle = _USER32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return None
        pointer = _KERNEL32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            # 按分配大小限量读取：wstring_at 无界读取遇到未按 NUL 结尾的
            # 剪贴板数据会越界（access violation），此处以字节读入再解码。
            size = _KERNEL32.GlobalSize(handle) or 0
            if not size:
                return None
            raw = ctypes.string_at(pointer, size)
            return raw.decode("utf-16-le", errors="ignore").rstrip("\x00") or None
        finally:
            _KERNEL32.GlobalUnlock(handle)
    finally:
        _USER32.CloseClipboard()


def _system_idle_seconds() -> float:
    """系统级键鼠空闲秒数（GetLastInputInfo：全局最后一次真实/注入输入时刻）。

    等待阶段本进程不注入任何输入，读数即用户真实活动；比轮询光标 +
    GetAsyncKeyState 更可靠（不会漏掉两次轮询之间的快速敲键）。
    """
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not _USER32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    now = _KERNEL32.GetTickCount()
    delta = (int(now) - int(info.dwTime)) & 0xFFFFFFFF  # GetTickCount 约 49.7 天回绕
    return delta / 1000.0


def _wait_user_idle(idle_seconds: float = _USER_IDLE_SECONDS, max_wait: float = _USER_IDLE_MAX_WAIT) -> bool:
    """阻塞到用户键鼠空闲（系统级连续 idle_seconds 无输入）才返回 True。

    用户早已空闲时首次检查立即通过（零等待）；仅当用户正在活动时等待其停下。
    超时仍不空闲返回 False（调用方放弃，宁可不发也不抢用户鼠标）。
    """
    deadline = time.monotonic() + max_wait
    while True:
        if _system_idle_seconds() >= idle_seconds:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


# ------------------------------ UIA 会话定位与验证 ------------------------------


def _run_uia_script(script: str, timeout: float) -> str:
    """在独立 PowerShell 进程执行 UIA 脚本，返回其标准输出。"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        _log(f"UIA 脚本执行失败：{error}")
        return "SCRIPT_ERROR"
    return result.stdout or ""


def _navigate_and_verify(target: str, skip_home: bool, entry_poll_seconds: int,
                         single_shot: bool, timeout: float = 40.0) -> dict[str, str]:
    """单次 PowerShell 调用完成：就绪轮询 + 回主页 + 点会话入口 + 会话验证 + 聚焦。

    返回 {"home": ..., "entry": ..., "session": ..., "input": ...}（出现哪项
    含哪项）。ready=NOT_READY 表示 UIA 树失明（调用方恢复后重跑）；entry
    非 CLICKED/ALREADY 表示入口未命中（调用方走搜索路径）；session!=
    IN_SESSION 表示验证失败（调用方取消发送）。已在目标会话时脚本输出
    ENTRY=ALREADY 并直接聚焦输入框。
    """
    script = (_UIA_NAVIGATE_SCRIPT
              .replace("__TARGET__", target)
              .replace("__SKIP_HOME__", "1" if skip_home else "0")
              .replace("__POLL_SEC__", str(entry_poll_seconds))
              .replace("__SINGLE_SHOT__", "1" if single_shot else "0"))
    output = _run_uia_script(script, timeout)
    result: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if line == "NOT_READY":
            result["ready"] = "NOT_READY"
            continue
        key, sep, value = line.partition("=")
        if sep and key.lower() in ("home", "entry", "session", "input") and key.lower() not in result:
            result[key.lower()] = value
    _log(f"导航结果：{result or output.strip()[:60]}")
    return result


def _get_wechat_process_path() -> str:
    """查询微信主进程可执行文件路径（Weixin.exe = 4.0 / WeChat.exe = 3.9）。"""
    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
        "$p = Get-Process Weixin, WeChat -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path } | Select-Object -First 1;"
        "if ($p) { Write-Output $p.Path }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return lines[0] if lines else ""


def _restart_wechat_and_wait(max_wait: float = 90.0) -> int:
    """结束微信进程并重新拉起，等待主窗口就绪，返回新窗口句柄。

    用于 UIA 深度失明（托盘唤出后整树仅 1 元素；最小化还原/隐藏显示/
    尺寸微调均无效且不随等待自愈，实测）：重启客户端是唯一可靠解法。
    停在登录窗口时抛错（需用户手机确认登录）。
    """
    exe_path = _get_wechat_process_path()
    if not exe_path:
        raise RuntimeError("未找到微信进程路径，无法自动重启；请手动打开微信后重试")
    _log("常规恢复无效，自动重启微信客户端")
    subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "WeChat.exe"], capture_output=True)
    time.sleep(2.0)
    subprocess.Popen([exe_path], close_fds=True)
    deadline = time.monotonic() + max_wait
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            hwnd = _find_wechat_hwnd()
        except RuntimeError as error:
            if "登录窗口" in str(error):
                # 自动登录时登录窗一闪而过，给 8 秒过渡再复查一次。
                time.sleep(8.0)
                try:
                    hwnd = _find_wechat_hwnd()
                except RuntimeError as error2:
                    raise RuntimeError("微信重启后停在登录窗口，请确认登录后重新发起发送") from error2
                _log("微信已重启并完成登录，主窗口就绪")
                return hwnd
            last_error = error
            time.sleep(1.0)
            continue
        _log("微信已重启，主窗口就绪")
        return hwnd
    raise RuntimeError(f"微信重启后 {max_wait:.0f} 秒未见主窗口（最后状态：{last_error}）；请手动检查微信")


def _navigate_with_recovery(hwnd: int, target: str, skip_home: bool,
                            entry_poll_seconds: int, single_shot: bool,
                            max_wait: float = 24.0,
                            restart_on_blind: bool = False) -> dict[str, str]:
    """导航并处理 UIA 失明：NOT_READY 时「最小化→还原」恢复后重跑，最多 max_wait 秒。

    restart_on_blind=True 时，常规恢复耗尽仍失明则自动重启微信客户端再继续
    一次（重启分支最多触发一次，防止反复杀进程）。
    """
    deadline = time.monotonic() + max_wait
    last_revive = 0.0
    attempts = 0
    restarted = False
    while True:
        nav = _navigate_and_verify(target, skip_home=skip_home,
                                   entry_poll_seconds=entry_poll_seconds,
                                   single_shot=single_shot)
        if nav.get("ready") != "NOT_READY":
            return nav
        if time.monotonic() - last_revive >= 3.0:
            attempts += 1
            _log(f"微信窗口 UIA 树未就绪，第 {attempts} 次最小化→还原触发恢复")
            _USER32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            time.sleep(0.6)
            _USER32.ShowWindow(hwnd, _SW_RESTORE)
            _USER32.SetForegroundWindow(hwnd)
            last_revive = time.monotonic()
        if time.monotonic() >= deadline:
            if restart_on_blind and not restarted:
                restarted = True
                hwnd = _restart_wechat_and_wait()
                deadline = time.monotonic() + max_wait
                last_revive = time.monotonic()
                continue
            _log(f"微信窗口 UIA 树等待超时（共恢复 {attempts} 次），继续尝试发送（可能失败）")
            return nav
        time.sleep(0.5)


# ------------------------------ 入口（工作流 / CLI 双模式） ------------------------------

def main(context: dict) -> dict:
    """工作流兼容入口：context 含 {"inputs": {...}}；返回 dict 作为节点输出。"""
    inputs = context.get("inputs")
    if isinstance(inputs, str):
        try:
            inputs = json.loads(inputs)
        except ValueError:
            return {"output": {"ok": False, "error": "inputs 为字符串但不是合法 JSON"}}
    if not isinstance(inputs, dict):
        inputs = {}

    target = inputs.get("target") or "文件传输助手"
    message = inputs.get("message")
    wait_idle = inputs.get("wait_idle", True)
    restart_wechat = inputs.get("restart_wechat", False)

    if not isinstance(target, str) or not target.strip():
        return {"output": {"ok": False, "error": "target 需为非空字符串（联系人备注名 / 群名）"}}
    if not isinstance(message, str) or not message.strip():
        return {"output": {"ok": False, "target": target.strip(), "error": "缺少必填参数 message（要发送的文本）"}}

    result = _send(target.strip(), message, wait_idle=wait_idle is not False,
                   restart_wechat=restart_wechat is True)
    return {"output": result}


def _cli_result(argv: list[str]) -> dict:
    """命令行参数入口：argv 走 Windows 宽字符 API，中文无编码问题。

    注意不要用 PowerShell 的 echo 管道传中文 JSON——其 $OutputEncoding 默认
    ASCII，中文会变 ? 后才进入本进程，信息已丢失无法恢复。
    """
    parser = argparse.ArgumentParser(
        description="微信消息发送：给指定联系人 / 群 / 文件传输助手发送文本消息",
    )
    parser.add_argument("target_pos", nargs="?", default=None, help="目标会话名（位置参数 1）")
    parser.add_argument("message_pos", nargs="?", default=None, help="消息文本（位置参数 2）")
    parser.add_argument("-t", "--target", default=None, help="目标会话名（联系人备注名 / 群名，默认文件传输助手）")
    parser.add_argument("-m", "--message", default=None, help="要发送的文本")
    parser.add_argument("--no-wait", action="store_true", help="跳过键鼠空闲等待（默认等待）")
    parser.add_argument("--restart-wechat", action="store_true",
                        help="UIA 深度失明且常规恢复无效时自动重启微信客户端再继续（默认关闭）")
    args = parser.parse_args(argv)

    target = args.target if args.target is not None else args.target_pos
    message = args.message if args.message is not None else args.message_pos
    inputs = {"target": target, "message": message, "wait_idle": not args.no_wait,
              "restart_wechat": bool(args.restart_wechat)}
    return main({"inputs": inputs})


def _send(target: str, message: str, wait_idle: bool, restart_wechat: bool = False) -> dict:
    try:
        send_message(target, message, wait_idle=wait_idle, restart_wechat=restart_wechat)
        return {"ok": True, "target": target}
    except Exception as error:  # noqa: BLE001
        error_text = f"{type(error).__name__}: {error}"
        if target == "文件传输助手":
            error_text += (
                "（提示：文件传输助手需在聊天列表可见才能发送——"
                "可在微信中将其置顶，或先手动给它发一条消息后重试）"
            )
        return {"ok": False, "target": target, "error": error_text}


if __name__ == "__main__":
    # 工作流引擎/管道按 UTF-8 读写；Windows 下 Python 默认跟随系统编码（GBK），需显式切换。
    for _stream in (sys.stdin, sys.stdout):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    result = _cli_result(sys.argv[1:]) if len(sys.argv) > 1 else main(json.loads(sys.stdin.read() or "{}"))
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["output"].get("ok") else 1)
