# Advanced browser operations

Read the matching section only. Run examples through `nodejs` on the intended
owned page, with the same task name and a new request ID. Replace illustrative
selectors, paths, and outputs with observed evidence.

## Frames and observation

`tabbit.observe(options)` discovers controls and frames on `page`.

| Option | Default | Allowed values |
| --- | --- | --- |
| `frames` | `"visible"` | `"none"`, `"visible"`, `"all"` |
| `depth` | 20 | 1–30 |
| `maxChars` | 6000 | 256–20000 |
| `frameMaxChars` | `min(2000, maxChars)` | 256–6000 |
| `maxFrames` | 8 | 1–32, including the main frame |
| `boxes`, `focus` | `true` | `false` omits boxes or focus details |
| `hitTest` | absent | Locator or `{x, y}` |

Discover frames, then act inside an observed `iframe[title="Profile"]`:

```js
return await tabbit.observe({frames: "all", maxFrames: 16, frameMaxChars: 3000});
```

```js
const profile = page.frameLocator('iframe[title="Profile"]');
await profile.getByLabel("Display name", {exact: true}).fill("Alex");
await profile.getByRole("button", {name: "Save", exact: true}).click();
await expect(profile.getByRole("status")).toHaveText("Saved");
return {status: await profile.getByRole("status").textContent()};
```

Check `framesTruncated` and each `snapshotTruncated`. Increase the
relevant limit or inspect a specific frame; resource paging cannot recover text
already truncated by `observe`. Characters bound snapshots, not total response
bytes. Frame IDs are observational labels; select through observed markup,
`page.frame({name})`, or a unique frame URL. Re-resolve detached frames.

## Popups

Install the waiter before clicking; select the popup with `usePage`.

An observed “Open details” link opens a Details page:

```js
const popup = await tabbit.triggerAndWait("popup", () =>
  page.getByRole("link", {name: "Open details", exact: true}).click());
await popup.waitForLoadState("domcontentloaded");
await expect(popup.getByRole("heading", {name: "Details", exact: true})).toBeVisible();
usePage(popup);
return {url: page.url(), title: await page.title()};
```

Expect `{url, title}` in `result.value`; the next call uses the
popup. Return data, not Page objects. Close scratch popups when finished.

## Dialogs

Handle a dialog while its triggering action is pending. The runtime
records `BLOCKING_DIALOG` but does not accept or dismiss it.

The user authorized Apply changes and its known confirmation:

```js
const stop = new AbortController();
const handled = page.waitForEvent("dialog", {
  timeout: 10000, signal: stop.signal,
}).then(async dialog => {
  const expected = dialog.type() === "confirm" && dialog.message() === "Apply changes?";
  if (expected) await dialog.accept();
  else await dialog.dismiss();
  assert(expected, "Unexpected dialog dismissed");
});
try {
  await Promise.all([
    handled,
    page.getByRole("button", {name: "Apply changes", exact: true}).click(),
  ]);
  await expect(page.getByRole("status")).toHaveText("Saved");
  return {saved: true};
} finally {
  stop.abort();
}
```

Handle prompts with `accept(authorizedText)`; dismiss cancellation.
Do not await `triggerAndWait("dialog", click)` before handling the dialog: the
click may wait for dismissal. Unexpected dialogs require inspection before retry.

## Uploads

Use native file inputs; selecting a file may immediately upload it.

The user requested uploading `/absolute/report.pdf` to this site:

```js
await page.getByLabel("Attachment", {exact: true}).setInputFiles("/absolute/report.pdf");
await expect(page.getByRole("status")).toHaveText("Uploaded report.pdf");
return {uploaded: "report.pdf"};
```

For an observed control that creates a file chooser:

```js
const stop = new AbortController();
try {
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser", {timeout: 10000, signal: stop.signal}),
    page.getByRole("button", {name: "Attach file", exact: true}).click(),
  ]);
  await chooser.setFiles("/absolute/report.pdf");
  await expect(page.getByRole("status")).toHaveText("Uploaded report.pdf");
  return {uploaded: "report.pdf"};
} finally {
  stop.abort();
}
```

Use an existing authorized absolute file path readable by the
runtime. Adapt the application's upload/save confirmation; file selection alone
does not prove persistence. After failure, inspect attachments before retrying.

## Paste

Use `pasteText` for bulk editor/grid text; ordinary typing uses
`fill`, or `pressSequentially` when individual key events matter.

Replace Items with the requested TSV:

```js
const box = page.getByRole("textbox", {name: "Items", exact: true});
const text = "alpha\tbeta\ngamma\tdelta";
await box.fill("");
await box.focus();
const paste = await tabbit.pasteText(text, {
  format: "tsv", requireEditableFocus: true,
});
await expect(box).toHaveValue(text);
return {strategy: paste.strategy, value: await box.inputValue()};
```

Verify values or grid cells; dispatch does not prove acceptance
or persistence. Nonempty text is limited to 1 MiB. Defaults: `format: "text"`,
`requireEditableFocus: false`. Paste is task-local and synthetic (`trusted: false`);
the system clipboard is unchanged.

## Snapshot references across a rerender

Prefer semantic locators. Normalize a fresh snapshot ref before
a known DOM replacement.

Observed Save ref `e3` must survive the checkbox's action-bar rerender;
the user requested enabling updates and saving:

```js
const save = await page.locator("aria-ref=e3").normalize();
await page.getByRole("checkbox", {name: "Email me updates", exact: true}).check();
await save.click();
await expect(page.getByRole("status")).toHaveText("Saved");
return {status: await page.getByRole("status").textContent()};
```

Normalized locators re-resolve test IDs, roles, and user-facing attributes, not
permanent identity. Re-observe after navigation or changed attributes; never
invent refs. Store the locator on `globalThis` if it must survive another call.

## An action whose transition is unknown

`triggerAndObserve` detects page, URL, navigation, frame, or render
changes in that priority order.

Continue shows Confirmation preview on this or a new page:

```js
const transition = await tabbit.triggerAndObserve(() =>
  page.getByRole("button", {name: "Continue", exact: true}).click(),
  {timeoutMs: 10000, activatePage: true});
await expect(page.getByRole("heading", {name: "Confirmation preview", exact: true})).toBeVisible();
return {transition};
```

Transition shape: `{kind, url, pageId?, activated?, frame?}`.
`activatePage` selects a new page but does not wait for content; use native waits.
For unknown destinations, inspect the transition first. Locate child frames by
returned name/URL before acting.

Defaults: `timeoutMs: 30000`, `activatePage: false`, `settleMs: 120` (0–2000),
`pollMs: 25` (10–500). Signals accumulate through `settleMs`.
For known page/popup/navigation/URL events use `triggerAndWait`; all accept
`timeoutMs`. URL requires `url`; navigation/URL also accept `waitUntil`.

## Browser-network requests

`page.fetch` uses browser CORS, CSP, and cookies.

Read an endpoint observed in this application's workflow:

```js
const response = await page.fetch("/api/orders?limit=20", {as: "json"});
assert(response.ok, `HTTP ${response.status}`);
return response.json;
```

Results contain HTTP metadata and `text`, `json`, or `path`, not
`APIResponse`. HTTP errors return `ok: false`; network, parsing, timeout, and
size failures reject. Defaults: `method: "GET"`, `timeoutMs: 20000` including body.

Relative URLs resolve against `document.baseURI`; only HTTP(S) is supported.
Credentials default to `"same-origin"`; `"omit"`/`"include"` are also accepted.
Options are `{method, headers, body, as, savePath, maxBytes, timeoutMs, credentials}`;
`body` must be a string and `as` is `"text"`, `"json"`, or `"file"`.
Without `as`, textual responses up to 256 KiB return inline text; other responses
require `savePath`. `as: "file"` forces file output; `maxBytes` can lower the
8 MiB limit. `artifactPath(name)` requires a plain filename ≤128 characters;
same name means same path, and fetch never overwrites files.

Native `page.request` / `context.request` use Node HTTP. Browser downloads need
an exposed HTTP(S) URL: this connection delivers no Playwright download events.
Do not wait for `download`/`downloadsDelta`. Without a URL, verify through an
authorized native download UI or hand off to the user.

## Rate limits and interaction diagnostics

`result.issuesDelta` reports `SITE_RATE_LIMITED` for every owned-page HTTP 429,
with or without `Retry-After`. HTTP 503 requires a valid `Retry-After`. This
includes fetch/XHR/subresources and excludes native
`page.request`/`context.request`. Reporting does not wait or retry. Defer the
reported `origin` until Unix-millisecond `timestamp + details.retryAfterMs`;
null means no usable delay. `details.status` contains the HTTP status.

For a fetch/XHR network failure, `result.issuesDelta` reports `REQUEST_FAILED`
with `details.method`, `details.path`, and `details.networkError`. The path
excludes query parameters. A failure that arrives after a program returns
appears once in the next receipt. For a failed write, inspect the resulting
state before retrying: the request may have reached the server.

Inspect a failed Save action, then act on its reported blockers:

```js
return await tabbit.actionability(page.getByRole("button", {name: "Save", exact: true}));
```

`tabbit.focusInfo()` reports focus; `tabbit.hitTest(locatorOrPoint)`
reports the hit target. Use diagnostics to choose native actions, not replace them.
Record observed login walls before handoff:

```js
reportIssue("AUTHENTICATION_REQUIRED");
return {blocked: "login required", url: page.url()};
```

Also reportable: `SITE_ACCESS_BLOCKED`, `BROWSER_ERROR_PAGE`. Report only observed
conditions; an authorized protected flow can continue within its scope.

## Screenshots and visual input


`page.screenshot()` produces PNG artifact receipts only; JPEG is unsupported.
Locator screenshots keep Playwright’s native Buffer return value.

```js
return await page.screenshot({fullPage: false});
```

Open the exact `result.nextAction.path` with the host image viewer before making
a visual judgment or choosing coordinates. The receipt is not a Playwright
Buffer. Coordinates use CSS pixels; account for device scale or viewer resizing
when reading image pixels. For a canvas lacking useful DOM controls, after
inspection establishes the target position:

```js
await page.mouse.click(420, 260);
await page.keyboard.insertText("Quarterly plan");
return await page.screenshot({fullPage: false});
```

Open the resulting screenshot and verify the edit. Prefer semantic locators when
available. See [uploads](#uploads), [refs across rerenders](#snapshot-references-across-a-rerender),
and [ambiguous transitions](#an-action-whose-transition-is-unknown).

## Page-scoped CDP sessions

Use a raw CDP session only for a capability Playwright does not expose, such as
performance counters, emulation, or protocol events. Prefer native Playwright
APIs otherwise.

`context.newCDPSession(page)` works for **owned pages only** and opens a separate
attachment scoped to that page: enabling a domain there does not affect the
task's Playwright session. `Browser.*` and `Target.*` commands are rejected in
it, and `Page.bringToFront` follows the task's foreground policy. The session
ends when its page closes; detach it when finished.

Read counters that Playwright does not report:

```js
const cdp = await context.newCDPSession(page);
try {
  await cdp.send("Performance.enable");
  const {metrics} = await cdp.send("Performance.getMetrics");
  const wanted = new Set(["JSHeapUsedSize", "Nodes", "LayoutCount", "TaskDuration"]);
  return Object.fromEntries(metrics.filter((metric) => wanted.has(metric.name))
    .map((metric) => [metric.name, metric.value]));
} finally {
  await cdp.detach();
}
```

Collect protocol events around one action. Register the listener before the
trigger and bound what you keep:

```js
const cdp = await context.newCDPSession(page);
const failures = [];
cdp.on("Network.loadingFailed", (event) => {
  if (failures.length < 20) {
    failures.push({type: event.type, error: event.errorText, blocked: event.blockedReason});
  }
});
try {
  await cdp.send("Network.enable");
  await page.getByRole("button", {name: "Load more", exact: true}).click();
  await page.waitForLoadState("networkidle");
  return {failures};
} finally {
  await cdp.detach();
}
```

Emulation changes the page for later programs too; always restore it:

```js
const cdp = await context.newCDPSession(page);
try {
  await cdp.send("Emulation.setCPUThrottlingRate", {rate: 4});
  const started = Date.now();
  await page.reload({waitUntil: "load"});
  return {throttledLoadMs: Date.now() - started};
} finally {
  await cdp.send("Emulation.setCPUThrottlingRate", {rate: 1});
  await cdp.detach();
}
```

A rejected command fails with `Command rejected by TabbitDance` or
`Browser and Target commands are unavailable in raw CDP sessions`. Use the
task's Playwright objects (`context`, `page`, `usePage`) for tab and page
management instead.

## Browser data through tabbit.evaluate

`tabbit.evaluate(fn, arg)` reads browser-wide data (tabs and windows outside the
task, bookmarks, history, synced sessions, and system information) through a
allowlisted subset of Chrome extension APIs. Reads are browser-wide; explicit
group mutations require task-owned tabs. It works like `page.evaluate`:

- `fn` is ordinary JavaScript. Its globals are ECMAScript built-ins, `URL`,
  `URLSearchParams`, and `chrome`; Node globals, `page`, `tabbit`, timers, and
  `fetch` are absent.
- `fn` cannot use variables from the surrounding program. Pass inputs as `arg`
  and return JSON-safe data; both are structured-cloned.
- `chrome.*` methods return promises. A trailing callback also works, with
  `chrome.runtime.lastError` set during it on failure; `chrome.*.on*` events
  are unsupported. A method outside the subset is `undefined`.
- Incognito tabs, windows, and history are never visible.

| Namespace | Methods |
| --- | --- |
| `chrome.tabs` | `query`, `get`, `getZoom`, `getZoomSettings`, `detectLanguage`, `group`, `ungroup` |
| `chrome.windows` | `getAll`, `get`, `getLastFocused` |
| `chrome.tabGroups` | `query`, `get`, `update` |
| `chrome.bookmarks` | `getTree`, `getSubTree`, `getChildren`, `get`, `getRecent`, `search` |
| `chrome.history` | `search`, `getVisits` |
| `chrome.sessions` | `getRecentlyClosed`, `getDevices` |
| `chrome.readingList` | `query` |
| `chrome.topSites` | `get` |
| `chrome.webNavigation` | `getFrame`, `getAllFrames` |
| `chrome.idle` | `queryState` |
| `chrome.system.cpu`, `.memory`, `.display` | `getInfo` |

To mutate a tab found this way, acquire it with `--tab ID`; `chrome.tabs` IDs
are the inventory tab IDs. `tabs.group` and `tabs.ungroup` require ownership of
every listed tab. Joining or updating an existing group requires ownership of
every tab in that group. Grouping never acquires or releases ownership.

A task has no group of its own. It may leave its tabs ungrouped or create
several groups; group only when the user asks or related tabs benefit from it.
Pages from `context.newPage()` normally open at the end of the window, outside
any group. When the CLI runs inside a Tabbit local task, new pages instead open
at the end of that task's project group while the group is open, in whichever
window holds it. A closed project group is never reopened; pages then open
ungrouped. This placement does not grant ownership of the group's other tabs or
permission to mutate that group.

Get owned tab IDs and their `windowId` from `tabs --task NAME --state owned`;
inventory window IDs are `chrome.windows` IDs. Extension API group IDs are
integers, unlike the opaque IDs used by CLI `--group`. Supply the intended
window ID when creating a group so it does not default to the foreground
window. For observed owned tab IDs 17 and 18 in window 1:

```js
return await tabbit.evaluate(async ({tabIds, windowId}) => {
  const id = await chrome.tabs.group({tabIds, createProperties: {windowId}});
  return await chrome.tabGroups.update(id, {title: "Research", color: "blue"});
}, {tabIds: [17, 18], windowId: 1});
```

To add owned tab 19 to the group containing owned tab 17, reuse that tab's
`groupId`:

```js
return await tabbit.evaluate(async ({tabId, memberTabId}) => {
  const {groupId} = await chrome.tabs.get(memberTabId);
  return await chrome.tabs.group({tabIds: [tabId], groupId});
}, {tabId: 19, memberTabId: 17});
```

To ungroup those owned tabs while retaining task ownership:

```js
await tabbit.evaluate(async (tabIds) => {
  await chrome.tabs.ungroup(tabIds);
}, [17, 18]);
return {ungrouped: true};
```

List the user's tabs in the focused window, including tabs this task does not own:

```js
return await tabbit.evaluate(async () => {
  const tabs = await chrome.tabs.query({lastFocusedWindow: true});
  return tabs.map(({id, title, url, active, groupId}) => ({id, title, url, active, groupId}));
});
```

Summarize recent history with an input and ordinary JavaScript:

```js
return await tabbit.evaluate(async ({days, top}) => {
  const items = await chrome.history.search({
    text: "", startTime: Date.now() - days * 86_400_000, maxResults: 1000,
  });
  const visits = new Map();
  for (const item of items) {
    const host = new URL(item.url).host;
    visits.set(host, (visits.get(host) ?? 0) + (item.visitCount ?? 0));
  }
  return [...visits].sort((a, b) => b[1] - a[1]).slice(0, top)
    .map(([host, count]) => ({host, count}));
}, {days: 7, top: 10});
```

Find bookmarks and recently closed tabs:

```js
return await tabbit.evaluate(async ({query}) => {
  const bookmarks = (await chrome.bookmarks.search(query))
    .filter((node) => node.url).slice(0, 20)
    .map(({id, title, url}) => ({id, title, url}));
  const closed = (await chrome.sessions.getRecentlyClosed({maxResults: 10}))
    .flatMap((entry) => entry.tab ? [entry.tab] : entry.window?.tabs ?? [])
    .map(({title, url}) => ({title, url}));
  return {bookmarks, closed};
}, {query: "quarterly report"});
```

Check machine state before heavy work:

```js
return await tabbit.evaluate(async () => {
  const [cpu, memory, idle] = await Promise.all([
    chrome.system.cpu.getInfo(), chrome.system.memory.getInfo(),
    chrome.idle.queryState(60),
  ]);
  return {processors: cpu.numOfProcessors,
    availableMemoryGb: +(memory.availableCapacity / 2 ** 30).toFixed(1), idle};
});
```

Failures reject with a code: `EXTENSION_API_NOT_ALLOWED` for a method outside
the subset, `INVALID_ARGUMENT` for arguments the API cannot parse or that
exceed its limits (for example, `chrome.sessions` `maxResults` above 25), and
`EXTENSION_API_ERROR` with the API's own message (for example, an unknown tab
ID). Check `typeof chrome.tabs.remove === "undefined"` rather than probing.

## Extract complete evidence


For lists, counts, extrema, or rankings, define the candidate set and inclusion
rule. A bounded sample is not a complete answer. The following workflow collects
all issues under the current Open filter, deduplicating by absolute issue URL.

### Collect a paginated list across calls

Inspection established a server-rendered “Open issues” page, issue links matching
`main a.issue-link[href]`, and at most one `a[rel="next"]` link, absent only on the
last page. These are this site's completion signals; do not assume them elsewhere.
Navigate to the first page and initialize once in the current task:

```js
await expect(page.getByRole("heading", {name: "Open issues", exact: true})).toBeVisible();
globalThis.issueScan = {items: new Map(), visited: new Set(), nextUrl: page.url()};
return {startUrl: globalThis.issueScan.nextUrl};
```

Run this program under a new request ID. It processes at most two pages per call;
`globalThis.issueScan` preserves the accumulated items and continuation:

```js
const scan = globalThis.issueScan;
assert(scan, "Initialize the scan on the first page");
for (let i = 0; scan.nextUrl && i < 2; i++) {
  const url = scan.nextUrl;
  assert(!scan.visited.has(url), "Pagination returned to a visited page");
  await page.goto(url, {waitUntil: "domcontentloaded"});
  await expect(page.getByRole("heading", {name: "Open issues", exact: true})).toBeVisible();
  const rows = await page.locator("main a.issue-link[href]").evaluateAll(links =>
    links.map(a => ({title: (a.textContent || "").trim(), url: a.href})));
  const nextUrl = await page.locator('a[rel="next"]').evaluateAll(links => {
    if (links.length > 1) throw new Error("Ambiguous next page");
    return links[0]?.href ?? null;
  });
  for (const row of rows) scan.items.set(row.url, row);
  scan.visited.add(url);
  scan.nextUrl = nextUrl;
}
return {items: [...scan.items.values()], unique: scan.items.size,
  pagesRead: scan.visited.size, complete: scan.nextUrl === null, nextUrl: scan.nextUrl};
```

A partial result might report `pagesRead: 2`, `unique: 35`, `complete: false`, and
a `nextUrl` for page 3. Run the same batch under a **new request ID**, without
reinitializing the scan. When `complete: true`, `items` contains the deduplicated
collection; read resource chunks if the result is large, then finish the task.

Report “35 unique open issues across 3 pages” only if those are the final verified
counts. If stopped early or a page fails, report partial coverage and the last
confirmed page count. A visited URL cycle is an error, not a completion signal.
For client-rendered lists, wait for each page's data-ready signal before reading
rows or treating an absent Next link as the end. For infinite scroll, use the
application's observed end marker or total count instead of assuming that one
unchanged scroll means completion.

### Collect independent sources concurrently

For independent sources, keep concurrency small and return failures
alongside results. This example closes each scratch tab in `finally`:

```js
const urls = ["https://example.com/", "https://example.org/"];
const settled = await Promise.allSettled(urls.map(async (url) => {
  const tab = await context.newPage();
  try {
    await tab.goto(url, {waitUntil: "domcontentloaded"});
    return await tab.locator("main").evaluate((main) => ({
      title: document.title,
      url: location.href,
      text: (main.innerText || "").slice(0, 4000),
    }));
  } finally {
    await tab.close();
  }
}));
return settled.map((item, index) => item.status === "fulfilled"
  ? item.value : {url: urls[index], error: String(item.reason)});
```
