---
name: tabbit
description: Use for browser navigation, inspection, interaction, and visual verification through Tabbit's installed CLI.
---

# Tabbit Browser

Use the installed `tabbit-cli` launcher to run Playwright code in Tabbit tabs.
The usual flow is **connect → open → observe and act → verify → finish**.

## Connect and discover

Use the stable launcher for every command:

- POSIX: `"$HOME/.local/bin/tabbit-cli"`
- Windows PowerShell: `& "$env:LOCALAPPDATA\Tabbit\LocalAgent\bin\tabbit-cli.exe"`
- Windows CMD: `"%LOCALAPPDATA%\Tabbit\LocalAgent\bin\tabbit-cli.exe"`

Start a task on macOS:

```bash
tabbit_cli="$HOME/.local/bin/tabbit-cli"
"$tabbit_cli" create --task "Update profile"
```

Start a task on Windows PowerShell:

```powershell
$tabbitCli = "$env:LOCALAPPDATA\Tabbit\LocalAgent\bin\tabbit-cli.exe"
& $tabbitCli create --task "Update profile"
```

CLI results use stdout; diagnostics use stderr.

The launcher selects an instance and launches the browser when necessary.
Never invoke a CLI from an application bundle or versioned runtime directory,
read `endpoint.json` during browsing tasks, or start the Browser-owned Runtime
Service directly. If launcher or routing behavior breaks, follow
[launcher and routing failures](references/recovery.md#launcher-and-routing-failures),
including its scoped Windows registration and ACL repair fallback. For a user
request specifying a particular product or instance, read
[instance selection](references/recovery.md#explicit-product-or-instance-selection)
before the first command; keep the selected instance through `finish`.
Calling the browser "Tabbit" in passing, as in "my tabs in Tabbit", does not
select a product, and neither does invoking the tabbit skill or CLI; use the
launcher's selection in those cases.

Choose a short, human-readable `--task` name and reuse it throughout the task.
Standalone CLI tabs are not automatically grouped, and a task has no group of
its own. Inside a Tabbit local task, new pages open in that task's open project
group without acquiring its other tabs. Create and customize groups explicitly
with `tabbit.evaluate()` when needed; see the advanced operations reference.
Existing groups use their observed group ID with `--group`; the title is not an
ID.
Tasks expire after 90 seconds of inactivity, releasing ownership and retaining
tabs; a running evaluation is never expired. JavaScript globals are removed on
expiry; receipts and result resources stay readable, and the next task under
that name reports the retained tab IDs.

For connection problems, run `diagnose` to inspect the selected runtime and live
tasks. Add `--task` for diagnostics of an existing task:

```bash
"$HOME/.local/bin/tabbit-cli" diagnose
# Use only after the task exists; replace the name with your task's name.
"$HOME/.local/bin/tabbit-cli" diagnose --task "Update profile"
```

For routing or startup errors, follow
[launcher and routing failures](references/recovery.md#launcher-and-routing-failures).

## Open the intended page

| Starting point | Action |
| --- | --- |
| Known URL | Run `nodejs` and navigate its supplied `page`. |
| Existing user tab or retained group | Run `create --task NAME`, then acquire an observed `--tab ID` or `--group ID`. |
| Continuing this task | Reuse the task name and `page`; select another owned page with `usePage(otherPage)`. |

A missing site in the tab inventory does not establish its login state. For a
requested URL, open it in the selected browser and inspect the resulting page.

```bash
"$HOME/.local/bin/tabbit-cli" nodejs --task "Read example" --request-id open-example <<'JS'
await page.goto("https://example.com/", {waitUntil: "domcontentloaded"});
return await tabbit.observe({frames: "none", maxChars: 4000});
JS
```

`nodejs` creates the task and its initial page when needed. Reuse that page;
`context.newPage()` is for additional pages. On Windows, use the
[UTF-8 file and CMD redirection recipe](references/recovery.md#windows-multiline-invocation)
so PowerShell does not rewrite multiline JavaScript.

For an existing tab, `create` returns inventory without acquiring or opening
anything. Acquire the observed tab before operating it:

```bash
"$HOME/.local/bin/tabbit-cli" create --task "Update profile"
# Replace 17 with the tab ID returned by inventory.
"$HOME/.local/bin/tabbit-cli" nodejs --task "Update profile" --tab 17 --request-id inspect-profile <<'JS'
return await tabbit.observe({frames: "none", maxChars: 4000});
JS
```

For “this tab,” prefer inventory's `currentTabId`; otherwise match title and URL.
`available` means unowned, `owned` means this task owns it, and `claimed` means
another task owns it. Only owned tabs appear in `pages()` / `context.pages()`;
inventory tab IDs differ from runtime page labels. Check inventory truncation.
For multiple tabs, group acquisition, or acquisition failures, read
[inventory and acquisition](references/recovery.md#inventory-and-acquisition).

## Observe and act

Use a new `--request-id` for each new program. Reusing an ID returns its original
receipt without rerunning it. Programs support top-level `await` and `return`.
Lexical variables reset between calls; `globalThis` can retain task-local state.
Globals include `page`, `pages()`, `usePage`, `context`, `browser`, `tabbit`,
`expect`, `assert`, `artifactPath`, and `reportIssue`. Return bounded JSON-safe
data, not Page objects or handles. Use `expect(...).toEqual(...)` for structural
comparisons across browser realms; Node's `assert.deepEqual` checks prototypes.

Programs have a 60-second deadline by default. Set `--timeout-ms 120000` for
two minutes, as below; the maximum is `180000` (three minutes). Set it when
submitting the program; native Playwright timeouts cannot extend that deadline.

| Need | Surface |
| --- | --- |
| Unfamiliar controls | `tabbit.observe({frames: "none", maxChars: 4000})` |
| Known control | Native Playwright semantic locators and actions |
| Data extraction | Bounded `page.evaluate()` / `locator.evaluateAll()` |
| Layout or canvas | Return `await page.screenshot({fullPage: false})`; inspect the returned `result.nextAction.path` with the host image viewer |
| Browser-wide data: other tabs, bookmarks, history | Read-only `tabbit.evaluate(fn, arg)` with `chrome.*` APIs |
| Protocol-only data: metrics, emulation, CDP events | `context.newCDPSession(page)` on an owned page |

Use observed labels or fresh refs, and inspect changed state before choosing new
targets. Check snapshot truncation; resource paging cannot recover omitted text.
Batch known actions and their verification in one program. Wait for relevant
application state with locators, `expect`, or `waitForFunction`, not fixed sleeps.
Install popup, dialog, and file-chooser waiters before the triggering action.
Run known independent reads concurrently with bounded concurrency; keep mutations
to the same business object sequential.

For example, after observing Display name and Save, and when saving is authorized:

```bash
"$HOME/.local/bin/tabbit-cli" nodejs --task "Update profile" --request-id save-profile --timeout-ms 120000 <<'JS'
const name = page.getByRole("textbox", {name: "Display name", exact: true});
await name.fill("Alex");
await page.getByRole("button", {name: "Save", exact: true}).click();
await expect(page.getByRole("status")).toHaveText("Saved");
return {saved: true};
JS
```

Adapt verification to the application. For a requested draft, retain it without
submitting. Login, CAPTCHA, payment, and sensitive values need user action or an
authorized protected flow. For an observed login wall needing user action,
record `reportIssue("AUTHENTICATION_REQUIRED")`, return the URL, and finish while
retaining the page. Also reportable: `SITE_ACCESS_BLOCKED`, `BROWSER_ERROR_PAGE`.

Do not rely on Back/Forward to preserve unsaved state: owned tabs disable BFCache.
Keep a page open when its state matters. `usePage` changes the task's current page
without bringing the browser to the foreground.

Read the relevant reference only when needed:

- [Frames, popups, dialogs, uploads, paste, and rerenders](references/advanced-operations.md).
- [Files and browser-network requests](references/advanced-operations.md#browser-network-requests):
  use `page.fetch` for observed HTTP(S) URLs with browser cookies/CORS/CSP.
  Native `page.request` / `context.request` use Node HTTP. Playwright download
  events are unavailable in this connection.
- [Screenshots and visual input](references/advanced-operations.md#screenshots-and-visual-input):
  page screenshots return artifact receipts; locator screenshots return native
  Buffers. Open a page screenshot from its returned path.
- [Pagination](references/advanced-operations.md#extract-complete-evidence) and
  [parallel extraction](references/advanced-operations.md#collect-independent-sources-concurrently):
  verify coverage before reporting complete lists or counts.
- [Rate limits and interaction diagnostics](references/advanced-operations.md#rate-limits-and-interaction-diagnostics):
  respect `SITE_RATE_LIMITED` and any supplied retry time.
- [Browser data through tabbit.evaluate](references/advanced-operations.md#browser-data-through-tabbitevaluate):
  `fn` is plain JavaScript whose only browser global is allowlisted `chrome`;
  pass inputs as `arg`, since it cannot see program variables.
- [Page-scoped CDP sessions](references/advanced-operations.md#page-scoped-cdp-sessions):
  raw CDP for owned pages only; `Browser.*` and `Target.*` are rejected; detach
  when finished.

Receipts may include site `playbooks` catalogs with `manifestPath`, domains, and
files. Read the relevant manifest and listed notes/tools from the packaged
`playbooks/` directory. Resolve paths beside the manifest; run Playwright helpers
through `nodejs` and DOM helpers inside `page.evaluate`.

## Verify the result and resolve pending work

Read successful `nodejs` output from `result.value`; the save example can return
this response excerpt:

```json
{"status":"succeeded","result":{"requestId":"save-profile","value":{"saved":true}}}
```

Use this result directly; another receipt read is unnecessary after success.
If it returns a `result.resourceId`, read that resource before finishing; use
`<launcher> resource --task NAME --resource ID --offset 0 --max-bytes 32768`,
then follow each returned `nextOffset` until `eof`. See
[resource results](references/recovery.md#read-resource-results).

For `queued` or `running`, read the original pending request's receipt with the
same task name and request ID. For the save example:

```bash
"$HOME/.local/bin/tabbit-cli" receipt --task "Update profile" --request-id save-profile
# If still queued or running, wait up to 60 seconds for it to settle.
"$HOME/.local/bin/tabbit-cli" receipt --task "Update profile" --request-id save-profile --wait-ms 60000
```

Without `--wait-ms`, `receipt` reads the current status immediately. Repeat the
wait if still pending; it does not rerun code or extend the program deadline.
A successful receipt has a different result shape from `nodejs`, for example:

```json
{"requestId":"save-profile","status":"succeeded","result":{"type":"inline","value":{"saved":true}}}
```

Read `result.value` for `type: "inline"`, or fetch `result.resourceId` for
`type: "resource"`. For `failed` or `interrupted`, inspect the receipt's error.

A dispatched or failed program may already have changed the page. Inspect the
persisted state before repeating a mutation. For transport loss, missing receipts,
`taskTerminated`, or uncertain acquisition, read [recovery](references/recovery.md)
before continuing; never change tasks or request IDs to bypass pending work.
Exit codes are 0 for success, 70 for failed/interrupted, and 75 for queued/running;
pre-submission failures may instead return `{ok: false, error}` without a receipt.

On `TAB_DETACHED`, or when `closedPages` lists a page whose tab still appears in
inventory, re-acquire that tab with `--tab ID`; do not open a replacement tab.
Verify persisted results by reloading the same page. Never open the same editor
URL in two tabs. Idle tasks expire; the next command reports `task.expired`.

## Finish

After verifying the result and reading needed resources, close only unneeded
task-created scratch and duplicate pages with `page.close()`, then finish using the same name:

```bash
"$HOME/.local/bin/tabbit-cli" finish --task "Read example"
```

Plain `finish` releases ownership and retains remaining tabs and explicit groups.
Reacquire retained tabs with `nodejs --tab ID`, or an explicit group with
`nodejs --group ID`.
Preserve acquired user tabs, requested output pages, drafts, and login pages.
Finishing removes receipts and resource files; exported artifacts remain.
Use `--discard` only when closing **all task-owned tabs** was requested, since it
also closes acquired user tabs. Choose one finish mode and await its result.
If `forcedCleanup` is true or finish is interrupted, follow
[finish recovery](references/recovery.md#finish-recovery) before claiming cleanup
or retrying. Restore any explicitly pinned instance override only after finish
is confirmed.
