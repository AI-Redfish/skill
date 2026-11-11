// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取表格上下文 — read. 读取当前
// Base、数据表、视图、字段结构、可写性和加载范围；写入前先调用。
async function feishu_base_get_table_context(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) || (typeof rawInput['viewId'] === 'string' && [
          ...rawInput['viewId']
        ].length >= 1 && [...rawInput['viewId']].length <= 128))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    const tableRecordIds =
        asIds(table.getRecordIds?.() || Object.keys(table.records || {})) || [];
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const loadedRecordIds = orderedRecordIds || tableRecordIds;
    const visibleFieldIds = orderedFieldIds ||
        fields.map((field) => String(field.id || '')).filter(Boolean);
    const recordOrder = orderedRecordIds ? 'view_display' : 'table_storage';
    const fieldOrder = orderedFieldIds ? 'view_display' : 'table_storage';
    const tableTotalRecords = Number(
        table.getAllRecordCount?.(true) ?? table.getRecordCount?.() ??
        table.recordsNum ?? tableRecordIds.length);
    const tableLoadedRecords =
        Number(table.getLoadedRecordCount?.() ?? tableRecordIds.length);
    const visibleRecordCount =
        Number(view?.getVisibleRecordsCount?.() ?? loadedRecordIds.length);
    const orderWarnings = [
      ...(recordOrder === 'view_display' ?
              [] :
              [
                '页面运行时未提供视图可见行顺序；记录按底层存储顺序返回，不能用于 A1/B4 等位置引用。'
              ]),
      ...(fieldOrder === 'view_display' ?
              [] :
              [
                '页面运行时未提供视图可见列顺序；字段顺序不能用于 A1/B4 等位置引用。'
              ])
    ];
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const inputHint = (field) => {
      const ui = String(field.fieldUIType || '');
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        return 'string';
      if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        return 'number';
      if (ui === 'Checkbox')
        return 'boolean';
      if (ui === 'DateTime')
        return 'YYYY-MM-DD HH:mm:ss、ISO 8601 或毫秒时间戳';
      if (ui === 'SingleSelect')
        return '选项名或 option id';
      if (ui === 'MultiSelect')
        return '选项名或 option id 数组';
      if (ui === 'Url')
        return 'URL 字符串';
      if (/User|GroupChat/.test(ui))
        return '页面原生用户/群单元格值，或 ID 数组（以页面校验为准）';
      if (/Link/.test(ui))
        return '关联记录 ID 数组（以页面校验为准）';
      return '页面原生 CellValue；工具会调用飞书字段模型校验';
    };
    const summarizeField = (field) => {
      const options = Array.isArray(field.property?.options) ?
          field.property.options.map((option) => ({
                                       id: option.id,
                                       name: cleanText(option.name),
                                       color: option.color ?? null
                                     })) :
          undefined;
      return {
        id: String(field.id || ''),
        name: cleanText(field.name),
        type: field.type,
        fieldUIType: String(field.fieldUIType || ''),
        writable: fieldWritable(field),
        inputHint: inputHint(field),
        multiple: Boolean(field.multiple ?? field.property?.multiple),
        ...(options ? {options} : {})
      };
    };
    const context = {
      base: {title: cleanText(store.baseMeta?.title || document.title)},
      table: {
        id: String(table.id || activeTableId),
        name: cleanText(table.name),
        recordCount: tableTotalRecords,
        loadedRecordCount: tableLoadedRecords
      },
      view: view ? {
        id: String(view.id || viewId),
        name: cleanText(view.name),
        type: view.type ?? null,
        recordOrder,
        fieldOrder,
        visibleRecordCount,
        loadedVisibleRecordCount: loadedRecordIds.length,
        visibleFieldIds
      } :
                   (viewId ? {
                     id: viewId,
                     name: '',
                     type: null,
                     recordOrder,
                     fieldOrder,
                     visibleRecordCount,
                     loadedVisibleRecordCount: loadedRecordIds.length,
                     visibleFieldIds
                   } :
                             null),
      fields: fields.map(summarizeField),
      capabilities: {
        createTable: store.commandManager.hasCommand?.('AddTable') !== false,
        renameTable: store.commandManager.hasCommand?.('SetTable') !== false,
        deleteTable: store.commandManager.hasCommand?.('DeleteTable') !== false,
        createField: store.commandManager.hasCommand?.('AddField') !== false,
        renameField:
            store.commandManager.hasCommand?.('SetFieldAttr') !== false,
        addFieldOptions:
            store.commandManager.hasCommand?.('AddOptions') !== false,
        deleteField: store.commandManager.hasCommand?.('DeleteField') !== false,
        resolveRange:
            recordOrder === 'view_display' && fieldOrder === 'view_display',
        addRecords:
            store.commandManager.hasCommand?.('ExtendAddRecords') !== false,
        updateRecords:
            store.commandManager.hasCommand?.('SetRecords') !== false,
        clearCells: store.commandManager.hasCommand?.('SetRecords') !== false,
        deleteRecords:
            store.commandManager.hasCommand?.('DeleteRecords') !== false,
        createView: store.commandManager.hasCommand?.('AddView') !== false,
        renameView: store.commandManager.hasCommand?.('SetView') !== false,
        updateView:
            store.commandManager.hasCommand?.('SetViewProperty') !== false,
        deleteView: store.commandManager.hasCommand?.('DeleteView') !== false,
        network: String(store.network || 'unknown')
      },
      scope: input.tableId ? 'loaded_table' : 'current_page_table'
    };
    return {
      data: context,
      warnings: [
        ...orderWarnings,
        ...(tableLoadedRecords < tableTotalRecords ?
                ['页面当前只加载了部分记录；字段结构和总记录数仍可用。'] :
                [])
      ]
    };
  }
}


// 列出数据表 — read. 列出当前 Base
// 页面模型中已加载的数据表、字段数、视图数和记录数。
async function feishu_base_list_tables(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => [].includes(key))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeTable = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      active: String(entry.id || '') === activeTableId,
      fieldCount: Number(
          entry.getFieldCount?.() ?? entry.getAllFields?.()?.length ??
          entry.fields?.length ?? 0),
      viewCount: Number(entry.getViews?.()?.length ?? entry.views?.length ?? 0),
      recordCount: Number(
          entry.getAllRecordCount?.(true) ?? entry.getRecordCount?.() ??
          entry.recordsNum ?? 0)
    });
    return {
      data: {items: allTables.map(summarizeTable), activeTableId},
      warnings: []
    };
  }
}


// 创建数据表 — write. 在当前 Base 中创建数据表并设置名称。
async function feishu_base_create_table(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'name' in rawInput &&
        Object.keys(rawInput).every(key => ['name'].includes(key)) &&
        (!('name' in rawInput) || (typeof rawInput['name'] === 'string' && [
          ...rawInput['name']
        ].length >= 1 && [...rawInput['name']].length <= 100))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeTable = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      active: String(entry.id || '') === activeTableId,
      fieldCount: Number(
          entry.getFieldCount?.() ?? entry.getAllFields?.()?.length ??
          entry.fields?.length ?? 0),
      viewCount: Number(entry.getViews?.()?.length ?? entry.views?.length ?? 0),
      recordCount: Number(
          entry.getAllRecordCount?.(true) ?? entry.getRecordCount?.() ??
          entry.recordsNum ?? 0)
    });
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      const name = cleanText(input.name);
      if (allTables.some((entry) => cleanText(entry.name) === name))
        throw new Error(`VALIDATION_ERROR: 数据表“${name}”已存在。`);
      const added =
          store.commandManager.execute({cmd: 'AddTable', from: 'webmcp'});
      if (!commandOk(added))
        return commandError('飞书页面拒绝创建数据表。', added);
      const createdTableId = String(added.data?.tableId || '');
      const renamed = store.commandManager.execute(
          {cmd: 'SetTable', tableId: createdTableId, name});
      if (!commandOk(renamed, true))
        return commandError('数据表已创建，但页面拒绝设置名称。', renamed);
      const created = store.modelOperator.getTableById?.(createdTableId);
      return {
        data: {
          created: true,
          table: created ? summarizeTable(created) : {id: createdTableId, name}
        },
        warnings: []
      };
    }
  }
}


// 重命名数据表 — write. 按数据表 ID 或精确名称重命名数据表。
async function feishu_base_rename_table(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'tableId' in rawInput &&
        'name' in rawInput &&
        Object.keys(rawInput).every(key => ['tableId', 'name'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('name' in rawInput) || (typeof rawInput['name'] === 'string' && [
          ...rawInput['name']
        ].length >= 1 && [...rawInput['name']].length <= 100))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeTable = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      active: String(entry.id || '') === activeTableId,
      fieldCount: Number(
          entry.getFieldCount?.() ?? entry.getAllFields?.()?.length ??
          entry.fields?.length ?? 0),
      viewCount: Number(entry.getViews?.()?.length ?? entry.views?.length ?? 0),
      recordCount: Number(
          entry.getAllRecordCount?.(true) ?? entry.getRecordCount?.() ??
          entry.recordsNum ?? 0)
    });
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      const name = cleanText(input.name);
      if (allTables.some(
              (entry) => String(entry.id) !== tableId &&
                  cleanText(entry.name) === name))
        throw new Error(`VALIDATION_ERROR: 数据表“${name}”已存在。`);
      const result =
          store.commandManager.execute({cmd: 'SetTable', tableId, name});
      if (!commandOk(result, true))
        return commandError('飞书页面拒绝重命名数据表。', result);
      return {
        data: {
          updated: true,
          table: summarizeTable(table),
          noChanges: result?.result === 0 || !result
        },
        warnings: []
      };
    }
  }
}


// 删除数据表 — write. 删除明确指定的数据表；不可逆，必须传 confirm=true。
async function feishu_base_delete_table(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'tableId' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'confirm'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeTable = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      active: String(entry.id || '') === activeTableId,
      fieldCount: Number(
          entry.getFieldCount?.() ?? entry.getAllFields?.()?.length ??
          entry.fields?.length ?? 0),
      viewCount: Number(entry.getViews?.()?.length ?? entry.views?.length ?? 0),
      recordCount: Number(
          entry.getAllRecordCount?.(true) ?? entry.getRecordCount?.() ??
          entry.recordsNum ?? 0)
    });
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      if (input.confirm !== true)
        throw new Error('VALIDATION_ERROR: 删除数据表必须传 confirm=true。');
      const target = summarizeTable(table);
      const result =
          store.commandManager.execute({cmd: 'DeleteTable', tableId});
      if (!commandOk(result))
        return commandError(
            '飞书页面拒绝删除数据表；最后一张表或无权限的表不能删除。', result);
      return {data: {deleted: true, table: target}, warnings: []};
    }
  }
}


// 创建字段 — write.
// 在指定数据表创建文本、数字、选项、日期或复选框字段；type=select 时用 multiple
// 区分单选/多选，并可同时创建选项。
async function feishu_base_create_field(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'name' in rawInput && 'type' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'name', 'type', 'multiple', 'options']
                       .includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('name' in rawInput) ||
         (typeof rawInput['name'] === 'string' &&
          [...rawInput['name']].length >= 1 &&
          [...rawInput['name']].length <= 100)) &&
        (!('type' in rawInput) ||
         (typeof rawInput['type'] === 'string' &&
          [
            'text', 'number', 'select', 'single_select', 'multi_select',
            'datetime', 'checkbox'
          ].includes(rawInput['type']))) &&
        (!('multiple' in rawInput) ||
         (typeof rawInput['multiple'] === 'boolean')) &&
        (!('options' in rawInput) ||
         (Array.isArray(rawInput['options']) &&
          rawInput['options'].length <= 1000 &&
          rawInput['options'].every(
              item => typeof item === 'string' && [...item].length >= 1 &&
                  [...item].length <= 100)))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const inputHint = (field) => {
      const ui = String(field.fieldUIType || '');
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        return 'string';
      if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        return 'number';
      if (ui === 'Checkbox')
        return 'boolean';
      if (ui === 'DateTime')
        return 'YYYY-MM-DD HH:mm:ss、ISO 8601 或毫秒时间戳';
      if (ui === 'SingleSelect')
        return '选项名或 option id';
      if (ui === 'MultiSelect')
        return '选项名或 option id 数组';
      if (ui === 'Url')
        return 'URL 字符串';
      if (/User|GroupChat/.test(ui))
        return '页面原生用户/群单元格值，或 ID 数组（以页面校验为准）';
      if (/Link/.test(ui))
        return '关联记录 ID 数组（以页面校验为准）';
      return '页面原生 CellValue；工具会调用飞书字段模型校验';
    };
    const summarizeField = (field) => {
      const options = Array.isArray(field.property?.options) ?
          field.property.options.map((option) => ({
                                       id: option.id,
                                       name: cleanText(option.name),
                                       color: option.color ?? null
                                     })) :
          undefined;
      return {
        id: String(field.id || ''),
        name: cleanText(field.name),
        type: field.type,
        fieldUIType: String(field.fieldUIType || ''),
        writable: fieldWritable(field),
        inputHint: inputHint(field),
        multiple: Boolean(field.multiple ?? field.property?.multiple),
        ...(options ? {options} : {})
      };
    };
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    const optionId = () =>
        `opt${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`;
    const buildOptions = (names, existing = []) => {
      const seen = new Set(existing.map((entry) => cleanText(entry.name)));
      return names.map((entry, index) => {
        const name = cleanText(entry);
        if (!name)
          throw new Error('VALIDATION_ERROR: 选项名不能为空。');
        if (seen.has(name))
          throw new Error(`VALIDATION_ERROR: 选项“${name}”重复或已存在。`);
        seen.add(name);
        return {id: optionId(), name, color: (existing.length + index) % 11};
      });
    };
    {
      const name = cleanText(input.name);
      if (fields.some((entry) => cleanText(entry.name) === name))
        throw new Error(`VALIDATION_ERROR: 字段“${name}”已存在。`);
      const requestedType = cleanText(input.type);
      const normalizedType = requestedType === 'select' ?
          (input.multiple === true ? 'multi_select' : 'single_select') :
          requestedType;
      if (input.multiple !== undefined && requestedType !== 'select')
        throw new Error('VALIDATION_ERROR: multiple 只用于 type=select。');
      const typeMap = {
        text: {type: 1, fieldUIType: 'Text'},
        number: {type: 2, fieldUIType: 'Number'},
        single_select: {type: 3, fieldUIType: 'SingleSelect'},
        multi_select: {type: 4, fieldUIType: 'MultiSelect'},
        datetime: {type: 5, fieldUIType: 'DateTime'},
        checkbox: {type: 7, fieldUIType: 'Checkbox'}
      };
      const definition = typeMap[normalizedType];
      if (!definition)
        throw new Error(
            `VALIDATION_ERROR: 暂不支持字段类型“${requestedType}”。`);
      const rawOptions = Array.isArray(input.options) ? input.options : [];
      if (rawOptions.length && !/select$/.test(normalizedType))
        throw new Error(
            'VALIDATION_ERROR: 只有单选或多选字段可以设置 options。');
      const options =
          /select$/.test(normalizedType) ? buildOptions(rawOptions) : [];
      const newFieldId = String(
          table.getNewFieldId?.() ||
          `fld${crypto.randomUUID().replace(/-/g, '').slice(0, 10)}`);
      const data = {name, ...definition};
      if (/select$/.test(normalizedType))
        data.property = {options, optionsType: 0};
      const result = store.commandManager.execute(
          {cmd: 'AddField', tableId, viewId, data, newFieldId, from: 'webmcp'});
      if (!commandOk(result))
        return commandError(
            '飞书页面拒绝创建字段；请确认字段类型、名称和当前权限。', result);
      const createdId = String(result.data?.fieldId || newFieldId);
      const created =
          table.getFieldById?.(createdId) || table.getField?.(createdId);
      return {
        data: {
          created: true,
          field: created ? summarizeField(created) :
                           {id: createdId, name, ...definition}
        },
        warnings: []
      };
    }
  }
}


// 重命名字段 — write. 按字段 ID 或精确名称重命名字段，不改变字段类型和已有值。
async function feishu_base_rename_field(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'fieldId' in rawInput &&
        'name' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'fieldId', 'name'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('fieldId' in rawInput) ||
         (typeof rawInput['fieldId'] === 'string' &&
          [...rawInput['fieldId']].length >= 1 &&
          [...rawInput['fieldId']].length <= 128)) &&
        (!('name' in rawInput) || (typeof rawInput['name'] === 'string' && [
          ...rawInput['name']
        ].length >= 1 && [...rawInput['name']].length <= 100))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const inputHint = (field) => {
      const ui = String(field.fieldUIType || '');
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        return 'string';
      if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        return 'number';
      if (ui === 'Checkbox')
        return 'boolean';
      if (ui === 'DateTime')
        return 'YYYY-MM-DD HH:mm:ss、ISO 8601 或毫秒时间戳';
      if (ui === 'SingleSelect')
        return '选项名或 option id';
      if (ui === 'MultiSelect')
        return '选项名或 option id 数组';
      if (ui === 'Url')
        return 'URL 字符串';
      if (/User|GroupChat/.test(ui))
        return '页面原生用户/群单元格值，或 ID 数组（以页面校验为准）';
      if (/Link/.test(ui))
        return '关联记录 ID 数组（以页面校验为准）';
      return '页面原生 CellValue；工具会调用飞书字段模型校验';
    };
    const summarizeField = (field) => {
      const options = Array.isArray(field.property?.options) ?
          field.property.options.map((option) => ({
                                       id: option.id,
                                       name: cleanText(option.name),
                                       color: option.color ?? null
                                     })) :
          undefined;
      return {
        id: String(field.id || ''),
        name: cleanText(field.name),
        type: field.type,
        fieldUIType: String(field.fieldUIType || ''),
        writable: fieldWritable(field),
        inputHint: inputHint(field),
        multiple: Boolean(field.multiple ?? field.property?.multiple),
        ...(options ? {options} : {})
      };
    };
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      const field = fieldByInputKey(cleanText(input.fieldId));
      const name = cleanText(input.name);
      if (fields.some(
              (entry) =>
                  entry.id !== field.id && cleanText(entry.name) === name))
        throw new Error(`VALIDATION_ERROR: 字段“${name}”已存在。`);
      const result = store.commandManager.execute({
        cmd: 'SetFieldAttr',
        tableId,
        viewId,
        fieldId: field.id,
        data: {name},
        from: 'webmcp'
      });
      if (!commandOk(result, true))
        return commandError('飞书页面拒绝重命名字段。', result);
      return {
        data: {
          updated: true,
          field: summarizeField(table.getFieldById?.(field.id) || field),
          noChanges: result?.result === 0 || !result
        },
        warnings: []
      };
    }
  }
}


// 增加字段选项 — write. 向单选或多选字段追加选项；不会删除或覆盖已有选项。
async function feishu_base_add_field_options(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'fieldId' in rawInput &&
        'options' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'fieldId', 'options'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('fieldId' in rawInput) ||
         (typeof rawInput['fieldId'] === 'string' &&
          [...rawInput['fieldId']].length >= 1 &&
          [...rawInput['fieldId']].length <= 128)) &&
        (!('options' in rawInput) ||
         (Array.isArray(rawInput['options']) &&
          rawInput['options'].length >= 1 &&
          rawInput['options'].length <= 1000 &&
          rawInput['options'].every(
              item => typeof item === 'string' && [...item].length >= 1 &&
                  [...item].length <= 100)))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const inputHint = (field) => {
      const ui = String(field.fieldUIType || '');
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        return 'string';
      if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        return 'number';
      if (ui === 'Checkbox')
        return 'boolean';
      if (ui === 'DateTime')
        return 'YYYY-MM-DD HH:mm:ss、ISO 8601 或毫秒时间戳';
      if (ui === 'SingleSelect')
        return '选项名或 option id';
      if (ui === 'MultiSelect')
        return '选项名或 option id 数组';
      if (ui === 'Url')
        return 'URL 字符串';
      if (/User|GroupChat/.test(ui))
        return '页面原生用户/群单元格值，或 ID 数组（以页面校验为准）';
      if (/Link/.test(ui))
        return '关联记录 ID 数组（以页面校验为准）';
      return '页面原生 CellValue；工具会调用飞书字段模型校验';
    };
    const summarizeField = (field) => {
      const options = Array.isArray(field.property?.options) ?
          field.property.options.map((option) => ({
                                       id: option.id,
                                       name: cleanText(option.name),
                                       color: option.color ?? null
                                     })) :
          undefined;
      return {
        id: String(field.id || ''),
        name: cleanText(field.name),
        type: field.type,
        fieldUIType: String(field.fieldUIType || ''),
        writable: fieldWritable(field),
        inputHint: inputHint(field),
        multiple: Boolean(field.multiple ?? field.property?.multiple),
        ...(options ? {options} : {})
      };
    };
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    const optionId = () =>
        `opt${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`;
    const buildOptions = (names, existing = []) => {
      const seen = new Set(existing.map((entry) => cleanText(entry.name)));
      return names.map((entry, index) => {
        const name = cleanText(entry);
        if (!name)
          throw new Error('VALIDATION_ERROR: 选项名不能为空。');
        if (seen.has(name))
          throw new Error(`VALIDATION_ERROR: 选项“${name}”重复或已存在。`);
        seen.add(name);
        return {id: optionId(), name, color: (existing.length + index) % 11};
      });
    };
    {
      const field = fieldByInputKey(cleanText(input.fieldId));
      if (!['SingleSelect', 'MultiSelect'].includes(
              String(field.fieldUIType || '')))
        throw new Error(`VALIDATION_ERROR: 字段“${
            cleanText(field.name)}”不是单选或多选字段。`);
      const existing =
          Array.isArray(field.property?.options) ? field.property.options : [];
      const options = buildOptions(
          Array.isArray(input.options) ? input.options : [], existing);
      const result = store.commandManager.execute({
        cmd: 'AddOptions',
        tableId,
        viewId,
        fieldId: field.id,
        options,
        from: 'webmcp'
      });
      if (!commandOk(result))
        return commandError('飞书页面拒绝增加字段选项。', result);
      return {
        data: {
          addedCount: options.length,
          options,
          field: summarizeField(table.getFieldById?.(field.id) || field)
        },
        warnings: []
      };
    }
  }
}


// 删除字段 — write. 删除明确指定的非主字段；不可逆，必须传 confirm=true。
async function feishu_base_delete_field(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'fieldId' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'fieldId', 'confirm'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('fieldId' in rawInput) ||
         (typeof rawInput['fieldId'] === 'string' &&
          [...rawInput['fieldId']].length >= 1 &&
          [...rawInput['fieldId']].length <= 128)) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const inputHint = (field) => {
      const ui = String(field.fieldUIType || '');
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        return 'string';
      if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        return 'number';
      if (ui === 'Checkbox')
        return 'boolean';
      if (ui === 'DateTime')
        return 'YYYY-MM-DD HH:mm:ss、ISO 8601 或毫秒时间戳';
      if (ui === 'SingleSelect')
        return '选项名或 option id';
      if (ui === 'MultiSelect')
        return '选项名或 option id 数组';
      if (ui === 'Url')
        return 'URL 字符串';
      if (/User|GroupChat/.test(ui))
        return '页面原生用户/群单元格值，或 ID 数组（以页面校验为准）';
      if (/Link/.test(ui))
        return '关联记录 ID 数组（以页面校验为准）';
      return '页面原生 CellValue；工具会调用飞书字段模型校验';
    };
    const summarizeField = (field) => {
      const options = Array.isArray(field.property?.options) ?
          field.property.options.map((option) => ({
                                       id: option.id,
                                       name: cleanText(option.name),
                                       color: option.color ?? null
                                     })) :
          undefined;
      return {
        id: String(field.id || ''),
        name: cleanText(field.name),
        type: field.type,
        fieldUIType: String(field.fieldUIType || ''),
        writable: fieldWritable(field),
        inputHint: inputHint(field),
        multiple: Boolean(field.multiple ?? field.property?.multiple),
        ...(options ? {options} : {})
      };
    };
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      if (input.confirm !== true)
        throw new Error('VALIDATION_ERROR: 删除字段必须传 confirm=true。');
      const field = fieldByInputKey(cleanText(input.fieldId));
      if (table.isPrimaryField?.(field.id))
        throw new Error(
            'VALIDATION_ERROR: 主字段不能删除；可使用重命名字段或安全的字段类型更新。');
      const target = summarizeField(field);
      const result = store.commandManager.execute({
        cmd: 'DeleteField',
        tableId,
        viewId,
        fieldId: field.id,
        from: 'webmcp'
      });
      if (!commandOk(result))
        return commandError('飞书页面拒绝删除字段。', result);
      return {data: {deleted: true, field: target}, warnings: []};
    }
  }
}


// 读取记录 — read. 按当前视图可见行顺序分页返回记录 ID、1-based
// 行号、字段值和易读展示值；若无法确认视图顺序会明确警告。
async function feishu_base_list_records(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'offset', 'limit'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('offset' in rawInput) ||
         (Number.isInteger(rawInput['offset']) && rawInput['offset'] >= 0 &&
          rawInput['offset'] <= 1000000)) &&
        (!('limit' in rawInput) ||
         (Number.isInteger(rawInput['limit']) && rawInput['limit'] >= 1 &&
          rawInput['limit'] <= 200))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    const tableRecordIds =
        asIds(table.getRecordIds?.() || Object.keys(table.records || {})) || [];
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const loadedRecordIds = orderedRecordIds || tableRecordIds;
    const visibleFieldIds = orderedFieldIds ||
        fields.map((field) => String(field.id || '')).filter(Boolean);
    const recordOrder = orderedRecordIds ? 'view_display' : 'table_storage';
    const fieldOrder = orderedFieldIds ? 'view_display' : 'table_storage';
    const tableTotalRecords = Number(
        table.getAllRecordCount?.(true) ?? table.getRecordCount?.() ??
        table.recordsNum ?? tableRecordIds.length);
    const visibleRecordCount =
        Number(view?.getVisibleRecordsCount?.() ?? loadedRecordIds.length);
    const orderWarnings = [
      ...(recordOrder === 'view_display' ?
              [] :
              [
                '页面运行时未提供视图可见行顺序；记录按底层存储顺序返回，不能用于 A1/B4 等位置引用。'
              ]),
      ...(fieldOrder === 'view_display' ?
              [] :
              [
                '页面运行时未提供视图可见列顺序；字段顺序不能用于 A1/B4 等位置引用。'
              ])
    ];
    const displayValue = (field, value) => {
      if (value === null || value === undefined)
        return null;
      const ui = String(field.fieldUIType || '');
      if (Array.isArray(value) &&
          value.every(
              (entry) => entry && typeof entry === 'object' && 'text' in entry))
        return value.map((entry) => entry.text).join('');
      if (ui === 'SingleSelect' || ui === 'MultiSelect') {
        const ids = Array.isArray(value) ? value : [value];
        const names = ids.map((entry) => {
          const id = typeof entry === 'object' && entry ? entry.id : entry;
          return field.property?.options?.find((option) => option.id === id)
                     ?.name ||
              id;
        });
        return ui === 'SingleSelect' ? cleanText(names[0]) :
                                       names.map(cleanText);
      }
      if (ui === 'DateTime' && typeof value === 'number')
        return new Date(value).toISOString();
      return safeJson(value);
    };
    {
      const offset = Math.max(0, Number(input.offset ?? 0));
      const limit = Math.min(200, Math.max(1, Number(input.limit ?? 50)));
      const ids = loadedRecordIds.slice(offset, offset + limit);
      const items = ids.map((recordId, index) => {
        const recordFields = {};
        for (const field of fields) {
          let value = null;
          try {
            value = table.getCellValue?.(recordId, field.id, false);
          } catch {
            value = table.getOriginalCellValue?.(recordId, field.id);
          }
          recordFields[field.id] = {
            name: cleanText(field.name),
            value: safeJson(value),
            displayValue: displayValue(field, value)
          };
        }
        return {rowIndex: offset + index + 1, recordId, fields: recordFields};
      });
      const nextOffset = offset + ids.length;
      return {
        data: {
          items,
          order: recordOrder,
          fieldOrder,
          visibleFieldIds,
          offset,
          limit,
          nextOffset: nextOffset < loadedRecordIds.length ? nextOffset : null,
          loadedCount: loadedRecordIds.length,
          totalCount: visibleRecordCount,
          tableTotalCount: tableTotalRecords,
          truncated: nextOffset < visibleRecordCount
        },
        warnings: [
          ...orderWarnings,
          ...(loadedRecordIds.length < visibleRecordCount ?
                  ['只返回当前页面已加载的可见记录，不能据此判断完整视图。'] :
                  [])
        ]
      };
    }
  }
}


// 校验记录摘要 — read.
// 在页面内按唯一键比较预期记录与当前可见记录，只返回数量、缺失项、多余项和字段差异摘要。
async function feishu_base_verify_records(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'keyField' in rawInput &&
        'expectedRecords' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'keyField', 'expectedRecords',
                    'maxDiffs']
                       .includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('keyField' in rawInput) ||
         (typeof rawInput['keyField'] === 'string' &&
          [...rawInput['keyField']].length >= 1 &&
          [...rawInput['keyField']].length <= 128)) &&
        (!('expectedRecords' in rawInput) ||
         (Array.isArray(rawInput['expectedRecords']) &&
          rawInput['expectedRecords'].length >= 1 &&
          rawInput['expectedRecords'].length <= 200 &&
          rawInput['expectedRecords'].every(
              item => typeof item === 'object' && item !== null &&
                  !Array.isArray(item) && 'fields' in item &&
                  Object.keys(item).every(key => ['fields'].includes(key)) &&
                  (!('fields' in item) ||
                   (typeof item['fields'] === 'object' &&
                    item['fields'] !== null && !Array.isArray(item['fields']) &&
                    Object.keys(item['fields']).length >= 1))))) &&
        (!('maxDiffs' in rawInput) ||
         (Number.isInteger(rawInput['maxDiffs']) && rawInput['maxDiffs'] >= 0 &&
          rawInput['maxDiffs'] <= 100))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    const tableRecordIds =
        asIds(table.getRecordIds?.() || Object.keys(table.records || {})) || [];
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const loadedRecordIds = orderedRecordIds || tableRecordIds;
    const visibleRecordCount =
        Number(view?.getVisibleRecordsCount?.() ?? loadedRecordIds.length);
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const displayValue = (field, value) => {
      if (value === null || value === undefined)
        return null;
      const ui = String(field.fieldUIType || '');
      if (Array.isArray(value) &&
          value.every(
              (entry) => entry && typeof entry === 'object' && 'text' in entry))
        return value.map((entry) => entry.text).join('');
      if (ui === 'SingleSelect' || ui === 'MultiSelect') {
        const ids = Array.isArray(value) ? value : [value];
        const names = ids.map((entry) => {
          const id = typeof entry === 'object' && entry ? entry.id : entry;
          return field.property?.options?.find((option) => option.id === id)
                     ?.name ||
              id;
        });
        return ui === 'SingleSelect' ? cleanText(names[0]) :
                                       names.map(cleanText);
      }
      if (ui === 'DateTime' && typeof value === 'number')
        return new Date(value).toISOString();
      return safeJson(value);
    };
    {
      const keyField = fieldByInputKey(cleanText(input.keyField));
      const expectedRecords =
          Array.isArray(input.expectedRecords) ? input.expectedRecords : [];
      const maxDiffs = Math.min(100, Math.max(0, Number(input.maxDiffs ?? 20)));
      const normalizeComparable = (field, value, fromPage) => {
        const displayed = fromPage ? displayValue(field, value) : value;
        if (displayed === null || displayed === undefined)
          return String(field.fieldUIType || '') === 'Text' ? '' : null;
        if (typeof displayed === 'string')
          return cleanText(displayed);
        if (Array.isArray(displayed))
          return displayed.map(
              (entry) => typeof entry === 'string' ? cleanText(entry) :
                                                     safeJson(entry));
        return safeJson(displayed);
      };
      const comparableKey = (value) => JSON.stringify(value);
      const expectedByKey = new Map();
      for (const record of expectedRecords) {
        if (!record?.fields || typeof record.fields !== 'object' ||
            Array.isArray(record.fields))
          throw new Error(
              'VALIDATION_ERROR: expectedRecords[].fields 必须是对象。');
        const rawKeyEntry =
            Object.entries(record.fields)
                .find(
                    ([name]) =>
                        fieldByInputKey(cleanText(name)).id === keyField.id);
        if (!rawKeyEntry)
          throw new Error(`VALIDATION_ERROR: 每条预期记录都必须包含唯一键字段“${
              cleanText(keyField.name)}”。`);
        const key = normalizeComparable(keyField, rawKeyEntry[1], false);
        const encodedKey = comparableKey(key);
        if (expectedByKey.has(encodedKey))
          throw new Error(
              `VALIDATION_ERROR: 预期记录中的唯一键重复：${String(key)}。`);
        expectedByKey.set(encodedKey, {
          key,
          fields: Object.entries(record.fields).map(([name, value]) => {
            const field = fieldByInputKey(cleanText(name));
            return {field, expected: normalizeComparable(field, value, false)};
          })
        });
      }
      const actualByKey = new Map();
      const duplicateActualKeys = [];
      for (const recordId of loadedRecordIds) {
        let rawKey = null;
        try {
          rawKey = table.getCellValue?.(recordId, keyField.id, false);
        } catch {
          rawKey = table.getOriginalCellValue?.(recordId, keyField.id);
        }
        const key = normalizeComparable(keyField, rawKey, true);
        const encodedKey = comparableKey(key);
        if (actualByKey.has(encodedKey))
          duplicateActualKeys.push(key);
        else
          actualByKey.set(encodedKey, {key, recordId});
      }
      const missingKeys = [];
      const mismatches = [];
      let matchedCount = 0;
      for (const [encodedKey, expectedRecord] of expectedByKey) {
        const actualRecord = actualByKey.get(encodedKey);
        if (!actualRecord) {
          missingKeys.push(expectedRecord.key);
          continue;
        }
        let recordMatches = true;
        for (const {field, expected} of expectedRecord.fields) {
          let rawActual = null;
          try {
            rawActual =
                table.getCellValue?.(actualRecord.recordId, field.id, false);
          } catch {
            rawActual =
                table.getOriginalCellValue?.(actualRecord.recordId, field.id);
          }
          const actual = normalizeComparable(field, rawActual, true);
          if (comparableKey(actual) !== comparableKey(expected)) {
            recordMatches = false;
            mismatches.push({
              key: expectedRecord.key,
              recordId: actualRecord.recordId,
              fieldId: String(field.id),
              fieldName: cleanText(field.name),
              expected,
              actual
            });
          }
        }
        if (recordMatches)
          matchedCount++;
      }
      const unexpectedKeys = [...actualByKey.entries()]
                                 .filter(([key]) => !expectedByKey.has(key))
                                 .map(([, record]) => record.key);
      const diffCount = missingKeys.length + unexpectedKeys.length +
          mismatches.length + duplicateActualKeys.length;
      let remainingDiffs = maxDiffs;
      const compact = (items) => {
        const selected = items.slice(0, remainingDiffs);
        remainingDiffs -= selected.length;
        return selected;
      };
      const compactMissingKeys = compact(missingKeys);
      const compactUnexpectedKeys = compact(unexpectedKeys);
      const compactDuplicateActualKeys = compact(duplicateActualKeys);
      const compactMismatches = compact(mismatches);
      return {
        data: {
          matches:
              diffCount === 0 && loadedRecordIds.length === visibleRecordCount,
          keyField: {id: String(keyField.id), name: cleanText(keyField.name)},
          expectedCount: expectedRecords.length,
          actualLoadedCount: loadedRecordIds.length,
          actualVisibleCount: visibleRecordCount,
          matchedCount,
          diffCount,
          missingKeys: compactMissingKeys,
          unexpectedKeys: compactUnexpectedKeys,
          duplicateActualKeys: compactDuplicateActualKeys,
          mismatches: compactMismatches,
          returnedDiffCount: maxDiffs - remainingDiffs,
          truncatedDiffs: diffCount > maxDiffs,
          complete: loadedRecordIds.length === visibleRecordCount
        },
        warnings: loadedRecordIds.length < visibleRecordCount ?
            ['页面只加载了部分可见记录；摘要不能证明完整视图一致。'] :
            []
      };
    }
  }
}


// 解析可见区域 — read. 按当前视图可见行列顺序解析 A1、B4 或 A1:C5，返回对应
// recordId、fieldId、值和 1-based 行列号。
async function feishu_base_resolve_range(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'range' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'range'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('range' in rawInput) ||
         (typeof rawInput['range'] === 'string' &&
          [...rawInput['range']].length >= 2 &&
          [...rawInput['range']].length <= 64 &&
          new RegExp('^[A-Za-z]+[1-9][0-9]*(?::[A-Za-z]+[1-9][0-9]*)?$')
              .test(rawInput['range'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    const tableRecordIds =
        asIds(table.getRecordIds?.() || Object.keys(table.records || {})) || [];
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const loadedRecordIds = orderedRecordIds || tableRecordIds;
    const visibleFieldIds = orderedFieldIds ||
        fields.map((field) => String(field.id || '')).filter(Boolean);
    const recordOrder = orderedRecordIds ? 'view_display' : 'table_storage';
    const fieldOrder = orderedFieldIds ? 'view_display' : 'table_storage';
    const visibleRecordCount =
        Number(view?.getVisibleRecordsCount?.() ?? loadedRecordIds.length);
    const displayValue = (field, value) => {
      if (value === null || value === undefined)
        return null;
      const ui = String(field.fieldUIType || '');
      if (Array.isArray(value) &&
          value.every(
              (entry) => entry && typeof entry === 'object' && 'text' in entry))
        return value.map((entry) => entry.text).join('');
      if (ui === 'SingleSelect' || ui === 'MultiSelect') {
        const ids = Array.isArray(value) ? value : [value];
        const names = ids.map((entry) => {
          const id = typeof entry === 'object' && entry ? entry.id : entry;
          return field.property?.options?.find((option) => option.id === id)
                     ?.name ||
              id;
        });
        return ui === 'SingleSelect' ? cleanText(names[0]) :
                                       names.map(cleanText);
      }
      if (ui === 'DateTime' && typeof value === 'number')
        return new Date(value).toISOString();
      return safeJson(value);
    };
    {
      if (recordOrder !== 'view_display' || fieldOrder !== 'view_display')
        throw new Error(
            'CONTENT_UNAVAILABLE: 页面运行时没有提供可靠的视图行列顺序，不能解析 A1/B4 等位置引用。');
      const rawRange = cleanText(input.range).toUpperCase();
      const match =
          rawRange.match(/^([A-Z]+)([1-9]\d*)(?::([A-Z]+)([1-9]\d*))?$/);
      if (!match)
        throw new Error(
            'VALIDATION_ERROR: range 必须是 A1、B4 或 A1:C5 形式。');
      const columnNumber = (letters) => [...letters].reduce(
          (total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0);
      const startColumn = columnNumber(match[1]);
      const startRow = Number(match[2]);
      const endColumn = columnNumber(match[3] || match[1]);
      const endRow = Number(match[4] || match[2]);
      if (endColumn < startColumn || endRow < startRow)
        throw new Error('VALIDATION_ERROR: range 结束位置不能早于开始位置。');
      if (endColumn > visibleFieldIds.length)
        throw new Error(`VALIDATION_ERROR: 当前视图只有 ${
            visibleFieldIds.length} 个可见字段，无法解析第 ${endColumn} 列。`);
      if (endRow > loadedRecordIds.length) {
        const suffix = endRow <= visibleRecordCount ?
            '目标行尚未加载到页面。' :
            `当前视图只有 ${visibleRecordCount} 行。`;
        throw new Error(
            `CONTENT_UNAVAILABLE: 无法解析第 ${endRow} 行；${suffix}`);
      }
      const cellCount = (endColumn - startColumn + 1) * (endRow - startRow + 1);
      if (cellCount > 5000)
        throw new Error(
            'RESULT_TOO_LARGE: 单次解析区域不能超过 5000 个单元格。');
      const columnLetters = (index) => {
        let value = index;
        let result = '';
        while (value > 0) {
          value--;
          result = String.fromCharCode(65 + value % 26) + result;
          value = Math.floor(value / 26);
        }
        return result;
      };
      const cells = [];
      for (let rowIndex = startRow; rowIndex <= endRow; rowIndex++) {
        const recordId = loadedRecordIds[rowIndex - 1];
        for (let columnIndex = startColumn; columnIndex <= endColumn;
             columnIndex++) {
          const fieldId = visibleFieldIds[columnIndex - 1];
          const field = fields.find((entry) => String(entry.id) === fieldId);
          if (!field)
            throw new Error(`SITE_CHANGED: 当前视图字段“${fieldId}”未加载。`);
          let value = null;
          try {
            value = table.getCellValue?.(recordId, fieldId, false);
          } catch {
            value = table.getOriginalCellValue?.(recordId, fieldId);
          }
          cells.push({
            address: `${columnLetters(columnIndex)}${rowIndex}`,
            rowIndex,
            columnIndex,
            recordId,
            fieldId,
            fieldName: cleanText(field.name),
            value: safeJson(value),
            displayValue: displayValue(field, value)
          });
        }
      }
      return {
        data: {
          range: rawRange,
          order: 'view_display',
          tableId,
          viewId,
          rowStart: startRow,
          rowEnd: endRow,
          columnStart: startColumn,
          columnEnd: endColumn,
          recordIds: loadedRecordIds.slice(startRow - 1, endRow),
          fieldIds: visibleFieldIds.slice(startColumn - 1, endColumn),
          cells
        },
        warnings: []
      };
    }
  }
}


// 新增记录 — write. 向当前数据表批量新增记录；字段可用精确字段名或字段
// ID，单次最多 200 条。
async function feishu_base_add_records(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'records' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'records'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('records' in rawInput) ||
         (Array.isArray(rawInput['records']) &&
          rawInput['records'].length >= 1 &&
          rawInput['records'].length <= 200 &&
          rawInput['records'].every(
              item => typeof item === 'object' && item !== null &&
                  !Array.isArray(item) && 'fields' in item &&
                  Object.keys(item).every(key => ['fields'].includes(key)) &&
                  (!('fields' in item) ||
                   (typeof item['fields'] === 'object' &&
                    item['fields'] !== null && !Array.isArray(item['fields']) &&
                    Object.keys(item['fields']).length >= 1)))))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const inputHint = (field) => {
      const ui = String(field.fieldUIType || '');
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        return 'string';
      if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        return 'number';
      if (ui === 'Checkbox')
        return 'boolean';
      if (ui === 'DateTime')
        return 'YYYY-MM-DD HH:mm:ss、ISO 8601 或毫秒时间戳';
      if (ui === 'SingleSelect')
        return '选项名或 option id';
      if (ui === 'MultiSelect')
        return '选项名或 option id 数组';
      if (ui === 'Url')
        return 'URL 字符串';
      if (/User|GroupChat/.test(ui))
        return '页面原生用户/群单元格值，或 ID 数组（以页面校验为准）';
      if (/Link/.test(ui))
        return '关联记录 ID 数组（以页面校验为准）';
      return '页面原生 CellValue；工具会调用飞书字段模型校验';
    };
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const valid = (field, value) => {
      try {
        return field.validate?.(value) === true;
      } catch {
        return false;
      }
    };
    const selectOptionIds = (field, value) => {
      const values = Array.isArray(value) ? value : [value];
      const options =
          Array.isArray(field.property?.options) ? field.property.options : [];
      return values.map((entry) => {
        const raw = String(entry);
        const option = options.find(
            (candidate) =>
                candidate.id === raw || cleanText(candidate.name) === raw);
        if (!option)
          throw new Error(`VALIDATION_ERROR: 字段“${
              cleanText(field.name)}”没有选项“${raw}”。`);
        return option.id;
      });
    };
    const convertValue = (field, inputValue) => {
      if (inputValue === null)
        throw new Error(
            'VALIDATION_ERROR: null 不作为写入值；清空已有单元格请调用 feishu_base_clear_cells，新增记录中的空字段请直接省略。');
      if (valid(field, inputValue))
        return inputValue;
      const ui = String(field.fieldUIType || '');
      const candidates = [];
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        candidates.push(
            [{type: 'text', text: String(inputValue)}],
            [{type: 'Text', text: String(inputValue)}], String(inputValue));
      else if (ui === 'Url')
        candidates.push(
            String(inputValue),
            [{type: 'url', text: String(inputValue), link: String(inputValue)}],
            [
              {type: 'text', text: String(inputValue), link: String(inputValue)}
            ]);
      else if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        candidates.push(
            typeof inputValue === 'number' ? inputValue : Number(inputValue));
      else if (ui === 'Checkbox')
        candidates.push(inputValue === true || inputValue === 'true');
      else if (ui === 'DateTime') {
        const millis = typeof inputValue === 'number' ?
            inputValue :
            Date.parse(String(inputValue).replace(' ', 'T'));
        if (Number.isFinite(millis))
          candidates.push(millis);
      } else if (ui === 'SingleSelect' || ui === 'MultiSelect') {
        const ids = selectOptionIds(field, inputValue);
        candidates.push(
            ui === 'SingleSelect' ? ids[0] : ids,
            ui === 'SingleSelect' ? {id: ids[0]} : ids.map((id) => ({id})));
      } else if (/User|GroupChat|Link/.test(ui)) {
        const values = Array.isArray(inputValue) ? inputValue : [inputValue];
        candidates.push(
            values,
            values.map(
                (entry) => typeof entry === 'object' && entry ?
                    entry :
                    ({id: String(entry)})),
            values.map(String));
      }
      const converted = candidates.find((candidate) => valid(field, candidate));
      if (converted === undefined)
        throw new Error(`VALIDATION_ERROR: 字段“${
            cleanText(field.name)}”不接受该值；需要 ${inputHint(field)}。`);
      return converted;
    };
    const buildCellData = (rawFields) => {
      if (!rawFields || typeof rawFields !== 'object' ||
          Array.isArray(rawFields))
        throw new Error(
            'VALIDATION_ERROR: fields 必须是字段名/字段 ID 到值的对象。');
      const cells = {};
      for (const [key, value] of Object.entries(rawFields)) {
        if (key === '__proto__' || key === 'prototype' || key === 'constructor')
          throw new Error('VALIDATION_ERROR: fields 包含不允许的键。');
        const field = fieldByInputKey(key);
        if (!fieldWritable(field))
          throw new Error(
              `VALIDATION_ERROR: 字段“${cleanText(field.name)}”不可直接写入。`);
        if (cells[field.id])
          throw new Error(
              `VALIDATION_ERROR: 字段“${cleanText(field.name)}”被重复指定。`);
        cells[field.id] = {type: field.type, value: convertValue(field, value)};
      }
      return cells;
    };
    {
      const records = Array.isArray(input.records) ? input.records : [];
      const recordIds = records.map(
          () => String(table.getNewRecordId?.() || crypto.randomUUID()));
      const recordMap = {};
      records.forEach((record, index) => {
        recordMap[recordIds[index]] = buildCellData(record.fields);
      });
      const result = store.commandManager.execute({
        cmd: 'ExtendAddRecords',
        tableId,
        viewId,
        count: recordIds.length,
        recordIds,
        records: recordMap,
        from: 'webmcp',
        throwCellOversizeError: true
      });
      if (!result || result.result !== 2)
        return {
          data: {
            reason: result?.reason ?? null,
            failInfo: safeJson(result?.failInfo)
          },
          error: {
            code: 'PERMISSION_DENIED',
            message:
                '飞书页面拒绝新增记录；请确认当前表权限、字段值和页面状态。',
            recoverable: true
          }
        };
      return {
        data: {createdCount: recordIds.length, recordIds, tableId, viewId},
        warnings: []
      };
    }
  }
}


// 更新记录 — write. 按 recordId
// 批量更新当前数据表记录；字段可用精确字段名或字段 ID，单次最多 200
// 条；清空单元格必须使用 feishu_base_clear_cells，不要传 null。
async function feishu_base_update_records(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'records' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'records'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('records' in rawInput) ||
         (Array.isArray(rawInput['records']) &&
          rawInput['records'].length >= 1 &&
          rawInput['records'].length <= 200 &&
          rawInput['records'].every(
              item => typeof item === 'object' && item !== null &&
                  !Array.isArray(item) && 'recordId' in item &&
                  'fields' in item &&
                  Object.keys(item).every(
                      key => ['recordId', 'fields'].includes(key)) &&
                  (!('recordId' in item) ||
                   (typeof item['recordId'] === 'string' &&
                    [...item['recordId']].length >= 1 &&
                    [...item['recordId']].length <= 128)) &&
                  (!('fields' in item) ||
                   (typeof item['fields'] === 'object' &&
                    item['fields'] !== null && !Array.isArray(item['fields']) &&
                    Object.keys(item['fields']).length >= 1)))))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    const tableRecordIds =
        asIds(table.getRecordIds?.() || Object.keys(table.records || {})) || [];
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const inputHint = (field) => {
      const ui = String(field.fieldUIType || '');
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        return 'string';
      if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        return 'number';
      if (ui === 'Checkbox')
        return 'boolean';
      if (ui === 'DateTime')
        return 'YYYY-MM-DD HH:mm:ss、ISO 8601 或毫秒时间戳';
      if (ui === 'SingleSelect')
        return '选项名或 option id';
      if (ui === 'MultiSelect')
        return '选项名或 option id 数组';
      if (ui === 'Url')
        return 'URL 字符串';
      if (/User|GroupChat/.test(ui))
        return '页面原生用户/群单元格值，或 ID 数组（以页面校验为准）';
      if (/Link/.test(ui))
        return '关联记录 ID 数组（以页面校验为准）';
      return '页面原生 CellValue；工具会调用飞书字段模型校验';
    };
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const valid = (field, value) => {
      try {
        return field.validate?.(value) === true;
      } catch {
        return false;
      }
    };
    const selectOptionIds = (field, value) => {
      const values = Array.isArray(value) ? value : [value];
      const options =
          Array.isArray(field.property?.options) ? field.property.options : [];
      return values.map((entry) => {
        const raw = String(entry);
        const option = options.find(
            (candidate) =>
                candidate.id === raw || cleanText(candidate.name) === raw);
        if (!option)
          throw new Error(`VALIDATION_ERROR: 字段“${
              cleanText(field.name)}”没有选项“${raw}”。`);
        return option.id;
      });
    };
    const convertValue = (field, inputValue) => {
      if (inputValue === null)
        throw new Error(
            'VALIDATION_ERROR: null 不作为写入值；清空已有单元格请调用 feishu_base_clear_cells，新增记录中的空字段请直接省略。');
      if (valid(field, inputValue))
        return inputValue;
      const ui = String(field.fieldUIType || '');
      const candidates = [];
      if (/^(Text|Email|Phone|Barcode)$/.test(ui))
        candidates.push(
            [{type: 'text', text: String(inputValue)}],
            [{type: 'Text', text: String(inputValue)}], String(inputValue));
      else if (ui === 'Url')
        candidates.push(
            String(inputValue),
            [{type: 'url', text: String(inputValue), link: String(inputValue)}],
            [
              {type: 'text', text: String(inputValue), link: String(inputValue)}
            ]);
      else if (/^(Number|Currency|Progress|Rating)$/.test(ui))
        candidates.push(
            typeof inputValue === 'number' ? inputValue : Number(inputValue));
      else if (ui === 'Checkbox')
        candidates.push(inputValue === true || inputValue === 'true');
      else if (ui === 'DateTime') {
        const millis = typeof inputValue === 'number' ?
            inputValue :
            Date.parse(String(inputValue).replace(' ', 'T'));
        if (Number.isFinite(millis))
          candidates.push(millis);
      } else if (ui === 'SingleSelect' || ui === 'MultiSelect') {
        const ids = selectOptionIds(field, inputValue);
        candidates.push(
            ui === 'SingleSelect' ? ids[0] : ids,
            ui === 'SingleSelect' ? {id: ids[0]} : ids.map((id) => ({id})));
      } else if (/User|GroupChat|Link/.test(ui)) {
        const values = Array.isArray(inputValue) ? inputValue : [inputValue];
        candidates.push(
            values,
            values.map(
                (entry) => typeof entry === 'object' && entry ?
                    entry :
                    ({id: String(entry)})),
            values.map(String));
      }
      const converted = candidates.find((candidate) => valid(field, candidate));
      if (converted === undefined)
        throw new Error(`VALIDATION_ERROR: 字段“${
            cleanText(field.name)}”不接受该值；需要 ${inputHint(field)}。`);
      return converted;
    };
    const buildCellData = (rawFields) => {
      if (!rawFields || typeof rawFields !== 'object' ||
          Array.isArray(rawFields))
        throw new Error(
            'VALIDATION_ERROR: fields 必须是字段名/字段 ID 到值的对象。');
      const cells = {};
      for (const [key, value] of Object.entries(rawFields)) {
        if (key === '__proto__' || key === 'prototype' || key === 'constructor')
          throw new Error('VALIDATION_ERROR: fields 包含不允许的键。');
        const field = fieldByInputKey(key);
        if (!fieldWritable(field))
          throw new Error(
              `VALIDATION_ERROR: 字段“${cleanText(field.name)}”不可直接写入。`);
        if (cells[field.id])
          throw new Error(
              `VALIDATION_ERROR: 字段“${cleanText(field.name)}”被重复指定。`);
        cells[field.id] = {type: field.type, value: convertValue(field, value)};
      }
      return cells;
    };
    {
      const records = Array.isArray(input.records) ? input.records : [];
      const knownIds = new Set(tableRecordIds);
      const updates = {};
      for (const record of records) {
        if (!knownIds.has(record.recordId) &&
            !table.hasRecord?.(record.recordId))
          throw new Error(
              `VALIDATION_ERROR: 当前表中找不到记录“${record.recordId}”。`);
        updates[record.recordId] = buildCellData(record.fields);
      }
      const result = store.commandManager.execute(
          {cmd: 'SetRecords', tableId, viewId, data: updates});
      if (!result || (result.result !== 2 && result.result !== 0))
        return {
          data: {
            reason: result?.reason ?? null,
            failInfo: safeJson(result?.failInfo)
          },
          error: {
            code: 'PERMISSION_DENIED',
            message:
                '飞书页面拒绝更新记录；请确认当前表权限、字段值和页面状态。',
            recoverable: true
          }
        };
      const noChanges = result.result === 0;
      return {
        data: {
          requestedCount: records.length,
          updatedCount: noChanges ? 0 : records.length,
          recordIds: records.map(({recordId}) => recordId),
          noChanges,
          failInfo: safeJson(result?.failInfo),
          tableId,
          viewId
        },
        warnings: []
      };
    }
  }
}


// 清空单元格 — write. 按 recordId 和字段
// ID/精确名称清空单元格，并在返回前验证页面模型中的值确已为空；单次最多 200
// 个。
async function feishu_base_clear_cells(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'cells' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'cells'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('cells' in rawInput) ||
         (Array.isArray(rawInput['cells']) && rawInput['cells'].length >= 1 &&
          rawInput['cells'].length <= 200 &&
          rawInput['cells'].every(
              item => typeof item === 'object' && item !== null &&
                  !Array.isArray(item) && 'recordId' in item &&
                  'fieldId' in item &&
                  Object.keys(item).every(
                      key => ['recordId', 'fieldId'].includes(key)) &&
                  (!('recordId' in item) ||
                   (typeof item['recordId'] === 'string' &&
                    [...item['recordId']].length >= 1 &&
                    [...item['recordId']].length <= 128)) &&
                  (!('fieldId' in item) ||
                   (typeof item['fieldId'] === 'string' &&
                    [...item['fieldId']].length >= 1 &&
                    [...item['fieldId']].length <= 128)))))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    const tableRecordIds =
        asIds(table.getRecordIds?.() || Object.keys(table.records || {})) || [];
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const readOnlyUiTypes = new Set([
      'Formula', 'Lookup', 'AutoNumber', 'CreatedTime', 'ModifiedTime',
      'CreatedUser', 'ModifiedUser', 'Attachment', 'VirtualTrigger'
    ]);
    const fieldWritable = (field) => {
      if (readOnlyUiTypes.has(String(field.fieldUIType || '')))
        return false;
      if (field.allowedEditModes?.manual === false)
        return false;
      return true;
    };
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const isCellEmpty = (field, value) => {
      if (value === null || value === undefined ||
          (Array.isArray(value) && value.length === 0))
        return true;
      try {
        return field.isEmptyCellValue?.(value) === true;
      } catch {
        return false;
      }
    };
    {
      const requested = Array.isArray(input.cells) ? input.cells : [];
      const knownIds = new Set(tableRecordIds);
      const unique = new Map();
      const updates = {};
      for (const target of requested) {
        if (!knownIds.has(target.recordId) &&
            !table.hasRecord?.(target.recordId))
          throw new Error(
              `VALIDATION_ERROR: 当前表中找不到记录“${target.recordId}”。`);
        const field = fieldByInputKey(cleanText(target.fieldId));
        if (!fieldWritable(field))
          throw new Error(
              `VALIDATION_ERROR: 字段“${cleanText(field.name)}”不可直接清空。`);
        const key = `${target.recordId}\u0000${field.id}`;
        if (unique.has(key))
          continue;
        let before = null;
        try {
          before = table.getCellValue?.(target.recordId, field.id, false);
        } catch {
          before = table.getOriginalCellValue?.(target.recordId, field.id);
        }
        unique.set(key, {
          recordId: target.recordId,
          field,
          alreadyEmpty: isCellEmpty(field, before)
        });
        if (!isCellEmpty(field, before)) {
          updates[target.recordId] ||= {};
          updates[target.recordId][field.id] = {type: field.type, value: null};
        }
      }
      const targetsToClear =
          [...unique.values()].filter(({alreadyEmpty}) => !alreadyEmpty);
      let result = {result: 0, data: {}};
      if (Object.keys(updates).length)
        result = store.commandManager.execute(
            {cmd: 'SetRecords', tableId, viewId, data: updates});
      if (!result || (result.result !== 2 && result.result !== 0))
        return {
          data: {
            reason: result?.reason ?? null,
            failInfo: safeJson(result?.failInfo)
          },
          error: {
            code: 'PERMISSION_DENIED',
            message: '飞书页面拒绝清空单元格。',
            recoverable: true
          }
        };
      const uncleared = targetsToClear.filter(({recordId, field}) => {
        let current = null;
        try {
          current = table.getCellValue?.(recordId, field.id, false);
        } catch {
          current = table.getOriginalCellValue?.(recordId, field.id);
        }
        return !isCellEmpty(field, current);
      });
      if (uncleared.length)
        return {
          data: {
            uncleared: uncleared.map(({recordId, field}) => ({
                                       recordId,
                                       fieldId: field.id,
                                       fieldName: cleanText(field.name)
                                     })),
            failInfo: safeJson(result?.failInfo)
          },
          error: {
            code: 'SITE_CHANGED',
            message: '飞书返回了清空结果，但页面模型中的目标单元格仍非空。',
            recoverable: true
          }
        };
      return {
        data: {
          requestedCount: requested.length,
          uniqueCount: unique.size,
          clearedCount: targetsToClear.length,
          alreadyEmptyCount: [...unique.values()]
                                 .filter(({alreadyEmpty}) => alreadyEmpty)
                                 .length,
          cells: [...unique.values()].map(({recordId, field}) => ({
                                            recordId,
                                            fieldId: field.id,
                                            fieldName: cleanText(field.name)
                                          })),
          tableId,
          viewId
        },
        warnings: []
      };
    }
  }
}


// 删除记录 — write. 按 recordId 批量删除记录；不可逆，单次最多 200 条且必须传
// confirm=true。
async function feishu_base_delete_records(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'recordIds' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'recordIds', 'confirm'].includes(
                key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('recordIds' in rawInput) ||
         (Array.isArray(rawInput['recordIds']) &&
          rawInput['recordIds'].length >= 1 &&
          rawInput['recordIds'].length <= 200 &&
          rawInput['recordIds'].every(
              item => typeof item === 'string' && [...item].length >= 1 &&
                  [...item].length <= 128))) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      if (input.confirm !== true)
        throw new Error('VALIDATION_ERROR: 删除记录必须传 confirm=true。');
      const recordIds =
          Array.isArray(input.recordIds) ? input.recordIds.map(String) : [];
      const uniqueIds = [...new Set(recordIds)];
      for (const recordId of uniqueIds)
        if (!table.hasRecord?.(recordId))
          throw new Error(
              `VALIDATION_ERROR: 当前表中找不到记录“${recordId}”。`);
      const cmd = table.isRankType &&
              store.commandManager.hasCommand?.('DeleteRecordsV2') !== false ?
          'DeleteRecordsV2' :
          'DeleteRecords';
      const result = store.commandManager.execute(
          {cmd, tableId, viewId, recordIds: uniqueIds, from: 'webmcp'});
      if (!commandOk(result))
        return commandError('飞书页面拒绝删除记录。', result);
      return {
        data: {
          deletedCount: uniqueIds.length,
          recordIds: uniqueIds,
          tableId,
          viewId
        },
        warnings: []
      };
    }
  }
}


// 列出视图 — read.
// 列出指定数据表的视图及其类型、筛选、排序、分组和可见字段配置。
async function feishu_base_list_views(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => ['tableId'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeTable = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      active: String(entry.id || '') === activeTableId,
      fieldCount: Number(
          entry.getFieldCount?.() ?? entry.getAllFields?.()?.length ??
          entry.fields?.length ?? 0),
      viewCount: Number(entry.getViews?.()?.length ?? entry.views?.length ?? 0),
      recordCount: Number(
          entry.getAllRecordCount?.(true) ?? entry.getRecordCount?.() ??
          entry.recordsNum ?? 0)
    });
    const summarizeView = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      type: entry.type ?? null,
      typeName: {
        1: 'grid',
        2: 'kanban',
        3: 'form',
        4: 'gallery',
        5: 'gantt',
        6: 'hierarchy',
        7: 'calendar',
        8: 'query'
      }[Number(entry.type)] ||
          'unknown',
      property: safeJson(
          entry.deepCloneProperty?.() || entry.property ||
          entry.toJSON?.()?.property || null)
    });
    return {
      data:
          {table: summarizeTable(table), items: tableViews.map(summarizeView)},
      warnings: []
    };
  }
}


// 创建视图 — write. 创建表格、看板、画册、甘特图或日历视图。
async function feishu_base_create_view(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'name' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'name', 'type'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('name' in rawInput) ||
         (typeof rawInput['name'] === 'string' &&
          [...rawInput['name']].length >= 1 &&
          [...rawInput['name']].length <= 100)) &&
        (!('type' in rawInput) || (typeof rawInput['type'] === 'string' && [
          'grid', 'kanban', 'gallery', 'gantt', 'calendar'
        ].includes(rawInput['type'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeView = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      type: entry.type ?? null,
      typeName: {
        1: 'grid',
        2: 'kanban',
        3: 'form',
        4: 'gallery',
        5: 'gantt',
        6: 'hierarchy',
        7: 'calendar',
        8: 'query'
      }[Number(entry.type)] ||
          'unknown',
      property: safeJson(
          entry.deepCloneProperty?.() || entry.property ||
          entry.toJSON?.()?.property || null)
    });
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      const name = cleanText(input.name);
      if (tableViews.some((entry) => cleanText(entry.name) === name))
        throw new Error(`VALIDATION_ERROR: 视图“${name}”已存在。`);
      const viewTypes = {grid: 1, kanban: 2, gallery: 4, gantt: 5, calendar: 7};
      const requestedType = cleanText(input.type || 'grid');
      const type = viewTypes[requestedType];
      if (!type)
        throw new Error(
            `VALIDATION_ERROR: 暂不支持视图类型“${requestedType}”。`);
      const newViewId = String(
          table.getNewViewId?.() ||
          `vew${crypto.randomUUID().replace(/-/g, '').slice(0, 10)}`);
      const activeViewId = String(view?.id || tableViews[0]?.id || '');
      const result = store.commandManager.execute({
        cmd: 'AddView',
        tableId,
        name,
        type,
        newViewId,
        activeViewId,
        from: 'webmcp'
      });
      if (!commandOk(result))
        return commandError('飞书页面拒绝创建视图。', result);
      const createdId = String(result.data?.viewId || newViewId);
      const created = table.getViewById?.(createdId);
      return {
        data: {
          created: true,
          view: created ? summarizeView(created) :
                          {id: createdId, name, type, typeName: requestedType}
        },
        warnings: []
      };
    }
  }
}


// 重命名视图 — write. 按视图 ID 或精确名称重命名视图。
async function feishu_base_rename_view(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'viewId' in rawInput &&
        'name' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'name'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('name' in rawInput) || (typeof rawInput['name'] === 'string' && [
          ...rawInput['name']
        ].length >= 1 && [...rawInput['name']].length <= 100))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeView = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      type: entry.type ?? null,
      typeName: {
        1: 'grid',
        2: 'kanban',
        3: 'form',
        4: 'gallery',
        5: 'gantt',
        6: 'hierarchy',
        7: 'calendar',
        8: 'query'
      }[Number(entry.type)] ||
          'unknown',
      property: safeJson(
          entry.deepCloneProperty?.() || entry.property ||
          entry.toJSON?.()?.property || null)
    });
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      const targetView = resolveView(input.viewId, false);
      const name = cleanText(input.name);
      if (tableViews.some(
              (entry) =>
                  entry.id !== targetView.id && cleanText(entry.name) === name))
        throw new Error(`VALIDATION_ERROR: 视图“${name}”已存在。`);
      const result = store.commandManager.execute({
        cmd: 'SetView',
        tableId,
        viewId: targetView.id,
        name,
        from: 'webmcp'
      });
      if (!commandOk(result, true))
        return commandError('飞书页面拒绝重命名视图。', result);
      return {
        data: {
          updated: true,
          view: summarizeView(table.getViewById?.(targetView.id) || targetView),
          noChanges: result?.result === 0 || !result
        },
        warnings: []
      };
    }
  }
}


// 配置视图 — write. 配置视图的可见字段、排序、分组或页面原生 filterInfo。
async function feishu_base_update_view(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'viewId' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'visibleFieldIds', 'sort', 'group',
                    'filterInfo']
                       .includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('visibleFieldIds' in rawInput) ||
         (Array.isArray(rawInput['visibleFieldIds']) &&
          rawInput['visibleFieldIds'].length >= 1 &&
          rawInput['visibleFieldIds'].length <= 500 &&
          rawInput['visibleFieldIds'].every(
              item => typeof item === 'string' && [...item].length >= 1 &&
                  [...item].length <= 128))) &&
        (!('sort' in rawInput) ||
         (Array.isArray(rawInput['sort']) && rawInput['sort'].length <= 20 &&
          rawInput['sort'].every(
              item => typeof item === 'object' && item !== null &&
                  !Array.isArray(item) && 'fieldId' in item &&
                  Object.keys(item).every(
                      key => ['fieldId', 'desc'].includes(key)) &&
                  (!('fieldId' in item) ||
                   (typeof item['fieldId'] === 'string' &&
                    [...item['fieldId']].length >= 1 &&
                    [...item['fieldId']].length <= 128)) &&
                  (!('desc' in item) ||
                   (typeof item['desc'] === 'boolean'))))) &&
        (!('group' in rawInput) ||
         (Array.isArray(rawInput['group']) && rawInput['group'].length <= 3 &&
          rawInput['group'].every(
              item => typeof item === 'object' && item !== null &&
                  !Array.isArray(item) && 'fieldId' in item &&
                  Object.keys(item).every(
                      key => ['fieldId', 'desc'].includes(key)) &&
                  (!('fieldId' in item) ||
                   (typeof item['fieldId'] === 'string' &&
                    [...item['fieldId']].length >= 1 &&
                    [...item['fieldId']].length <= 128)) &&
                  (!('desc' in item) ||
                   (typeof item['desc'] === 'boolean'))))) &&
        (!('filterInfo' in rawInput) ||
         (((typeof rawInput['filterInfo'] === 'object' &&
            rawInput['filterInfo'] !== null &&
            !Array.isArray(rawInput['filterInfo'])) ||
           (rawInput['filterInfo'] === null))))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const visibleFieldIds = orderedFieldIds ||
        fields.map((field) => String(field.id || '')).filter(Boolean);
    const summarizeView = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      type: entry.type ?? null,
      typeName: {
        1: 'grid',
        2: 'kanban',
        3: 'form',
        4: 'gallery',
        5: 'gantt',
        6: 'hierarchy',
        7: 'calendar',
        8: 'query'
      }[Number(entry.type)] ||
          'unknown',
      property: safeJson(
          entry.deepCloneProperty?.() || entry.property ||
          entry.toJSON?.()?.property || null)
    });
    const fieldByInputKey = (key) => {
      const byId = fields.find((field) => field.id === key);
      if (byId)
        return byId;
      const byName = fields.filter((field) => cleanText(field.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 字段名“${key}”不唯一，请改用字段 ID。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 字段“${
            key}”不存在；请先调用 feishu_base_get_table_context。`);
      return byName[0];
    };
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      const targetView = resolveView(input.viewId, false);
      const data = {};
      if (Array.isArray(input.visibleFieldIds))
        data.fields = [...new Set(input.visibleFieldIds.map(
            (entry) => fieldByInputKey(cleanText(entry)).id))];
      if (Array.isArray(input.sort))
        data.sortInfo = input.sort.map(
            (entry) => ({
              fieldId: fieldByInputKey(cleanText(entry.fieldId)).id,
              desc: entry.desc === true
            }));
      if (Array.isArray(input.group))
        data.group = input.group.map(
            (entry) => ({
              fieldId: fieldByInputKey(cleanText(entry.fieldId)).id,
              desc: entry.desc === true
            }));
      if ('filterInfo' in input)
        data.filterInfo = safeJson(input.filterInfo);
      if (!Object.keys(data).length)
        throw new Error(
            'VALIDATION_ERROR: 至少提供 visibleFieldIds、sort、group 或 filterInfo 之一。');
      const result = store.commandManager.execute({
        cmd: 'SetViewProperty',
        tableId,
        viewId: targetView.id,
        data,
        from: 'webmcp'
      });
      if (!commandOk(result, true))
        return commandError('飞书页面拒绝更新视图配置。', result);
      return {
        data: {
          updated: true,
          view: summarizeView(table.getViewById?.(targetView.id) || targetView),
          noChanges: result?.result === 0 || !result
        },
        warnings: []
      };
    }
  }
}


// 删除视图 — write. 删除明确指定的视图；不可逆，必须传 confirm=true。
async function feishu_base_delete_view(rawInput = {}) {
  const isFeishuHost = (hostname) =>
      hostname === 'feishu.cn' || hostname.endsWith('.feishu.cn');
  const route = /^\/(base|wiki)\/([A-Za-z0-9_-]+)\/?$/;
  const feishuBaseAdapter = {
    matches: (url) => {
      const match = isFeishuHost(url.hostname) && route.exec(url.pathname);
      if (!match)
        return false;
      return match[1] === 'base' ||
          /^tbl[A-Za-z0-9_-]+$/.test(url.searchParams.get('table') || '');
    }
  };
  const routeUrl = new URL(location.href);
  if (!feishuBaseAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 飞书多维表格 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'viewId' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['tableId', 'viewId', 'confirm'].includes(key)) &&
        (!('tableId' in rawInput) ||
         (typeof rawInput['tableId'] === 'string' &&
          [...rawInput['tableId']].length >= 1 &&
          [...rawInput['tableId']].length <= 128)) &&
        (!('viewId' in rawInput) ||
         (typeof rawInput['viewId'] === 'string' &&
          [...rawInput['viewId']].length >= 1 &&
          [...rawInput['viewId']].length <= 128)) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const store = win.bitableStore;
    if (!store?.modelOperator || !store?.commandManager)
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message: '当前页面尚未加载已登录的飞书多维表格运行时。',
          recoverable: true
        }
      };
    const params = new URL(location.href).searchParams;
    const activeTableId =
        String(store.getActiveTableId?.() || params.get('table') || '');
    const requestedTableId = params.get('table');
    if (requestedTableId && activeTableId && requestedTableId !== activeTableId)
      return {
        data: null,
        error: {
          code: 'STALE_PAGE_CONTEXT',
          message: '页面当前数据表与 URL 不一致，请等待页面加载完成后重试。',
          recoverable: true
        }
      };
    const cleanText = (value) =>
        String(value ?? '').replace(/[\u200B-\u200F\u2060\uFEFF]/g, '').trim();
    const safeJson = (value) => {
      try {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
          if (typeof item === 'string')
            return item.slice(0, 20000);
          if (typeof item === 'bigint')
            return String(item);
          return item;
        }));
      } catch {
        return null;
      }
    };
    const activeTable = activeTableId ?
        store.modelOperator.getTableById?.(activeTableId) :
        null;
    if (!activeTable)
      return {
        data: null,
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前数据表模型尚未加载。',
          recoverable: true
        }
      };
    const modelTables =
        (store.commandManager?._model?.tables ||
         store.modelOperator?.base?.tables || [activeTable]);
    const allTables = [...new Map(modelTables.filter(Boolean).map(
                                      (entry) => [String(entry.id), entry]))
                           .values()];
    const resolveTable = (ref) => {
      const key = cleanText(ref);
      if (!key)
        return activeTable;
      const byId = store.modelOperator.getTableById?.(key) ||
          allTables.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName = allTables.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 数据表名“${key}”不唯一，请改用 tableId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 页面模型中找不到数据表“${
            key}”；请先调用 feishu_base_list_tables。`);
      return byName[0];
    };
    const table = resolveTable(input.tableId);
    const tableId = String(table.id || activeTableId);
    const tableViews = (table.getViews?.() || table.views || []);
    const resolveView = (ref, allowDefault = true) => {
      const requested = cleanText(ref);
      const urlView =
          tableId === activeTableId ? cleanText(params.get('view')) : '';
      const key = requested ||
          (allowDefault ? urlView || String(tableViews[0]?.id || '') : '');
      if (!key)
        return null;
      const byId = table.getViewById?.(key) ||
          tableViews.find((entry) => String(entry.id) === key);
      if (byId)
        return byId;
      const byName =
          tableViews.filter((entry) => cleanText(entry.name) === key);
      if (byName.length > 1)
        throw new Error(
            `VALIDATION_ERROR: 视图名“${key}”不唯一，请改用 viewId。`);
      if (!byName.length)
        throw new Error(`VALIDATION_ERROR: 数据表中找不到视图“${key}”。`);
      return byName[0];
    };
    const view = resolveView(input.viewId);
    const viewId = String(view?.id || '');
    const fields =
        (table.getAllFields?.() || table.getFields?.() ||
         Object.values(table.fields || {}));
    const asIds = (value) =>
        Array.isArray(value) ? value.map(String).filter(Boolean) : null;
    let orderedRecordIds = null;
    let orderedFieldIds = null;
    try {
      orderedRecordIds = asIds(view?.getLoadedVisibleRecords?.());
    } catch {
      orderedRecordIds = null;
    }
    try {
      orderedFieldIds = asIds(view?.getVisibleFields?.());
    } catch {
      orderedFieldIds = null;
    }
    if (!orderedRecordIds && viewId) {
      try {
        orderedRecordIds = asIds(table.getSortedRecordsByView?.(viewId));
      } catch {
        orderedRecordIds = null;
      }
    }
    if (!orderedFieldIds && viewId) {
      try {
        orderedFieldIds = asIds(table.getSortedFieldsByView?.(viewId));
      } catch {
        orderedFieldIds = null;
      }
    }
    const summarizeView = (entry) => ({
      id: String(entry.id || ''),
      name: cleanText(entry.name),
      type: entry.type ?? null,
      typeName: {
        1: 'grid',
        2: 'kanban',
        3: 'form',
        4: 'gallery',
        5: 'gantt',
        6: 'hierarchy',
        7: 'calendar',
        8: 'query'
      }[Number(entry.type)] ||
          'unknown',
      property: safeJson(
          entry.deepCloneProperty?.() || entry.property ||
          entry.toJSON?.()?.property || null)
    });
    const commandOk = (result, allowNoChanges = false) => Boolean(
        result &&
        (result.result === 2 || (allowNoChanges && result.result === 0)));
    const commandError = (message, result) => ({
      data: {
        reason: result?.reason ?? null,
        failInfo: safeJson(result?.failInfo)
      },
      error: {code: 'PERMISSION_DENIED', message, recoverable: true}
    });
    {
      if (input.confirm !== true)
        throw new Error('VALIDATION_ERROR: 删除视图必须传 confirm=true。');
      const targetView = resolveView(input.viewId, false);
      const target = summarizeView(targetView);
      const result = store.commandManager.execute(
          {cmd: 'DeleteView', tableId, viewId: targetView.id, from: 'webmcp'});
      if (!commandOk(result))
        return commandError(
            '飞书页面拒绝删除视图；每张表必须至少保留一个普通视图。', result);
      return {data: {deleted: true, view: target, tableId}, warnings: []};
    }
  }
}
