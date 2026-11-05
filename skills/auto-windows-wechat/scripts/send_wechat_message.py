#!/usr/bin/env python3
"""send_wechat_message.py — 给微信指定联系人 / 群 / 文件传输助手发送文本消息。

通过 Win32 API + 系统 UIA（ctypes 纯标准库，零第三方依赖）驱动本机微信客户端：
等键鼠空闲 → 激活窗口 → 定位会话（列表精确匹配 / 搜索功能入口 / 搜索下拉）→
UIA 验证当前会话 → 剪贴板粘贴正文 → 回车发送 → 恢复剪贴板。

用法:
    uv run send_wechat_message.py -t <联系人备注名|群名|文件传输助手> -m "<消息>"
    uv run send_wechat_message.py <联系人> "<消息>"        # 位置参数
    uv run send_wechat_message.py -m "<消息>"              # 默认发文件传输助手
    uv run send_wechat_message.py -m "<消息>" --no-wait    # 跳过键鼠空闲等待
    echo '{"inputs":{"target":"...","message":"..."}}' | uv run send_wechat_message.py

依赖: 仅 Python 3.10+ 标准库（ctypes/subprocess/json/argparse）；仅 Windows，
本机微信客户端需已登录并保持打开（最小化可以）。
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
_USER32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
_USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
_USER32.GetForegroundWindow.restype = wintypes.HWND

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

# 发送前等待用户键鼠空闲：连续 2.5 秒无活动视为间隙，最多等 120 秒。
_USER_IDLE_SECONDS = 2.5
_USER_IDLE_MAX_WAIT = 120.0

# 聊天输入框定位脚本：发送前点击输入框确保焦点（激活窗口不等于聚焦输入框；
# 焦点不在输入框时 Ctrl+V/回车会落空，导致 ok:true 但消息未发出的假成功）。
# 识别规则：Edit.Name == 目标（独立聊天窗口形态）；否则 Name 为空且
# 宽 >= 200 高 >= 30（主窗口内嵌形态）。搜索框（Name=搜索 / value=搜索词 /
# 窄条）不匹配。只输出坐标判定字。
_UIA_INPUT_BOX_SCRIPT = """
Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '微信')
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output 'NO_WINDOW'; exit }
$editCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCond)) {
    $r = $e.Current.BoundingRectangle
    if ($r.IsEmpty -or $r.Width -le 0) { continue }
    $nm = $e.Current.Name
    $vp = $null
    $v = ""
    if ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp)) { $v = $vp.Current.Value }
    $isTarget = $nm -eq '__TARGET__'
    $isChatBox = (-not $nm) -and ($r.Width -ge 200) -and ($r.Height -ge 30) -and ($v -ne '__TARGET__')
    if (-not ($isTarget -or $isChatBox)) { continue }
    $x = [int]($r.X + $r.Width / 2)
    $y = [int]($r.Y + $r.Height / 2)
    Write-Output ("HIT x=$x y=$y")
    Add-Type -Namespace W -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);'
    [W.U]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 80
    [W.U]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero)
    [W.U]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
    Write-Output 'CLICKED'
    exit
}
Write-Output 'NO_MATCH'
"""

# 回聊天页脚本：微信重启后可能停留在内容流等非聊天视图，Ctrl+F 与搜索框
# 在该视图下无效。点击左侧栏「聊天」按钮回到聊天列表（找不到时兜底「微信」
# 按钮）；按钮限定窗口左缘 200px 内，避免误点内容区同名元素。只输出判定字。
_UIA_HOME_BUTTON_SCRIPT = """
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '微信')
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output 'NO_WINDOW'; exit }
$wr = $win.Current.BoundingRectangle
$btnCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
foreach ($name in @('聊天', '微信')) {
    foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)) {
        if ($e.Current.Name -ne $name) { continue }
        $r = $e.Current.BoundingRectangle
        if ($r.IsEmpty -or $r.Width -le 0) { continue }
        if ($r.X - $wr.X -gt 200) { continue }
        $x = [int]($r.X + $r.Width / 2)
        $y = [int]($r.Y + $r.Height / 2)
        Write-Output ("HIT x=$x y=$y")
        Add-Type -Namespace W -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);'
        [W.U]::SetCursorPos($x, $y) | Out-Null
        Start-Sleep -Milliseconds 80
        [W.U]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero)
        [W.U]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
        Write-Output 'CLICKED'
        exit
    }
}
Write-Output 'NO_MATCH'
"""

# UIA 就绪探测：微信窗口唤出/重启后 Qt 的 UIA 树可能长期只有极少元素
# （实测持续 10 秒以上只有 1 个元素），后续验证/点击全部落空。轮询元素数，
# 过低时用「最小化→还原」触发窗口重绘强制 UIA 重注册（实测可恢复）。
_UIA_READY_SCRIPT = """
Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '微信')
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output 'NO_WINDOW'; exit }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
Write-Output ("COUNT=" + $all.Count)
"""

# 会话验证脚本（PowerShell + 系统 UIA）：微信聊天输入框的可访问名 = 当前会话名，
# 输入框存在名为目标会话的 Edit 元素即确认已进入目标会话。结果只输出判定字。
# 适配 2：本机微信 4.0 输入框 Name 为空，补充 Document 名判定与搜索框排除。
_UIA_VERIFY_SCRIPT = '''
Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '微信')
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output 'NO_WINDOW'; exit }
$editType = [System.Windows.Automation.ControlType]::Edit
$editCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, $editType)
foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCond)) {
    if ($e.Current.Name -eq '__TARGET__') { Write-Output 'IN_SESSION'; exit }
}
# 不在此处按「搜索框 value == 目标」早退否定：点击功能卡片进入会话后，
# 搜一搜页面的搜索框仍残留搜索词，会误杀真正会话输入框（Name==目标）的
# 命中；搜索残留的防护由下方 Document 的「- 搜一搜」排除规则承担。
$docCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $docCond)) {
    $n = $e.Current.Name
    if (-not $n) { continue }
    if ($n -eq '__TARGET__') { Write-Output 'IN_SESSION'; exit }
    if ($n -eq '__TARGET__ - 搜一搜') { Write-Output 'NOT_IN_SESSION'; exit }
    if ($n.StartsWith('__TARGET__ - ')) { Write-Output 'IN_SESSION'; exit }
}
Write-Output 'NOT_IN_SESSION'
'''

# 会话入口点击脚本（PowerShell + 系统 UIA）：与 AgentR 原实现一致——
# 会话列表项 / 搜索下拉条目的可访问名是多行文本，第一行 = 会话名（联系人条目；
# 群聊条目第一行 = 群名）。匹配条件为「第一行精确等于目标」：原实现 StartsWith 前缀匹配会误点群聊条目（群名以目标开头）与聊天记录摘要条目，导致消息发进群聊。
# 命中后点击条目左中部。只输出判定字。
_UIA_CLICK_ENTRY_SCRIPT = '''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '微信')
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output 'NO_WINDOW'; exit }
# 功能入口优先（文件传输助手等「功能」类目标）：搜索结果页的功能卡片
# Button，名如「文件传输助手 手机和电脑之间传输文件 前往」。以目标开头且
# 含「前往」才命中。必须先于 ListItem 检查：搜索结果里「聊天记录」分类的
# 条目第一行也是会话名（如与文件传输助手的聊天记录条目），若先匹配会点开
# 聊天记录预览而非会话。普通联系人无此 Button 形态，不受影响。
$target = $null
$btnCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)) {
    $name = $e.Current.Name
    if (-not $name) { continue }
    if ($name.StartsWith('__TARGET__') -and $name.Contains('前往')) { $target = $e; break }
}
if (-not $target) {
    # 搜索下拉里各分组（建议/功能/聊天记录）同属一个列表，分组标题行本身
    # 也是 ListItem。「搜索网络结果」分组下是搜索建议行，点击会进搜一搜页
    # 而不是会话（实测踩坑：文件传输助手的建议行与功能入口首行同名，且
    # 排在前面）。按当前所在分组过滤：建议分组下的行一律不点；主会话
    # 列表无分组头（section 保持空串），不受影响，保持原行为。
    $suggestSections = @('搜索网络结果', '搜索结果', '网络结果', '搜一搜')
    $sectionHeaders = $suggestSections + @('功能', '联系人', '群聊', '群组', '聊天记录')
    $section = ''
    $listCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)
    $items = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $listCond)
    foreach ($e in $items) {
        $name = $e.Current.Name
        if ($sectionHeaders -contains $name.Trim()) { $section = $name.Trim(); continue }
        $first = ($name -split "`n")[0].Trim()
        if ($first -eq '__TARGET__') {
            if ($suggestSections -contains $section) { continue }
            $target = $e; break
        }
    }
}
if (-not $target) { Write-Output 'NO_MATCH'; exit }
$rect = $target.Current.BoundingRectangle
if ($rect.IsEmpty -or $rect.Width -le 0) { Write-Output 'NO_RECT'; exit }
$x = [int]($rect.X + $rect.Width / 2)
$y = [int]($rect.Y + $rect.Height / 2)
Write-Output ("HIT x=$x y=$y")
Add-Type -Namespace W -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);'
[W.U]::SetCursorPos($x, $y) | Out-Null
Start-Sleep -Milliseconds 80
[W.U]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero)
[W.U]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
Write-Output 'CLICKED'
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


def send_message(target: str, text: str, wait_idle: bool = True) -> None:
    """向 target 会话发送文本 text。成功返回；失败抛异常（信息即原因）。

    流程与 AgentR 原实现 _send_via_win32 一致。
    """
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target 不能为空（联系人备注名 / 群名 / 文件传输助手）")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text 不能为空（要发送的消息文本）")
    target = target.strip()

    hwnd = _find_wechat_hwnd()
    # 发送前先等用户键鼠空闲：避免与用户争抢鼠标导致消息发错窗口。
    if wait_idle and not _wait_user_idle():
        raise RuntimeError(
            f"等待 {_USER_IDLE_MAX_WAIT:.0f} 秒用户仍在使用键鼠，已取消发送（宁可不发也不抢鼠标）"
        )
    _activate_window(hwnd)
    # UIA 就绪：失明状态（元素数极低）下「最小化→还原」强制恢复，否则
    # 验证/点击/搜索全部落空。
    _ensure_uia_ready(hwnd)
    # 回聊天页：微信重启后可能停留在内容流等视图，Ctrl+F 在那里无效。
    _click_home_button()
    time.sleep(0.6)
    original_clipboard = _get_clipboard_text()

    try:
        # 0. 先判断是否已在目标会话：微信 4.0 里重复点击当前已打开的会话条目
        #    会取消选中/收起会话，导致输入框消失、后续发送失败。
        #    已在目标会话时跳过入口点击，直接粘贴发送。
        if _verify_wechat_session(target, attempts=1):
            _log(f"已处于目标会话，跳过入口点击：target={target}")
        else:
            # 1. 直击会话列表：列表项可访问名以会话名开头（含置顶/最近会话），
            #    点击即进入会话。
            entered = _click_list_entry(target)
            if not entered:
                # 2. 目标会话不在可见列表：搜索路径。
                #    Ctrl+F → 剪贴板粘贴目标名 → UIA 精确点击下拉条目。
                #    不用 ↓+回车：其选中「最佳匹配」第一条，同名群聊 / 相似群
                #    排在前面时会误开群聊（实测发错）；条目点不到则由验证
                #    失败兜底取消，宁可不发不发错。
                _set_clipboard_text(target)
                _combo(_VK_CONTROL, _VK_F)
                time.sleep(0.6)
                _combo(_VK_CONTROL, _VK_V)
                time.sleep(1.5)
                _click_list_entry(target)
            time.sleep(1.0)

            # 3. 发送前验证（内置重试：会话切换有延迟）：确认微信聊天输入框当前
            #    就是目标会话，未进入目标会话时按 Esc 恢复并取消发送。
            if not _verify_wechat_session(target):
                # 不按 Esc「恢复」：本机实测微信 4.0 收到 Esc 会把主窗口隐藏
                # （连带后续调用报「未找到微信主窗口」）。未进入目标会话时尚未
                # 粘贴正文，微信停留当前状态即无副作用，直接取消即可。
                raise RuntimeError(f"未能确认微信已进入「{target}」会话，已取消发送以避免发错窗口")

        # 4. 正文走剪贴板粘贴，规避输入法与特殊字符问题。
        #    粘贴前点击输入框确保焦点：激活窗口不等于聚焦输入框，焦点不在
        #    输入框时 Ctrl+V/回车会落空（ok:true 但消息未发出的假成功）。
        if not _focus_chat_input(target):
            _log("未定位到聊天输入框，按原状态直接粘贴发送")
        time.sleep(0.3)
        _set_clipboard_text(text)
        time.sleep(0.15)
        _combo(_VK_CONTROL, _VK_V)
        time.sleep(0.35)
        _press(_VK_RETURN)
        time.sleep(0.4)
    finally:
        # 尽力恢复用户剪贴板；恢复失败不影响发送结果。稍等微信读完剪贴板
        # （粘贴后其读取可能尚未结束，立即覆写偶发 access violation）。
        time.sleep(0.8)
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
    time.sleep(0.4)


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


def _cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    _USER32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _user_active_since(last_seen: float) -> bool:
    """检测自 last_seen 起是否有真实键鼠活动（不包含本进程模拟的输入）。"""
    x, y = _cursor_pos()
    if (x, y) != last_seen:
        return True
    for vk in range(0x01, 0xFE):
        # 最高位：自上次 GetAsyncKeyState 调用以来键被按下过（真实或注入）。
        if _USER32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False


def _wait_user_idle(idle_seconds: float = _USER_IDLE_SECONDS, max_wait: float = _USER_IDLE_MAX_WAIT) -> bool:
    """阻塞到用户键鼠空闲（连续 idle_seconds 无移动/按键）才返回 True。

    等待阶段本进程不注入任何输入，读数即为用户真实活动。
    超时仍不空闲返回 False（调用方放弃，宁可不发也不抢用户鼠标）。
    """
    deadline = time.monotonic() + max_wait
    last_pos = _cursor_pos()
    last_activity = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.25)
        now = time.monotonic()
        if _user_active_since(last_pos):
            last_activity = now
            last_pos = _cursor_pos()
        if now - last_activity >= idle_seconds:
            return True
    return False


# ------------------------------ UIA 会话定位与验证 ------------------------------


def _uia_element_count(timeout: float = 20.0) -> int:
    """返回微信窗口 UIA 后代元素数；窗口不可见返回 -1。"""
    output = _run_uia_script(_UIA_READY_SCRIPT, "", timeout)
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("COUNT="):
            value = line[len("COUNT="):]
            return int(value) if value.isdigit() else -1
    return -1


def _ensure_uia_ready(hwnd: int, max_wait: float = 24.0) -> None:
    """等待微信窗口 UIA 树就绪；失明时用「最小化→还原」强制恢复。

    实测窗口唤出后 UIA 树可能长期只有 1 个元素（Qt UIA provider 未重注册），
    最小化再还原会触发窗口重绘，恢复后元素数 > 30。恢复动作可能需要多次
    才生效，纳入循环重试（每 3 秒最多一次）。
    """
    deadline = time.monotonic() + max_wait
    last_revive = 0.0
    attempts = 0
    while time.monotonic() < deadline:
        count = _uia_element_count()
        if count > 30:
            if attempts:
                _log(f"UIA 树已恢复（元素数={count}）")
            return
        if time.monotonic() - last_revive >= 3.0:
            attempts += 1
            _log(f"微信窗口 UIA 树未就绪（元素数={count}），第 {attempts} 次最小化→还原触发恢复")
            _USER32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            time.sleep(0.6)
            _USER32.ShowWindow(hwnd, _SW_RESTORE)
            _USER32.SetForegroundWindow(hwnd)
            last_revive = time.monotonic()
        time.sleep(1.2)
    _log(f"微信窗口 UIA 树等待超时（共尝试恢复 {attempts} 次），继续尝试发送（可能失败）")


def _focus_chat_input(target: str, timeout: float = 20.0) -> bool:
    """点击聊天输入框确保键盘焦点；未定位到时返回 False（由调用方兜底）。"""
    output = _run_uia_script(_UIA_INPUT_BOX_SCRIPT, target, timeout)
    if not _has_output_word(output, "CLICKED"):
        return False
    return True


def _click_home_button(timeout: float = 20.0) -> bool:
    """点击左栏「聊天」按钮回聊天列表页；按钮不存在（已在聊天页）仅记日志。"""
    output = _run_uia_script(_UIA_HOME_BUTTON_SCRIPT, "", timeout)
    if not _has_output_word(output, "CLICKED"):
        _log(f"未找到左栏「聊天/微信」按钮（可能已在聊天页），继续流程：output={output[:40]}")
        return False
    return True


def _verify_wechat_session(target: str, timeout: float = 30.0, attempts: int = 3) -> bool:
    """通过系统 UIA 确认微信当前处于 target 会话。

    用独立 PowerShell 进程读微信窗口的 UIA 树（含 Qt 自绘内容）：
    - 原实现路径：聊天输入框（Edit）的可访问名 = 当前会话名；
    - 适配路径：本机微信 4.0 输入框 Name 为空，改用聊天区 Document 名
      「会话名 - 昵称」（精确等于或以「会话名 - 」开头才算命中，
      避免「张三」误判进「张三丰」会话）；搜索框 value 仍为搜索词时
      显式判未进入（搜索结果页 Document 同为「<搜索词> - ?」格式）。
    点击会话后切换有延迟，内置多次尝试。
    """
    for attempt in range(attempts):
        if attempt:
            time.sleep(0.8)
        if _has_output_word(_run_uia_script(_UIA_VERIFY_SCRIPT, target, timeout), "IN_SESSION"):
            return True
    return False


def _click_list_entry(target: str, timeout: float = 30.0) -> bool:
    """用 UIA 点击会话列表中的目标会话（列表项名以会话名开头，取第一个命中项）。

    与 AgentR 原实现一致；未命中返回 False（调用方回退到搜索路径）。
    """
    encoded = base64.b64encode(
        _UIA_CLICK_ENTRY_SCRIPT.replace("__TARGET__", target).encode("utf-16-le")
    ).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        _log(f"UIA 会话入口点击执行失败：{error}")
        return False
    clicked = any(line.strip() == "CLICKED" for line in (result.stdout or "").splitlines())
    if not clicked:
        _log(f"会话列表未命中目标入口，回退搜索路径：{(result.stdout or '').strip()[:40]}")
    return clicked


def _has_output_word(output: str, word: str) -> bool:
    """按行精确匹配判定字（不能用子串：NOT_IN_SESSION 含 IN_SESSION 字样）。"""
    return any(line.strip() == word for line in output.splitlines())


def _run_uia_script(script: str, target: str, timeout: float) -> str:
    """在独立 PowerShell 进程执行 UIA 脚本，返回其标准输出。"""
    encoded = base64.b64encode(script.replace("__TARGET__", target).encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        _log(f"UIA 脚本执行失败：{error}")
        return "SCRIPT_ERROR"
    return result.stdout or ""


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

    if not isinstance(target, str) or not target.strip():
        return {"output": {"ok": False, "error": "target 需为非空字符串（联系人备注名 / 群名）"}}
    if not isinstance(message, str) or not message.strip():
        return {"output": {"ok": False, "target": target.strip(), "error": "缺少必填参数 message（要发送的文本）"}}

    result = _send(target.strip(), message, wait_idle=wait_idle is not False)
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
    args = parser.parse_args(argv)

    target = args.target if args.target is not None else args.target_pos
    message = args.message if args.message is not None else args.message_pos
    inputs = {"target": target, "message": message, "wait_idle": not args.no_wait}
    return main({"inputs": inputs})


def _send(target: str, message: str, wait_idle: bool) -> dict:
    try:
        send_message(target, message, wait_idle=wait_idle)
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
