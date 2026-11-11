# Recovery

Use this reference after pending or interrupted work, an uncertain mutation,
transport loss, a missing receipt, or finish failure, and for explicit instance
selection or launcher and routing failures. Read the relevant section only.
Keep the same task name and request identity until evidence establishes the
outcome. Use the [connection and permissions](../SKILL.md#connect-and-discover).

## Read, do not resubmit

```text
<launcher> receipt --task NAME --request-id ID --wait-ms 60000
<launcher> diagnose --task NAME
```

Every CLI program uses `mutationState: "possible"`: earlier actions may have
completed even when the program fails. For `queued` or `running`,
wait on the same receipt; a client-side wait ending does not establish failure.
For failed or interrupted work, inspect persisted application state before
retrying. Submit corrected code under a new request ID only when evidence rules
out repeating a completed mutation. Reusing an ID only returns its old receipt.
Never change task names, instances, or browser backends to evade pending work.

## Deadline and transport boundaries

When a hard deadline reports `taskTerminated: true`, only that task executor is
terminated; its live tabs and any explicit groups are retained. In a new
read-only task, reacquire the receipt's `retainedTabIds` with `--tab` or an
explicit group with `--group`, inspect externally visible state, and retry a mutation only
when evidence proves the original operation did not occur.

After a transport close in the same Browser generation, reconnect through the
stable launcher and read the original receipt. The CLI does not replay a fully
sent request on EOF. If the task or receipt is missing, or the response is
`OUTCOME_UNKNOWN`, the receipt cannot establish the mutation outcome. Create a
new read-only task, inspect externally visible state, and never replay the
possible mutation merely because the old receipt is unavailable.

A separate read-only view does not prove an earlier queued request has stopped.
Before retrying a mutation or finishing, establish that the original execution
has settled. If its outcome remains unknown, report that uncertainty and retain
the task's recovery evidence rather than resubmitting or deleting its receipts.

## Read resource results

Read needed resources before `finish`: task cleanup removes receipts and resource
files, while exported artifacts remain. A successful compact response carries
`result.resourceId` and `result.byteLength`. Use the returned ID:

```text
<launcher> resource --task NAME --resource ID --offset 0 --max-bytes 32768
```

Each response contains `data` (a fragment of the result's JSON text), `nextOffset`,
`eof`, and `byteLength`. To reconstruct the full result, start at zero, follow
`nextOffset` until `eof`, concatenate the `data` strings in order, then parse once.
Individual chunks need not be valid JSON. Read only a slice when that suffices.

Offsets are UTF-8 bytes, not JavaScript character indexes. Use each returned
`nextOffset` unchanged; offsets inside a multibyte character are rejected.
`max-bytes` is at most 65536 and must fit the next character. Resource paging does
not recover text already truncated by a page observation or extraction.

## Finish recovery

If finish is interrupted, run `diagnose --task NAME` before deciding whether
another finish is necessary. If `forcedCleanup` is true, inspect `tabsRetained`:
tabs may remain even when `--discard` was requested. `tabsRetained` describes the
finalization policy, not a count. A confirmed-empty implicit page can be removed
before finalization without appearing in `closedTabIds`; use inventory when
exact remaining tabs matter.

## Inventory and acquisition

`currentTabId` and `focusedWindowId` are null when no eligible window is focused;
per-window `active` flags remain available. Repeat `--tab` for multiple observed
tabs in one window, or use `--group` for an observed retained group. Do not combine
them. Group acquisition takes every member or fails; it preserves the group ID,
title, and color, and the task never renames it. `page` becomes the first
requested tab or the first group member in tab-strip order. Select the intended
owned page with `usePage` when acquiring a group:

```js
const matches = pages().filter(p => p.url() === "https://app.example.test/profile");
assert.equal(matches.length, 1);
usePage(matches[0]);
return await tabbit.observe({frames: "none", maxChars: 4000});
```

Inventory can be partial. `total` counts matching tabs; `complete` means the entire
unfiltered inventory was returned. `groupsScope: "returned-tabs"` means each
group's `visibleTabCount` covers only that response. Do not infer missing tabs or
whole-group counts from a filtered or paginated result.

```text
<launcher> tabs --task NAME --cursor TOKEN
<launcher> tabs --task NAME --group ID
```

Continue from `nextCursor` with the same filters and limit until `truncated` is
false when full inventory is needed. Restart on `STALE_CURSOR`. Both `create`
and `tabs` accept `--state available|owned|claimed`, `--window ID`, `--group ID`,
`--limit 1..200`, and `--cursor TOKEN`.

Acquisition is revalidated atomically. Failure prevents program dispatch, but
ownership persists if acquisition succeeds and attachment or code then fails.
Receipts report acquisition state and `codeDispatched`; dispatch alone does not
prove execution. Failed acquisition reports `outcome: "unchanged"` for an atomic
browser rejection, or `"unknown"` when transport loss or session abort prevents
certainty.

## Response details

Pre-submission failures may return `{ok: false, error}` without a receipt.
For submitted programs, the compact `nodejs` response contains:

| Field | Meaning |
| --- | --- |
| `status` | `queued`, `running`, `succeeded`, `failed`, or `interrupted`. |
| `result` | `requestId` plus inline `value`, resource metadata, or failure details; may include `elapsedMs`. |
| `result.mutationState` | Present for non-success; inspect visible state before repeating actions. |
| `task` | Present for a new task or non-success; identifies the task and whether it was reused; `groupId` appears only when every owned tab shares one group. |
| `transition` | Optional page/document changes; `targetEpoch` and `documentGeneration` are staleness evidence, not durable IDs. |

The `receipt` command returns the durable receipt directly: `status` and
`mutationState` are top-level, and successful `result` is either
`{type: "inline", value}` or `{type: "resource", resourceId, byteLength}`.

Keep JSON stdout separate from diagnostic stderr as described in the main skill.
The launcher exits 0 for success, 70 for failure, and 75 while pending; a nonzero
exit does not erase the receipt.

## Explicit product or instance selection

During normal browsing, do not inspect the registry or set an override without
an explicit user request. Registration failures also permit the scoped
diagnostics and repair below. The stable launcher selects the instance for each
normal command.

On macOS, pinned nondefault-profile cold startup is unsupported. Open that
profile in Tabbit before using its instance ID. Windows registrations include
the user-data directory and support cold start for a valid offline instance.

For an explicit request, inspect only the current user's registry with
read-only OS commands and validate records as described below. Normalize only
case and surrounding space, then match exactly one canonical product:
`Tabbit Browser`, `Tabbit Browser Dev`, `Tabbit`, or `Tabbit Dev`. These are not
aliases. If multiple valid records match, show their instance IDs and ask the user.
A request that only calls the browser "Tabbit" in passing is not explicit; use
the launcher's selection instead of matching it against these names.

Preserve any existing `TABBIT_PLAYWRIGHT_INSTANCE` value, then set the selected
uppercase 16-hex ID before the first command (the ID below is illustrative):

```bash
export TABBIT_PLAYWRIGHT_INSTANCE='0123456789ABCDEF'
```

```powershell
$env:TABBIT_PLAYWRIGHT_INSTANCE = '0123456789ABCDEF'
```

Follow the main skill's startup and execution workflow with this override in
effect. Keep it fixed for receipt and resource reads, recovery, and `finish`.
Do not probe with an unpinned launcher or change the ID during the task.
Only after finish is confirmed, restore the previous value. If it was originally
unset, use `unset TABBIT_PLAYWRIGHT_INSTANCE` on POSIX or
`Remove-Item Env:TABBIT_PLAYWRIGHT_INSTANCE` in PowerShell.

### Validate records without repairing them

On macOS, inspect only `$HOME/.local/share/tabbit-playwright/instances`.
The directory must belong to the current user, mode 0700, with no symlink path
components. `<ID>.instance` must be a regular file owned by that user, mode 0600,
with exactly these three lines (placeholders below describe absolute paths):

```text
# tabbit-playwright instance managed by Tabbit Browser
<absolute path to executable tabbit-playwright-cli>
<absolute user-data directory>/LocalAgent/endpoint.json
```

`<ID>` is 16 uppercase hexadecimal characters. The CLI must be an executable
regular file, the user-data directory must exist, and the endpoint path must
have no symlink components; the endpoint itself may be absent while offline.
For product selection, require `<ID>.product` with the same ownership/mode and
exactly two lines, for example:

```text
# tabbit-playwright product managed by Tabbit Browser
Tabbit Browser Dev
```

The second line must be one of the four canonical products above. The launcher
accepts legacy records without a sidecar, but those do not identify a product.

On Linux, use the same registry directory, ownership, permissions, instance ID
and product sidecar rules. Linux `.instance` records have a fourth line: the
absolute browser executable path used for cold startup. Require both recorded
executables to exist, and reject relative paths or parent traversal. The managed
home launcher executes the versioned client in place so its shared libraries
remain available. When more than one instance is registered, select an explicit
instance before running commands; do not guess between products or profiles.

On Windows, inspect only `%LOCALAPPDATA%\Tabbit\LocalAgent\instances` using
`Get-ChildItem`, `Get-Item`, `Get-Acl`, and bounded
`Get-Content -Raw -Encoding UTF8` (check the file is at most 64 KiB first).
`<ID>.json` must be a regular file under that protected root, with no reparse
components. Require the current user as owner and a protected DACL granting
FullControl only to that user and `SYSTEM` (inherited by children for directories).
Its JSON contains exactly these seven fields:

```json
{
  "version": 1,
  "instanceId": "0123456789ABCDEF",
  "product": "Tabbit Browser Dev",
  "cliPath": "C:\\TabbitDev\\tabbit-playwright-cli.exe",
  "browserPath": "C:\\TabbitDev\\tabbit.exe",
  "userDataDir": "C:\\Users\\Alex\\AppData\\Local\\TabbitDev",
  "endpointPath": "C:\\Users\\Alex\\AppData\\Local\\TabbitDev\\LocalAgent\\endpoint.json"
}
```

Paths and ID above are illustrative. The ID must match the filename and first
16 uppercase hex characters of SHA-256 of the UTF-8 endpoint path. Require a
canonical product and absolute paths without `..`, device prefixes, or reparse
components. The endpoint must be `LocalAgent\endpoint.json` below `userDataDir`.
The CLI basename is `tabbit-playwright-cli.exe`; its directory is either the
browser executable’s directory or a `TabbitDance` directory one or two levels
below it. CLI and browser executables must exist as regular files.

Ignore invalid records for instance selection. Repair is limited to the Windows
fallback below. Never broaden permissions, require administrator access, disable
security controls, or relocate binaries.

## Launcher and routing failures

- **Agent sandbox denial:** use the host approval mechanism for the stable
  launcher or scoped registration diagnostics. Do not change OS ACLs to bypass
  an Agent sandbox denial.
- **OS ownership, mode, ACL, endpoint access, quarantine, or signing policy:**
  verify Agent and Browser share an OS user, then relaunch Browser once so it can
  repair its managed integration. If Windows registration still fails, use the
  fallback below; on other platforms report the remaining denial unchanged.
- **Missing or malformed launcher or registry:** invalid installation.
- **Exit 69:** capture stdout, stderr, and the exit code. Check the selected
  instance. `diagnose` also needs a valid route, so do not repeat it when routing
  itself fails. Older launchers can return 69 without an error message.
- **Runtime unavailable:** relaunch Browser once with permission; do not launch
  the service yourself or switch browser backends.

### Windows registration repair fallback

When registration remains broken after one normal Browser relaunch, an Agent
may repair the affected current-user instance as part of the user's requested
Tabbit troubleshooting. This is a supported exception to read-only selection,
not a general permission to edit Browser or host settings. Do not repeat
reinstallation or restart loops. If several records could be the target, resolve
the intended Browser/user-data directory with the user before writing.

1. Preserve evidence: read the exact instance JSON as UTF-8, record its original
   bytes, ACL SDDL, file times, and the launcher error. Keep a uniquely named
   backup outside the `instances` directory; do not overwrite an earlier backup.
   Verify the filename/instanceId and endpoint-path hash described above. Check
   that the file is current-user-owned, is a regular single-link file, and that
   its path has no reparse components. Its effective DACL must grant FullControl
   only to that user and `SYSTEM`; protection/inheritance flags may be repaired,
   but bytes exposed to any additional principal are untrusted. Stop on another
   owner, hard links, extra or deny ACEs, a null DACL, ambiguous paths, malformed
   JSON, or access denial; do not take ownership or repair that file in place.
2. Verify the actual installed Browser executable, version, and user-data
   directory. Resolve the matching `TabbitDance` directory from that installation,
   not merely the highest version directory. Check the replacement executables
   exist and their Authenticode signatures are valid with the expected Tabbit
   publisher. The Browser executable may live in `Application`, while the CLI
   lives in `Application\<version>\TabbitDance`; do not move `browserPath` into
   the version directory by assumption.
3. Have the user save work and exit Browser normally before writing; verify the
   corresponding processes have exited. Do not force-kill them. Correct only
   the proven-stale `cliPath`; change `browserPath` only if independently verified
   wrong. Preserve `version`, `instanceId`, `product`, `endpointPath`, and
   `userDataDir`. Write valid UTF-8 without BOM and re-read to verify the fields.
   Never execute paths obtained from an invalid registration to diagnose it.
4. Only when the pre-write effective DACL already passed the user-and-`SYSTEM`
   exclusivity check may protection flags be repaired in place. Restore the exact
   product ACL on that verified file only: current Windows user SID as owner,
   protected DACL, and exactly two explicit Allow FullControl entries for that
   SID and SYSTEM (`S-1-5-18`), with no inheritance/propagation flags on the file
   ACEs. In PowerShell, construct a fresh `FileSecurity`, use
   `SetAccessRuleProtection($true, $false)`, add those two rules, and apply with
   `Set-Acl -LiteralPath`. Do not use an additive `icacls /grant`, recursive
   permission changes, or ACL repair to make exposed bytes trusted. `D:PAI` is
   acceptable when the ACEs are explicit: `P` is protection; `AI` alone is not
   protection, and `ID` on an ACE means inherited. Recheck the final owner/DACL
   and exact bytes through the same verified file object.
5. Start the verified Browser normally. Temporarily pin the repaired instance
   with `TABBIT_PLAYWRIGHT_INSTANCE`, run `<launcher> tabs`, capture its exit code
   and result, then restore the previous override even on failure. Success is
   exit 0 with the expected Browser's inventory, not merely a changed timestamp.
   Identical registration bytes may legitimately skip rewriting. Do not perform
   page actions as part of this check.
6. If repair cannot be completed, restore only a pre-change snapshot that passed
   the exclusivity checks above, then reverify its bytes and ACL; an unsafe
   evidence copy must never be restored into the registry. Report restoration
   failures explicitly. If the verified repair completes but tabs still fails,
   retain the backup and report the new error; do not expand to deleting or
   changing `LocalAgent`, Runtime, Skill, or user-data directories. Report
   exactly what changed and distinguish restored CLI access from proof that
   automatic registration now works.

For further diagnosis, capture one normal startup using the verified Browser
executable and original user-data directory with `--enable-logging
--disable-tab-log --log-level=0 --log-file="<absolute temporary log path>"`.
Inspect `Unable to install TabbitDance host integration` and Browser Runtime
errors. `config_read_failed` at the instance file can mean ACL validation failed,
not invalid JSON. `filesystem_error` needs its path and operation to attribute;
do not automatically label it Skill failure. Version 1.14.19 couples Skill
installation with route publication, so a Skill failure can prevent updates.
The current Browser publishes routing separately.

Diagnostics may inspect endpoint modification time and only the non-secret
`browserPid`/`generation` fields to correlate the actual Browser process; never
print or copy its token. An endpoint older than the diagnostic launch does not
prove that launch reached ready. A tab-strip-observer ready event is not Runtime
ready. Preserve uncertainty when logs do not identify the failing operation.
