// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取简历上下文 — read.
// 读取当前简历页的栏目、字段、条目数量、可见值和页面校验错误。
async function bytedance_resume_get_context(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => [].includes(key))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const listIds = {
      '工作经历': 'career_list',
      '教育经历': 'education_list',
      '实习经历': 'internship_list',
      '项目经历': 'project_list',
      '作品': 'works_list',
      '获奖': 'award_list',
      '语言能力': 'language_list',
      '社交账号': 'sns_list'
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const fieldValue = (container, fieldName) => {
      const root = fieldRoot(container, fieldName);
      if (!root)
        return null;
      if (fieldName === 'start_end_time')
        return Array.from(root.querySelectorAll('input'))
            .map((entry) => entry.value);
      const select = root.querySelector('select');
      if (select)
        return cleanText(
            select.selectedOptions[0]?.textContent || select.value);
      const control = textControl(root);
      return control?.value ?? cleanText(root.textContent);
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const repeatSections = Object.entries(listIds).map(([title, listId]) => {
        const module = section(title);
        const items = module ? cards(module).map((card, index) => {
          const fieldNames =
              Array.from(card.querySelectorAll('[data-form-field-name]'))
                  .map((node) => node.dataset.formFieldName)
                  .filter(Boolean);
          return {
            index,
            values: Object.fromEntries(
                [...new Set(fieldNames)]
                    .filter((name) => name !== listId)
                    .map((name) => [name, fieldValue(card, name)]))
          };
        }) :
                               [];
        return {title, listId, count: items.length, items};
      });
      const basic = section('基本信息');
      const work = section('工作经历');
      return {
        data: {
          page: {
            title: document.title,
            path: location.pathname,
            saveAvailable:
                Boolean(document.querySelector('[data-test="saveResumeBtn"]'))
          },
          attachment: {
            accepted:
                section('简历')?.querySelector('input[type="file"]')?.accept ||
                '',
            maxBytes: 10 * 1024 * 1024
          },
          basic: {
            name: fieldValue(basic, 'name'),
            mobile: fieldValue(basic, 'mobile'),
            email: fieldValue(basic, 'email'),
            preferredCities: fieldValue(basic, 'preferred_city_list')
          },
          noWorkExperience:
              Boolean(work?.querySelector('input[type="checkbox"]')?.checked),
          repeatSections,
          selfEvaluation:
              fieldValue(section('自我评价') || form, 'self_evaluation'),
          optionHints: {
            degree: [
              '博士', 'MBA', '硕士', '本科', '大专', '高中', '中专', '初中',
              '小学'
            ],
            language: [
              '英语', '法语', '日语', '韩语', '德语', '俄语', '西班牙语',
              '葡萄牙语', '阿拉伯语'
            ],
            proficiency: ['入门', '日常会话', '商务会话', '无障碍沟通', '母语'],
            socialPlatform: [
              '微信', 'QQ', '领英', '脉脉', '微博', 'Github', '知乎', '脸书',
              '推特'
            ]
          },
          validationErrors: formErrors()
        }
      };
    }
  }
}


// 填写基本信息 — write. 填写姓名、国家/地区代码、手机号、邮箱和期望工作地点。
async function bytedance_resume_set_basic_info(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['name', 'countryCode', 'mobile', 'email', 'preferredCities']
                       .includes(key)) &&
        Object.keys(rawInput).length >= 1 &&
        (!('name' in rawInput) ||
         (typeof rawInput['name'] === 'string' &&
          [...rawInput['name']].length >= 1 &&
          [...rawInput['name']].length <= 100)) &&
        (!('countryCode' in rawInput) ||
         (typeof rawInput['countryCode'] === 'string' &&
          [...rawInput['countryCode']].length >= 1 &&
          [...rawInput['countryCode']].length <= 16)) &&
        (!('mobile' in rawInput) ||
         (typeof rawInput['mobile'] === 'string' &&
          [...rawInput['mobile']].length >= 5 &&
          [...rawInput['mobile']].length <= 32)) &&
        (!('email' in rawInput) ||
         (typeof rawInput['email'] === 'string' &&
          [...rawInput['email']].length >= 3 &&
          [...rawInput['email']].length <= 254)) &&
        (!('preferredCities' in rawInput) ||
         (Array.isArray(rawInput['preferredCities']) &&
          rawInput['preferredCities'].length >= 1 &&
          rawInput['preferredCities'].length <= 20 &&
          rawInput['preferredCities'].every(
              item => typeof item === 'string' && [...item].length >= 1 &&
                  [...item].length <= 100)))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const selectOptionNodes = () => Array.from(document.querySelectorAll(
        '[role="option"],.ud__select__dropdown [class*="option"],.ud__select__dropdown li'));
    const setSelectField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      if (!root)
        throw new Error(`SITE_CHANGED: 页面中找不到选择字段“${fieldName}”。`);
      const normalized = cleanText(value);
      const nativeSelect = root.querySelector('select');
      if (nativeSelect) {
        const option =
            Array.from(nativeSelect.options)
                .find(
                    (entry) => cleanText(entry.textContent) === normalized ||
                        entry.value === normalized);
        if (!option)
          throw new Error(
              `VALIDATION_ERROR: 字段“${fieldName}”没有选项“${normalized}”。`);
        nativeSelect.value = option.value;
        nativeSelect.dispatchEvent(new Event('change', {bubbles: true}));
        return cleanText(option.textContent);
      }
      if (cleanText(root.textContent).includes(normalized))
        return normalized;
      const input = root.querySelector('input[type="search"],input');
      const trigger =
          root.querySelector('[class*="select__selector"]') || input;
      if (!input || !trigger)
        throw new Error(`SITE_CHANGED: 选择字段“${fieldName}”缺少可交互控件。`);
      trigger.click();
      setNativeValue(input, normalized);
      await pause(120);
      const candidates = selectOptionNodes().filter((node) => {
        const label = cleanText(node.textContent);
        return label === normalized || label.includes(normalized);
      });
      const option =
          candidates.find((node) => node.getClientRects().length > 0) ||
          candidates[0];
      if (option)
        option.click();
      else {
        input.dispatchEvent(new KeyboardEvent(
            'keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
        input.dispatchEvent(new KeyboardEvent(
            'keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
      }
      await pause(120);
      if (!cleanText(root.textContent).includes(normalized) &&
          cleanText(input.value) !== normalized) {
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”没有可选择的“${
            normalized}”。`);
      }
      return normalized;
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const basic = section('基本信息');
      const values = {};
      if (input.name !== undefined)
        values.name = await setTextField(basic, 'name', input.name);
      if (input.countryCode !== undefined)
        values.countryCode = await setSelectField(
            fieldRoot(basic, 'mobile') || basic, 'mobile', input.countryCode);
      if (input.mobile !== undefined)
        values.mobile = await setTextField(basic, 'mobile', input.mobile);
      if (input.email !== undefined)
        values.email = await setTextField(basic, 'email', input.email);
      if (Array.isArray(input.preferredCities)) {
        values.preferredCities = [];
        for (const city of input.preferredCities)
          values.preferredCities.push(
              await setSelectField(basic, 'preferred_city_list', city));
      }
      return {data: {updated: true, values}, warnings: formErrors(basic)};
    }
  }
}


// 上传简历附件 — write. 将明确提供的 Base64
// 文件设置到简历附件控件；会触发页面上传。
async function bytedance_resume_upload_attachment(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'filename' in rawInput &&
        'mimeType' in rawInput && 'base64' in rawInput &&
        Object.keys(rawInput).every(
            key => ['filename', 'mimeType', 'base64'].includes(key)) &&
        (!('filename' in rawInput) ||
         (typeof rawInput['filename'] === 'string' &&
          [...rawInput['filename']].length >= 1 &&
          [...rawInput['filename']].length <= 255)) &&
        (!('mimeType' in rawInput) ||
         (typeof rawInput['mimeType'] === 'string' &&
          [...rawInput['mimeType']].length >= 1 &&
          [...rawInput['mimeType']].length <= 100)) &&
        (!('base64' in rawInput) || (typeof rawInput['base64'] === 'string' && [
          ...rawInput['base64']
        ].length >= 1 && [...rawInput['base64']].length <= 14000000))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fileFromInput = (input) => {
      const filename = cleanText(input.filename);
      const mimeType = cleanText(input.mimeType);
      const encoded = String(input.base64 || '').replace(/\s+/g, '');
      let binary = '';
      try {
        binary = atob(encoded);
      } catch {
        throw new Error(
            'VALIDATION_ERROR: base64 不是有效的 Base64 文件内容。');
      }
      if (binary.length > 10 * 1024 * 1024)
        throw new Error('RESULT_TOO_LARGE: 附件不能超过 10 MiB。');
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1)
        bytes[index] = binary.charCodeAt(index);
      return new File([bytes], filename, {type: mimeType});
    };
    const setFile = async (container, fileInput) => {
      const control = container.querySelector('input[type="file"]');
      if (!control)
        throw new Error('SITE_CHANGED: 页面中找不到附件控件。');
      const file = fileFromInput(fileInput);
      if (typeof DataTransfer === 'undefined')
        throw new Error('SITE_CHANGED: 当前浏览器不支持安全设置附件。');
      const transfer = new DataTransfer();
      transfer.items.add(file);
      control.files = transfer.files;
      control.dispatchEvent(new Event('input', {bubbles: true}));
      control.dispatchEvent(new Event('change', {bubbles: true}));
      await pause(120);
      return {filename: file.name, mimeType: file.type, size: file.size};
    };
    {
      const resume = section('简历');
      if (!resume)
        throw new Error('SITE_CHANGED: 页面中找不到简历附件栏目。');
      const extension =
          cleanText(input.filename).split('.').pop()?.toLowerCase() || '';
      if (!['pdf', 'doc', 'docx', 'ppt', 'pptx', 'png', 'jpg', 'jpeg', 'html',
            'htm']
               .includes(extension))
        throw new Error('VALIDATION_ERROR: 简历附件格式不受页面支持。');
      return {data: {uploaded: true, file: await setFile(resume, input)}};
    }
  }
}


// 设置无工作经历 — write. 设置或取消“没有工作经历”；取消后可继续填写工作经历。
async function bytedance_resume_set_no_work_experience(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'value' in rawInput &&
        Object.keys(rawInput).every(key => ['value'].includes(key)) &&
        (!('value' in rawInput) || (typeof rawInput['value'] === 'boolean'))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    {
      const work = section('工作经历');
      const checkbox = work?.querySelector('input[type="checkbox"]');
      if (!work || !checkbox)
        throw new Error('SITE_CHANGED: 页面中找不到“没有工作经历”控件。');
      const value = input.value === true;
      if (checkbox.checked !== value) {
        checkbox.click();
        await pause(120);
      }
      if (checkbox.checked !== value)
        throw new Error('VALIDATION_ERROR: 页面拒绝更新“没有工作经历”。');
      return {data: {noWorkExperience: value}};
    }
  }
}


// 填写工作经历 — write. 按 0-based index
// 新增或更新一条工作经历，不删除其他条目。
async function bytedance_resume_upsert_work_experience(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput &&
        'company' in rawInput && 'title' in rawInput &&
        'startDate' in rawInput && 'endDate' in rawInput &&
        'description' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'company', 'title', 'startDate', 'endDate',
                    'description']
                       .includes(key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('company' in rawInput) ||
         (typeof rawInput['company'] === 'string' &&
          [...rawInput['company']].length >= 1 &&
          [...rawInput['company']].length <= 100)) &&
        (!('title' in rawInput) ||
         (typeof rawInput['title'] === 'string' &&
          [...rawInput['title']].length >= 1 &&
          [...rawInput['title']].length <= 100)) &&
        (!('startDate' in rawInput) ||
         (typeof rawInput['startDate'] === 'string' &&
          new RegExp('^\\d{4}-(0[1-9]|1[0-2])$')
              .test(rawInput['startDate']))) &&
        (!('endDate' in rawInput) ||
         (((typeof rawInput['endDate'] === 'string' &&
            new RegExp('^\\d{4}-(0[1-9]|1[0-2])$').test(rawInput['endDate'])) ||
           (typeof rawInput['endDate'] === 'string' &&
            ['present'].includes(rawInput['endDate']))))) &&
        (!('description' in rawInput) ||
         (typeof rawInput['description'] === 'string' &&
          [...rawInput['description']].length >= 1 &&
          [...rawInput['description']].length <= 10000))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const setDateRange = async (container, startValue, endValue) => {
      const root = fieldRoot(container, 'start_end_time');
      const controls = root ? Array.from(root.querySelectorAll('input'))
                                  .filter((entry) => entry.type !== 'search') :
                              [];
      if (controls.length !== 2)
        throw new Error('SITE_CHANGED: 起止时间控件结构已变化。');
      const start = cleanText(startValue);
      const requestedEnd = cleanText(endValue);
      const now = new Date();
      const currentMonth =
          `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      const end = requestedEnd === 'present' ? currentMonth : requestedEnd;
      const apply = () => {
        setNativeValue(controls[1], end);
        setNativeValue(controls[0], start);
        controls.forEach(
            (entry) =>
                entry.dispatchEvent(new FocusEvent('blur', {bubbles: true})));
      };
      apply();
      await pause();
      if (controls[0].value !== start || controls[1].value !== end) {
        apply();
        await pause();
      }
      if (controls[0].value !== start || controls[1].value !== end)
        throw new Error(
            'VALIDATION_ERROR: 页面拒绝了起止月份；请使用 YYYY-MM。');
      return {startDate: start, endDate: end, requestedEndDate: requestedEnd};
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const writeCommonExperience = async (title) => {
      const {card, index} = await ensureCard(title, input.index);
      const written = {};
      written.company = await setTextField(card, 'company', input.company);
      written.title = await setTextField(card, 'title', input.title);
      written.date = await setDateRange(card, input.startDate, input.endDate);
      written.description = await setTextField(card, 'desc', input.description);
      return {
        data: {section: title, index, values: written},
        warnings: input.endDate === 'present' ?
            ['页面没有“至今”字段，已将结束时间写为当前月份。'] :
            []
      };
    };
    return writeCommonExperience('工作经历');
  }
}


// 填写教育经历 — write. 按 0-based index
// 新增或更新一条教育经历，不删除其他条目。
async function bytedance_resume_upsert_education(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput &&
        'school' in rawInput && 'degree' in rawInput &&
        'fieldOfStudy' in rawInput && 'startDate' in rawInput &&
        'endDate' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'school', 'degree', 'fieldOfStudy', 'startDate',
                    'endDate']
                       .includes(key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('school' in rawInput) ||
         (typeof rawInput['school'] === 'string' &&
          [...rawInput['school']].length >= 1 &&
          [...rawInput['school']].length <= 100)) &&
        (!('degree' in rawInput) ||
         (typeof rawInput['degree'] === 'string' &&
          [...rawInput['degree']].length >= 1 &&
          [...rawInput['degree']].length <= 100)) &&
        (!('fieldOfStudy' in rawInput) ||
         (typeof rawInput['fieldOfStudy'] === 'string' &&
          [...rawInput['fieldOfStudy']].length >= 1 &&
          [...rawInput['fieldOfStudy']].length <= 100)) &&
        (!('startDate' in rawInput) ||
         (typeof rawInput['startDate'] === 'string' &&
          new RegExp('^\\d{4}-(0[1-9]|1[0-2])$')
              .test(rawInput['startDate']))) &&
        (!('endDate' in rawInput) ||
         (typeof rawInput['endDate'] === 'string' &&
          new RegExp('^\\d{4}-(0[1-9]|1[0-2])$').test(rawInput['endDate'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const selectOptionNodes = () => Array.from(document.querySelectorAll(
        '[role="option"],.ud__select__dropdown [class*="option"],.ud__select__dropdown li'));
    const setSelectField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      if (!root)
        throw new Error(`SITE_CHANGED: 页面中找不到选择字段“${fieldName}”。`);
      const normalized = cleanText(value);
      const nativeSelect = root.querySelector('select');
      if (nativeSelect) {
        const option =
            Array.from(nativeSelect.options)
                .find(
                    (entry) => cleanText(entry.textContent) === normalized ||
                        entry.value === normalized);
        if (!option)
          throw new Error(
              `VALIDATION_ERROR: 字段“${fieldName}”没有选项“${normalized}”。`);
        nativeSelect.value = option.value;
        nativeSelect.dispatchEvent(new Event('change', {bubbles: true}));
        return cleanText(option.textContent);
      }
      if (cleanText(root.textContent).includes(normalized))
        return normalized;
      const input = root.querySelector('input[type="search"],input');
      const trigger =
          root.querySelector('[class*="select__selector"]') || input;
      if (!input || !trigger)
        throw new Error(`SITE_CHANGED: 选择字段“${fieldName}”缺少可交互控件。`);
      trigger.click();
      setNativeValue(input, normalized);
      await pause(120);
      const candidates = selectOptionNodes().filter((node) => {
        const label = cleanText(node.textContent);
        return label === normalized || label.includes(normalized);
      });
      const option =
          candidates.find((node) => node.getClientRects().length > 0) ||
          candidates[0];
      if (option)
        option.click();
      else {
        input.dispatchEvent(new KeyboardEvent(
            'keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
        input.dispatchEvent(new KeyboardEvent(
            'keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
      }
      await pause(120);
      if (!cleanText(root.textContent).includes(normalized) &&
          cleanText(input.value) !== normalized) {
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”没有可选择的“${
            normalized}”。`);
      }
      return normalized;
    };
    const setDateRange = async (container, startValue, endValue) => {
      const root = fieldRoot(container, 'start_end_time');
      const controls = root ? Array.from(root.querySelectorAll('input'))
                                  .filter((entry) => entry.type !== 'search') :
                              [];
      if (controls.length !== 2)
        throw new Error('SITE_CHANGED: 起止时间控件结构已变化。');
      const start = cleanText(startValue);
      const requestedEnd = cleanText(endValue);
      const now = new Date();
      const currentMonth =
          `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      const end = requestedEnd === 'present' ? currentMonth : requestedEnd;
      const apply = () => {
        setNativeValue(controls[1], end);
        setNativeValue(controls[0], start);
        controls.forEach(
            (entry) =>
                entry.dispatchEvent(new FocusEvent('blur', {bubbles: true})));
      };
      apply();
      await pause();
      if (controls[0].value !== start || controls[1].value !== end) {
        apply();
        await pause();
      }
      if (controls[0].value !== start || controls[1].value !== end)
        throw new Error(
            'VALIDATION_ERROR: 页面拒绝了起止月份；请使用 YYYY-MM。');
      return {startDate: start, endDate: end, requestedEndDate: requestedEnd};
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const {card, index} = await ensureCard('教育经历', input.index);
      const values = {
        school: await setTextField(card, 'school', input.school),
        degree: await setSelectField(card, 'degree', input.degree),
        fieldOfStudy:
            await setTextField(card, 'field_of_study', input.fieldOfStudy),
        date: await setDateRange(card, input.startDate, input.endDate)
      };
      return {
        data: {section: '教育经历', index, values},
        warnings: formErrors(card)
      };
    }
  }
}


// 填写实习经历 — write. 按 0-based index
// 新增或更新一条实习经历，不删除其他条目。
async function bytedance_resume_upsert_internship(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput &&
        'company' in rawInput && 'title' in rawInput &&
        'startDate' in rawInput && 'endDate' in rawInput &&
        'description' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'company', 'title', 'startDate', 'endDate',
                    'description']
                       .includes(key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('company' in rawInput) ||
         (typeof rawInput['company'] === 'string' &&
          [...rawInput['company']].length >= 1 &&
          [...rawInput['company']].length <= 100)) &&
        (!('title' in rawInput) ||
         (typeof rawInput['title'] === 'string' &&
          [...rawInput['title']].length >= 1 &&
          [...rawInput['title']].length <= 100)) &&
        (!('startDate' in rawInput) ||
         (typeof rawInput['startDate'] === 'string' &&
          new RegExp('^\\d{4}-(0[1-9]|1[0-2])$')
              .test(rawInput['startDate']))) &&
        (!('endDate' in rawInput) ||
         (((typeof rawInput['endDate'] === 'string' &&
            new RegExp('^\\d{4}-(0[1-9]|1[0-2])$').test(rawInput['endDate'])) ||
           (typeof rawInput['endDate'] === 'string' &&
            ['present'].includes(rawInput['endDate']))))) &&
        (!('description' in rawInput) ||
         (typeof rawInput['description'] === 'string' &&
          [...rawInput['description']].length >= 1 &&
          [...rawInput['description']].length <= 10000))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const setDateRange = async (container, startValue, endValue) => {
      const root = fieldRoot(container, 'start_end_time');
      const controls = root ? Array.from(root.querySelectorAll('input'))
                                  .filter((entry) => entry.type !== 'search') :
                              [];
      if (controls.length !== 2)
        throw new Error('SITE_CHANGED: 起止时间控件结构已变化。');
      const start = cleanText(startValue);
      const requestedEnd = cleanText(endValue);
      const now = new Date();
      const currentMonth =
          `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      const end = requestedEnd === 'present' ? currentMonth : requestedEnd;
      const apply = () => {
        setNativeValue(controls[1], end);
        setNativeValue(controls[0], start);
        controls.forEach(
            (entry) =>
                entry.dispatchEvent(new FocusEvent('blur', {bubbles: true})));
      };
      apply();
      await pause();
      if (controls[0].value !== start || controls[1].value !== end) {
        apply();
        await pause();
      }
      if (controls[0].value !== start || controls[1].value !== end)
        throw new Error(
            'VALIDATION_ERROR: 页面拒绝了起止月份；请使用 YYYY-MM。');
      return {startDate: start, endDate: end, requestedEndDate: requestedEnd};
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const writeCommonExperience = async (title) => {
      const {card, index} = await ensureCard(title, input.index);
      const written = {};
      written.company = await setTextField(card, 'company', input.company);
      written.title = await setTextField(card, 'title', input.title);
      written.date = await setDateRange(card, input.startDate, input.endDate);
      written.description = await setTextField(card, 'desc', input.description);
      return {
        data: {section: title, index, values: written},
        warnings: input.endDate === 'present' ?
            ['页面没有“至今”字段，已将结束时间写为当前月份。'] :
            []
      };
    };
    return writeCommonExperience('实习经历');
  }
}


// 填写项目经历 — write. 按 0-based index
// 新增或更新一条项目经历，不删除其他条目。
async function bytedance_resume_upsert_project(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput && 'name' in rawInput &&
        'role' in rawInput && 'startDate' in rawInput &&
        'endDate' in rawInput && 'description' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'name', 'role', 'startDate', 'endDate', 'link',
                    'description']
                       .includes(key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('name' in rawInput) ||
         (typeof rawInput['name'] === 'string' &&
          [...rawInput['name']].length >= 1 &&
          [...rawInput['name']].length <= 100)) &&
        (!('role' in rawInput) ||
         (typeof rawInput['role'] === 'string' &&
          [...rawInput['role']].length >= 1 &&
          [...rawInput['role']].length <= 100)) &&
        (!('startDate' in rawInput) ||
         (typeof rawInput['startDate'] === 'string' &&
          new RegExp('^\\d{4}-(0[1-9]|1[0-2])$')
              .test(rawInput['startDate']))) &&
        (!('endDate' in rawInput) ||
         (((typeof rawInput['endDate'] === 'string' &&
            new RegExp('^\\d{4}-(0[1-9]|1[0-2])$').test(rawInput['endDate'])) ||
           (typeof rawInput['endDate'] === 'string' &&
            ['present'].includes(rawInput['endDate']))))) &&
        (!('link' in rawInput) ||
         (typeof rawInput['link'] === 'string' &&
          [...rawInput['link']].length <= 2000)) &&
        (!('description' in rawInput) ||
         (typeof rawInput['description'] === 'string' &&
          [...rawInput['description']].length >= 1 &&
          [...rawInput['description']].length <= 10000))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const setDateRange = async (container, startValue, endValue) => {
      const root = fieldRoot(container, 'start_end_time');
      const controls = root ? Array.from(root.querySelectorAll('input'))
                                  .filter((entry) => entry.type !== 'search') :
                              [];
      if (controls.length !== 2)
        throw new Error('SITE_CHANGED: 起止时间控件结构已变化。');
      const start = cleanText(startValue);
      const requestedEnd = cleanText(endValue);
      const now = new Date();
      const currentMonth =
          `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      const end = requestedEnd === 'present' ? currentMonth : requestedEnd;
      const apply = () => {
        setNativeValue(controls[1], end);
        setNativeValue(controls[0], start);
        controls.forEach(
            (entry) =>
                entry.dispatchEvent(new FocusEvent('blur', {bubbles: true})));
      };
      apply();
      await pause();
      if (controls[0].value !== start || controls[1].value !== end) {
        apply();
        await pause();
      }
      if (controls[0].value !== start || controls[1].value !== end)
        throw new Error(
            'VALIDATION_ERROR: 页面拒绝了起止月份；请使用 YYYY-MM。');
      return {startDate: start, endDate: end, requestedEndDate: requestedEnd};
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const {card, index} = await ensureCard('项目经历', input.index);
      const values = {
        name: await setTextField(card, 'name', input.name),
        role: await setTextField(card, 'role', input.role),
        date: await setDateRange(card, input.startDate, input.endDate),
        description: await setTextField(card, 'desc', input.description)
      };
      if (input.link !== undefined)
        values.link = await setTextField(card, 'link', input.link);
      return {
        data: {section: '项目经历', index, values},
        warnings: input.endDate === 'present' ?
            ['页面没有“至今”字段，已将结束时间写为当前月份。'] :
            formErrors(card)
      };
    }
  }
}


// 填写作品 — write. 按 0-based index
// 新增或更新一条作品，可填写链接、描述和附件。
async function bytedance_resume_upsert_work_sample(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'link', 'description', 'attachment'].includes(
                key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('link' in rawInput) ||
         (typeof rawInput['link'] === 'string' &&
          [...rawInput['link']].length <= 2000)) &&
        (!('description' in rawInput) ||
         (typeof rawInput['description'] === 'string' &&
          [...rawInput['description']].length >= 1 &&
          [...rawInput['description']].length <= 10000)) &&
        (!('attachment' in rawInput) ||
         (typeof rawInput['attachment'] === 'object' &&
          rawInput['attachment'] !== null &&
          !Array.isArray(rawInput['attachment']) &&
          'filename' in rawInput['attachment'] &&
          'mimeType' in rawInput['attachment'] &&
          'base64' in rawInput['attachment'] &&
          Object.keys(rawInput['attachment'])
              .every(key => ['filename', 'mimeType', 'base64'].includes(key)) &&
          (!('filename' in rawInput['attachment']) ||
           (typeof rawInput['attachment']['filename'] === 'string' &&
            [...rawInput['attachment']['filename']].length >= 1 &&
            [...rawInput['attachment']['filename']].length <= 255)) &&
          (!('mimeType' in rawInput['attachment']) ||
           (typeof rawInput['attachment']['mimeType'] === 'string' &&
            [...rawInput['attachment']['mimeType']].length >= 1 &&
            [...rawInput['attachment']['mimeType']].length <= 100)) &&
          (!('base64' in rawInput['attachment']) ||
           (typeof rawInput['attachment']['base64'] === 'string' &&
            [...rawInput['attachment']['base64']].length >= 1 &&
            [...rawInput['attachment']['base64']].length <= 14000000)))) &&
        (('link' in rawInput) || ('description' in rawInput) ||
         ('attachment' in rawInput))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    const fileFromInput = (input) => {
      const filename = cleanText(input.filename);
      const mimeType = cleanText(input.mimeType);
      const encoded = String(input.base64 || '').replace(/\s+/g, '');
      let binary = '';
      try {
        binary = atob(encoded);
      } catch {
        throw new Error(
            'VALIDATION_ERROR: base64 不是有效的 Base64 文件内容。');
      }
      if (binary.length > 10 * 1024 * 1024)
        throw new Error('RESULT_TOO_LARGE: 附件不能超过 10 MiB。');
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1)
        bytes[index] = binary.charCodeAt(index);
      return new File([bytes], filename, {type: mimeType});
    };
    const setFile = async (container, fileInput) => {
      const control = container.querySelector('input[type="file"]');
      if (!control)
        throw new Error('SITE_CHANGED: 页面中找不到附件控件。');
      const file = fileFromInput(fileInput);
      if (typeof DataTransfer === 'undefined')
        throw new Error('SITE_CHANGED: 当前浏览器不支持安全设置附件。');
      const transfer = new DataTransfer();
      transfer.items.add(file);
      control.files = transfer.files;
      control.dispatchEvent(new Event('input', {bubbles: true}));
      control.dispatchEvent(new Event('change', {bubbles: true}));
      await pause(120);
      return {filename: file.name, mimeType: file.type, size: file.size};
    };
    {
      const {card, index} = await ensureCard('作品', input.index);
      const values = {};
      if (input.link !== undefined)
        values.link = await setTextField(card, 'link', input.link);
      if (input.description !== undefined)
        values.description =
            await setTextField(card, 'desc', input.description);
      if (input.attachment && typeof input.attachment === 'object')
        values.attachment = await setFile(
            fieldRoot(card, 'attachment') || card, input.attachment);
      return {
        data: {section: '作品', index, values},
        warnings: formErrors(card)
      };
    }
  }
}


// 填写获奖 — write. 按 0-based index 新增或更新一条获奖经历。
async function bytedance_resume_upsert_award(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput && 'name' in rawInput &&
        'year' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'name', 'year', 'description'].includes(key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('name' in rawInput) ||
         (typeof rawInput['name'] === 'string' &&
          [...rawInput['name']].length >= 1 &&
          [...rawInput['name']].length <= 100)) &&
        (!('year' in rawInput) ||
         (Number.isInteger(rawInput['year']) && rawInput['year'] >= 1900 &&
          rawInput['year'] <= 2100)) &&
        (!('description' in rawInput) ||
         (typeof rawInput['description'] === 'string' &&
          [...rawInput['description']].length >= 1 &&
          [...rawInput['description']].length <= 10000))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const {card, index} = await ensureCard('获奖', input.index);
      const values = {
        name: await setTextField(card, 'name', input.name),
        year: await setTextField(card, 'date', input.year)
      };
      if (input.description !== undefined)
        values.description =
            await setTextField(card, 'desc', input.description);
      return {
        data: {section: '获奖', index, values},
        warnings: formErrors(card)
      };
    }
  }
}


// 填写语言能力 — write. 按 0-based index 新增或更新一条语言能力。
async function bytedance_resume_upsert_language(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput &&
        'language' in rawInput && 'proficiency' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'language', 'proficiency'].includes(key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('language' in rawInput) ||
         (typeof rawInput['language'] === 'string' &&
          [...rawInput['language']].length >= 1 &&
          [...rawInput['language']].length <= 100)) &&
        (!('proficiency' in rawInput) ||
         (typeof rawInput['proficiency'] === 'string' && [
           '入门', '日常会话', '商务会话', '无障碍沟通', '母语'
         ].includes(rawInput['proficiency'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const selectOptionNodes = () => Array.from(document.querySelectorAll(
        '[role="option"],.ud__select__dropdown [class*="option"],.ud__select__dropdown li'));
    const setSelectField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      if (!root)
        throw new Error(`SITE_CHANGED: 页面中找不到选择字段“${fieldName}”。`);
      const normalized = cleanText(value);
      const nativeSelect = root.querySelector('select');
      if (nativeSelect) {
        const option =
            Array.from(nativeSelect.options)
                .find(
                    (entry) => cleanText(entry.textContent) === normalized ||
                        entry.value === normalized);
        if (!option)
          throw new Error(
              `VALIDATION_ERROR: 字段“${fieldName}”没有选项“${normalized}”。`);
        nativeSelect.value = option.value;
        nativeSelect.dispatchEvent(new Event('change', {bubbles: true}));
        return cleanText(option.textContent);
      }
      if (cleanText(root.textContent).includes(normalized))
        return normalized;
      const input = root.querySelector('input[type="search"],input');
      const trigger =
          root.querySelector('[class*="select__selector"]') || input;
      if (!input || !trigger)
        throw new Error(`SITE_CHANGED: 选择字段“${fieldName}”缺少可交互控件。`);
      trigger.click();
      setNativeValue(input, normalized);
      await pause(120);
      const candidates = selectOptionNodes().filter((node) => {
        const label = cleanText(node.textContent);
        return label === normalized || label.includes(normalized);
      });
      const option =
          candidates.find((node) => node.getClientRects().length > 0) ||
          candidates[0];
      if (option)
        option.click();
      else {
        input.dispatchEvent(new KeyboardEvent(
            'keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
        input.dispatchEvent(new KeyboardEvent(
            'keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
      }
      await pause(120);
      if (!cleanText(root.textContent).includes(normalized) &&
          cleanText(input.value) !== normalized) {
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”没有可选择的“${
            normalized}”。`);
      }
      return normalized;
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const {card, index} = await ensureCard('语言能力', input.index);
      const values = {
        language: await setSelectField(card, 'language', input.language),
        proficiency:
            await setSelectField(card, 'proficiency', input.proficiency)
      };
      return {
        data: {section: '语言能力', index, values},
        warnings: formErrors(card)
      };
    }
  }
}


// 填写自我评价 — write. 填写或更新自我评价。
async function bytedance_resume_set_self_evaluation(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'value' in rawInput &&
        Object.keys(rawInput).every(key => ['value'].includes(key)) &&
        (!('value' in rawInput) || (typeof rawInput['value'] === 'string' && [
          ...rawInput['value']
        ].length >= 1 && [...rawInput['value']].length <= 10000))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const module = section('自我评价');
      if (!module)
        throw new Error('SITE_CHANGED: 页面中找不到自我评价栏目。');
      if (!fieldRoot(module, 'self_evaluation')) {
        clickAdd(module);
        await pause(120);
      }
      return {
        data: {
          updated: true,
          value: await setTextField(module, 'self_evaluation', input.value)
        },
        warnings: formErrors(module)
      };
    }
  }
}


// 填写社交账号 — write. 按 0-based index 新增或更新一个社交账号。
async function bytedance_resume_upsert_social_account(rawInput = {}) {
  const route = /^\/experienced\/resume\/(view|edit)\/?$/;
  const bytedanceResumeAdapter = {
    matches: (url) =>
        url.hostname === 'jobs.bytedance.com' && route.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bytedanceResumeAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 字节跳动简历 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'index' in rawInput &&
        'platform' in rawInput && 'value' in rawInput &&
        Object.keys(rawInput).every(
            key => ['index', 'platform', 'value'].includes(key)) &&
        (!('index' in rawInput) ||
         (Number.isInteger(rawInput['index']) && rawInput['index'] >= 0 &&
          rawInput['index'] <= 49)) &&
        (!('platform' in rawInput) ||
         (typeof rawInput['platform'] === 'string' &&
          [
            '微信', 'QQ', '领英', '脉脉', '微博', 'Github', '知乎', '脸书',
            '推特'
          ].includes(rawInput['platform']))) &&
        (!('value' in rawInput) || (typeof rawInput['value'] === 'string' && [
          ...rawInput['value']
        ].length >= 1 && [...rawInput['value']].length <= 2000))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
    const cleanText = (value) =>
        String(value ?? '')
            .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const moduleNodes = () =>
        Array
            .from(
                document.querySelectorAll('[class*="applyFormModuleWrapper"]'))
            .filter(
                (node, index, all) => !all.some(
                    (parent, parentIndex) =>
                        parentIndex < index && parent.contains(node)));
    const moduleTitle = (node) => cleanText(
        node.querySelector('.applyFormModuleWrapper-text')?.textContent);
    const section = (title) =>
        moduleNodes().find((node) => moduleTitle(node) === title) || null;
    const form = document.querySelector('form');
    if (!form || !section('基本信息'))
      return {
        data: null,
        error: {
          code: 'AUTH_REQUIRED',
          message:
              '字节跳动简历编辑表单尚未加载；请确认已登录并等待页面完成加载。',
          recoverable: true
        }
      };
    const fieldRoot = (container, fieldName) => {
      const self =
          container instanceof HTMLElement && container.dataset.formFieldName ?
          [container] :
          [];
      const candidates = [
        ...self,
        ...Array.from(container.querySelectorAll('[data-form-field-name]'))
      ];
      const matched = candidates.find(
                          (node) => node.dataset.formFieldName === fieldName &&
                              node.classList.contains('ud-formily-item')) ||
          candidates.find((node) => node.dataset.formFieldName === fieldName);
      return matched?.closest('.ud-formily-item') || matched || null;
    };
    const setNativeValue = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 页面输入控件不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const textControl = (root) => root.querySelector(
        'textarea[data-form-field-name],input[data-form-field-name],textarea,input:not([type="search"]):not([type="file"]):not([type="checkbox"])');
    const setTextField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      const control = root ? textControl(root) : null;
      if (!root || !control)
        throw new Error(`SITE_CHANGED: 页面中找不到字段“${fieldName}”。`);
      const normalized = String(value ?? '');
      setNativeValue(control, normalized);
      control.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
      await pause();
      if (control.value !== normalized)
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”拒绝了输入值。`);
      return normalized;
    };
    const selectOptionNodes = () => Array.from(document.querySelectorAll(
        '[role="option"],.ud__select__dropdown [class*="option"],.ud__select__dropdown li'));
    const setSelectField = async (container, fieldName, value) => {
      const root = fieldRoot(container, fieldName);
      if (!root)
        throw new Error(`SITE_CHANGED: 页面中找不到选择字段“${fieldName}”。`);
      const normalized = cleanText(value);
      const nativeSelect = root.querySelector('select');
      if (nativeSelect) {
        const option =
            Array.from(nativeSelect.options)
                .find(
                    (entry) => cleanText(entry.textContent) === normalized ||
                        entry.value === normalized);
        if (!option)
          throw new Error(
              `VALIDATION_ERROR: 字段“${fieldName}”没有选项“${normalized}”。`);
        nativeSelect.value = option.value;
        nativeSelect.dispatchEvent(new Event('change', {bubbles: true}));
        return cleanText(option.textContent);
      }
      if (cleanText(root.textContent).includes(normalized))
        return normalized;
      const input = root.querySelector('input[type="search"],input');
      const trigger =
          root.querySelector('[class*="select__selector"]') || input;
      if (!input || !trigger)
        throw new Error(`SITE_CHANGED: 选择字段“${fieldName}”缺少可交互控件。`);
      trigger.click();
      setNativeValue(input, normalized);
      await pause(120);
      const candidates = selectOptionNodes().filter((node) => {
        const label = cleanText(node.textContent);
        return label === normalized || label.includes(normalized);
      });
      const option =
          candidates.find((node) => node.getClientRects().length > 0) ||
          candidates[0];
      if (option)
        option.click();
      else {
        input.dispatchEvent(new KeyboardEvent(
            'keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
        input.dispatchEvent(new KeyboardEvent(
            'keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
      }
      await pause(120);
      if (!cleanText(root.textContent).includes(normalized) &&
          cleanText(input.value) !== normalized) {
        throw new Error(`VALIDATION_ERROR: 字段“${fieldName}”没有可选择的“${
            normalized}”。`);
      }
      return normalized;
    };
    const cards = (module) => Array.from(
        module.querySelectorAll('[class*="apply-form-array-card-content"]'));
    const clickAdd = (module) => {
      const button =
          Array.from(module.querySelectorAll('button'))
              .find((entry) => cleanText(entry.textContent) === '添加');
      if (!button)
        throw new Error(`SITE_CHANGED: “${moduleTitle(module)}”缺少添加按钮。`);
      button.click();
    };
    const ensureCard = async (title, rawIndex) => {
      const index = Number(rawIndex);
      const module = section(title);
      if (!module)
        throw new Error(`SITE_CHANGED: 页面中找不到“${title}”栏目。`);
      if (title === '工作经历') {
        const checkbox = module.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          checkbox.click();
          await pause(120);
        }
      }
      for (let guard = 0; cards(module).length <= index && guard < 50;
           guard += 1) {
        clickAdd(module);
        await pause(120);
      }
      const card = cards(module)[index];
      if (!card)
        throw new Error(`SITE_CHANGED: 无法创建“${title}”第 ${index + 1} 条。`);
      return {module, card, index};
    };
    const formErrors = (container = form) =>
        Array
            .from(container.querySelectorAll(
                '.ud-formily-item-feedback-status-error,.ud-formily-item-help,.ud-formily-item-feedback'))
            .map((node) => cleanText(node.textContent))
            .filter(Boolean);
    {
      const {card, index} = await ensureCard('社交账号', input.index);
      const values = {
        platform: await setSelectField(card, 'sns_type', input.platform),
        value: await setTextField(card, 'link', input.value)
      };
      return {
        data: {section: '社交账号', index, values},
        warnings: formErrors(card)
      };
    }
  }
}
