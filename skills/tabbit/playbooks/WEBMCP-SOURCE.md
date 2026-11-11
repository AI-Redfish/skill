# Tabbit WebMCP conversions

Source: https://github.com/TabbitAi/tabbit-webmcp

Revision: `13fef01b80ce371aeb53cf92bd3c677bb25c24bd` (default branch `main`).
The exact private repository was cloned over the user's existing SSH access into
`/Users/cxq/tab/tabbit-webmcp`; no target checkout or branch was switched.

## Provenance and license

The source tree at this revision contains **no LICENSE/COPYING/NOTICE file, no
copyright notice, and no package.json license field**. Its package.json marks
it private. These are adaptations made at the repository user's explicit request;
this document does not assign an open-source license or invent a copyright owner.
Any permission needed for distribution beyond that authorized use must be
established from the source owner. No third-party runtime package is copied into
these recipes. The original Google/GitHub/X material has separate CitroLabs
provenance and its full MIT license in [NOTICE.md](NOTICE.md), preserved unchanged.
That MIT grant is not attributed to the WebMCP source.

## Coverage

[WEBMCP-MAPPING.json](WEBMCP-MAPPING.json) maps **77 imported site capabilities
across 12 converted site packs**. Together with the original Google/GitHub/X
recipes, the library contains 85 site recipes across 14 site packs. Existing
X and YouTube content is preserved alongside the conversions.

| Source module | Capabilities | Playbook |
| --- | ---: | --- |
| site-bilibili | 4 | bilibili/webmcp.js |
| site-youtube | 5 | youtube/webmcp.js |
| site-xiaoyuzhou | 3 | xiaoyuzhou/webmcp.js |
| site-xiaohongshu | 3 | xiaohongshu/webmcp.js |
| site-amazon | 2 | amazon/webmcp.js |
| site-x | 10 | x-com/webmcp.js |
| site-weibo | 8 | weibo/webmcp.js |
| site-taobao | 2 | taobao/webmcp.js |
| site-jingdong | 2 | jingdong/webmcp.js |
| site-goofish | 4 | goofish/webmcp.js |
| site-feishu-base | 21 | feishu-base/webmcp.js |
| site-bytedance-resume | 13 | bytedance-resume/webmcp.js |

### Other source modules and exports

- `apps/extension/src/page-probe.ts`: all registered operation branches become
  direct named functions. Unreachable legacy YouTube branches after the earlier
  unconditional YouTube return are not separate registered capabilities.
- `packages/site-*/src/index.ts`: route predicates and tool availability become
  callback preconditions. `packages/sites` is the adapter aggregate, not another
  capability. `packages/runtime/adapter-factory` input contracts become direct
  input checks, with complete schemas documented per function.
- `runtime/subtitles` and `runtime/download`: subtitle conversion and filename
  sanitation are in [media-assets.js](media-assets.js). CDN/origin checks remain
  in that explicit save recipe. Source public-URL formatting occurs in the
  extraction functions where relevant; there is no extension result envelope.
- `extension/background`: X thread/article and Goofish search temporary-tab
  workflows use existing `context.newPage`, `goto`, `evaluate`, and `close` in
  the respective packs. Native `chrome.downloads` becomes explicit `page.fetch`
  plus artifact writes, with the limits below.
- `contracts`, `runtime/registrar`, `runtime/types`, `runtime/index`,
  `extension/content` and extension popup/config/status scaffolding supply
  validation, lifecycle, registration or UI infrastructure.
  They are not additional agent capabilities. Their server/registration/dispatch
  infrastructure is deliberately not shipped.

## Using a conversion

Each site `webmcp.js` contains ordinary, inspectable, standalone page callbacks.
Copy the selected definition into nodejs and call it directly:

```js
// Paste youtube_get_video_details from youtube/webmcp.js above this line.
console.log(await page.evaluate(youtube_get_video_details, {}));
```

No function runs just because an agent reads or pastes its definition. Inputs,
effects, routes and limits are documented in each pack's `webmcp.md`. Callbacks
return `{data, warnings?, assets?, error?}`. Check errors and truncation. Asset
records are not saved files: explicitly use `saveMediaAssets` for download/export.
For temporary-page flows, paste the relevant site definitions and Node helper,
then explicitly call the helper. Source error codes and meaningful data remain;
WebMCP registration and extension download IDs do not.

## Limits and observable behavior

- Page evaluation uses the authenticated page, current DOM and exposed page
  globals. The original selectors, bounded scrolling, polling, pagination,
  scoping and confirmation requirements are retained. Bounds reject nonfinite,
  fractional and out-of-range inputs. Source fixed-delay polling is retained
  where it exists; it is not a guarantee that a future page layout will load.
- Feishu requires `window.bitableStore.modelOperator` and `commandManager` and
  compatible table/view/field models. Unavailable or denied APIs return errors;
  no external API or WebMCP extension is installed as a fallback.
- Resume writes fill sections/attachments. The source has no save/submit
  capability and these recipes do not claim persistence after field edits.
- Media saving uses browser fetch with normal CORS/session rules. The existing
  transport caps files at **8 MiB**, with subtitles limited to **5 MiB**. Larger
  video/audio downloads require the native site UI; the conversion does not
  remove that transport limit. Signature deciphering, DRM, split-track merging,
  platform token generation and auth bypass are not implemented in the source.
- Source extension lifecycle cancellation/generation guards are replaced by
  Tabbit's existing task/evaluation lifecycle. A failed or timed-out write may
  already have changed the page; inspect the state before retrying. No change
  is made to Tabbit site matching, once-per-task announcements, original results,
  or receipt replay.

## Validation

Validation details and limits are recorded in the final task report. The checked-in
`test/webmcp-recipes.test.mjs` exercises standalone callbacks in isolated realms,
input/route boundaries, pagination, media transformation and controlled Feishu
model writes. No real external writes are used for validation. These fixtures
cannot establish all live layout, locale, account-state or pagination variants.

## Ablation

Removed the WebMCP adapter/registration/dispatch transport, all operation-selector
branches and unused operation helpers from the converted functions. Kept ordinary
functions with direct calls, plain manifests, existing Tabbit page/context/fetch
APIs, and one shared explicit media-save recipe. At conversion time, a final
ablation removed unused metadata initializers and route metadata, reducing the
callbacks from 16,168 to 12,452 lines; all 27 conversion tests passed again.
Site-local helper code is repeated
where needed to keep every page callback serializable without a new execution
layer. Existing Google/GitHub/X recipes, YouTube notes, and MIT attribution remain.

### Recorded verification (2026-09-15)

These results were recorded before the local catalog was removed; the test
counts describe that earlier suite.

- 18 dependency-free conversion tests: all definitions, wrong-origin checks,
  selected extraction, confirmations, temporary-tab cleanup, subtitle writes,
  and all 15 Feishu write families' permission-denial paths.
- Nine DOM unit fixture scenarios: Amazon, JD, Goofish pagination and controlled
  messaging, X thread/profile/like, Weibo feed/comments, Taobao search, Xiaoyuzhou
  audio and all 13 resume operations. No browser was launched by these tests.
- 43 existing focused manifest/asset/controller tests: containment, symlink escapes,
  original recipe behavior, once-per-task announcements and receipt replay.
- Live read-only smoke: YouTube `youtube_get_video_details` on
  `https://www.youtube.com/watch?v=jNQXAC9IVRw` returned “Me at the zoo”,
  19 seconds and two subtitle tracks through the existing Develop Tabbit CLI.
  This does not validate other accounts/locales/layouts or media file downloads.
- Every mapping row lists its actual validation level. Definition/origin coverage
  alone is **not** a successful behavioral test. Live external writes were not run.

Later defect regressions extend the DOM suite with YouTube collection and reply
boundaries, Bilibili shadow comments, Xiaoyuzhou comment roots, X quote identity
and timestamps, Weibo comment completeness and text expansion, Amazon price and
rating markup, and JD advertising badges. The historical counts above describe
the conversion checkpoint, not the expanded suite. Live checks use bounded
desktop samples; they do not establish complete pagination or write behavior.

The richer source HTML fixtures need a DOM implementation that the existing
VM mocks do not provide. For that optional focused unit check only, install
`jsdom@26.1.0` in a temporary directory (no production or repository dependency
was added). Reproduce with the exact source checkout and the Node binary under
`out/Develop/.../Resources/TabbitDance/node`:

```sh
npm install --prefix /tmp/webmcp-fixtures --no-audit --no-fund jsdom@26.1.0
WEBMCP_JSDOM_ROOT=/tmp/webmcp-fixtures/node_modules/jsdom \
WEBMCP_SOURCE_ROOT=/absolute/path/to/tabbit-webmcp \
"$develop_node" --test tab/tools/tabbit_playwright/test/webmcp-dom-fixtures.mjs
```

The regular conversion suite is
`"$develop_node" --test tab/tools/tabbit_playwright/test/webmcp-recipes.test.mjs`.
For existing runtime tests, set `TABBIT_PLAYWRIGHT_TEST_NODE_MODULES` to the
Develop bundle's `runtime/third_party/playwright/node_modules`. Asset parity
checks use `TABBIT_PLAYBOOK_BUNDLE_ROOT` pointing at its `TabbitDance` directory.
