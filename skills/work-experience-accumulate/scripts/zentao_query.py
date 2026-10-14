#!/usr/bin/env python3
"""Read-only ZenTao REST v1 resolved-Bug adapter (standard library only)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request


class QueryError(RuntimeError):
    """Only static, safe messages may cross the adapter boundary."""


def positive_id(value):
    if type(value) not in (int, str) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise QueryError("禅道记录 ID 无效")
    return str(value)


def timestamp(value):
    if not isinstance(value, str):
        raise QueryError("禅道解决时间缺失或无效")
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QueryError("禅道解决时间缺失或无效") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise QueryError("禅道时间没有时区；不能推断服务器时区")
    return stamp.astimezone(dt.timezone.utc)


def credentials(workdir):
    """Environment overrides routes, then .env fallback; never write secrets."""
    keys = ("ZENTAO_BASE_URL", "ZENTAO_ACCOUNT", "ZENTAO_PASSWORD")
    values = {}
    try:
        path = Path(workdir) / ".agents/zentao-bugfix/routes.json"
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            cfg = document.get("config", {})
            if not isinstance(cfg, dict):
                raise ValueError()
            values.update({k: cfg[k] for k in keys if k in cfg})
        env_path = Path(workdir) / ".agents/.env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.removeprefix("export ").partition("=")
                key = key.strip()
                if sep and key in keys and not values.get(key):
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    values[key] = value
    except (OSError, ValueError, AttributeError, TypeError):
        raise QueryError("现有禅道认证配置无法读取") from None
    for key in keys:
        if os.environ.get(key):
            values[key] = os.environ[key]
    if any(not isinstance(values.get(k), str) or not values[k].strip() for k in keys):
        raise QueryError("现有禅道认证配置不完整")
    return tuple(values[k] for k in keys)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise QueryError("禅道接口发生跳转；拒绝转发认证信息")


class Client:
    def __init__(self, base, account, password):
        parsed = urllib.parse.urlsplit(base.strip())
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise QueryError("禅道地址格式无效")
        self.base = base.strip().rstrip("/")
        self.account, self.password = account, password
        self.token = None
        self.opener = urllib.request.build_opener(NoRedirect())
        self.requests = 0
        self.deadline = time.monotonic() + 480

    def request(self, endpoint, params=None, login=False):
        if self.requests >= 2000 or time.monotonic() >= self.deadline:
            raise QueryError("禅道查询达到请求或时间上限；结果不完整")
        self.requests += 1
        url = self.base + "/api.php/v1" + endpoint
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = None
        headers = {"Accept": "application/json"}
        if login:
            if endpoint != "/tokens":
                raise QueryError("禁止非认证写入请求")
            body = json.dumps({"account": self.account, "password": self.password,
                               "addAction": False}).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            if not self.token:
                raise QueryError("禅道尚未认证")
            headers["Token"] = self.token
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST" if login else "GET")
        try:
            with self.opener.open(req, timeout=20) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise QueryError("禅道响应超过安全大小限制")
            result = json.loads(raw.decode("utf-8-sig"))
        except urllib.error.HTTPError as exc:
            raise QueryError(f"禅道接口 HTTP {exc.code}；查询失败") from None
        except (OSError, urllib.error.URLError):
            raise QueryError("禅道网络请求失败") from None
        except (UnicodeError, ValueError):
            raise QueryError("禅道响应不是有效 JSON") from None
        if not isinstance(result, dict) or result.get("status") in ("fail", "error") or "error" in result:
            raise QueryError("禅道接口拒绝查询或响应结构无效")
        return result

    def login(self):
        result = self.request("/tokens", login=True)
        token = result.get("token")
        if not isinstance(token, str) or not token:
            raise QueryError("禅道认证失败；未返回有效令牌")
        self.token = token

    def pages(self, endpoint, field, params=None):
        """No early date cutoff: ID order does not imply resolvedDate order."""
        total = None
        seen = set()
        page = 1
        offset = 0
        limit = 100
        while True:
            data = self.request(endpoint, {**(params or {}), "page": page, "limit": limit})
            rows = data.get(field)
            pager = [data.get(k) for k in ("page", "total", "limit")]
            if (not isinstance(rows, list) or any(type(v) is not int for v in pager)
                    or pager[0] != page or pager[1] < 0 or not 1 <= pager[2] <= 100):
                raise QueryError("禅道分页结构无效；结果不完整")
            if total is None:
                total = pager[1]
                limit = pager[2]
            if pager[1] != total or pager[2] != limit:
                raise QueryError("禅道分页总数或页大小变化；请重试")
            if len(rows) != min(limit, total - offset):
                raise QueryError("禅道分页记录数量不匹配；结果不完整")
            for row in rows:
                if not isinstance(row, dict):
                    raise QueryError("禅道列表记录结构无效")
                record_id = positive_id(row.get("id"))
                if record_id in seen:
                    raise QueryError("禅道分页出现重复 ID；结果不完整")
                seen.add(record_id)
                yield row
            offset += len(rows)
            if offset == total:
                return
            page += 1


def user_account(value):
    if isinstance(value, dict):
        value = value.get("account")
    if not isinstance(value, str) or not value:
        raise QueryError("禅道解决人账号缺失；不能用姓名推断")
    return value


def selected(bug, user_id, start, end):
    status = bug.get("status")
    if status not in ("active", "resolved", "closed"):
        raise QueryError("禅道 Bug 状态缺失或未知")
    if status != "resolved":
        return False
    if user_account(bug.get("resolvedBy")) != user_id:
        return False
    stamp = timestamp(bug.get("resolvedDate"))
    if not start <= stamp < end:
        return False
    deleted = bug.get("deleted")
    if type(deleted) not in (bool, int, str) or deleted not in (False, 0, "0", True, 1, "1"):
        raise QueryError("禅道 Bug 删除标记缺失或未知")
    return deleted in (False, 0, "0")


def safe_text(value, secrets):
    if not isinstance(value, str):
        return ""
    text = value
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[已脱敏]")
    if any(word in text.lower() for word in ("password", "passwd", "secret", "token", "authorization", "cookie")):
        return "[已脱敏的敏感字段]"
    return text[:500]


def query(client, user_id, start, end):
    start_dt, end_dt = timestamp(start), timestamp(end)
    if start_dt >= end_dt or not isinstance(user_id, str) or not user_id.strip():
        raise QueryError("查询账号或时间窗口无效")
    if client.account != user_id:
        raise QueryError("查询账号与认证账号不一致；停止采集")
    client.login()
    products = list(client.pages("/products", "products", {"status": "all", "order": "id_asc"}))
    candidates = {}
    scanned = 0
    for product in products:
        product_id = positive_id(product["id"])
        for bug in client.pages(f"/products/{product_id}/bugs", "bugs",
                                {"status": "resolvedbyme", "branch": "all", "order": "id_asc"}):
            scanned += 1
            if positive_id(bug.get("product")) != product_id:
                raise QueryError("禅道列表返回其他产品记录；结果不完整")
            if selected(bug, user_id, start_dt, end_dt):
                bug_id = positive_id(bug["id"])
                if bug_id in candidates:
                    raise QueryError("禅道跨产品出现重复 Bug ID；结果不完整")
                candidates[bug_id] = product_id
    records = []
    changed = 0
    for bug_id, product_id in candidates.items():
        bug = client.request(f"/bugs/{bug_id}")
        if positive_id(bug.get("id")) != bug_id:
            raise QueryError("禅道详情 ID 不匹配")
        if not selected(bug, user_id, start_dt, end_dt):
            changed += 1
            continue
        if positive_id(bug.get("product")) != product_id:
            raise QueryError("禅道 Bug 产品在查询期间变化；请重试")
        records.append({
            "id": bug_id, "product": product_id, "status": "resolved",
            "resolvedBy": user_id,
            "resolvedDate": timestamp(bug["resolvedDate"]).isoformat(),
            "title": safe_text(bug.get("title"), (client.password, client.token)),
            "resolution": safe_text(bug.get("resolution"), (client.password, client.token)),
            "url": client.base + f"/bug-view-{bug_id}.html",
        })
    return {"window": {"start": start, "end": end}, "user_id": user_id,
            "scope": "all_accessible_products", "time_basis": "resolvedDate",
            "complete": True, "products_scanned": len(products),
            "bugs_scanned": scanned, "changed_candidates_skipped": changed,
            "requests": client.requests, "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--resolved-by", required=True)
    args = parser.parse_args()
    try:
        base, account, password = credentials(args.workdir.expanduser().resolve())
        data = query(Client(base, account, password), args.resolved_by, args.start, args.end)
        print(json.dumps({"status": "ok", "data": data}, ensure_ascii=False))
        return 0
    except QueryError as exc:
        message = str(exc)
    except Exception:
        message = "禅道适配器发生内部错误；未交付不完整结果"
    print(json.dumps({"status": "error", "error": {"code": "3", "message": message}}, ensure_ascii=False))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
