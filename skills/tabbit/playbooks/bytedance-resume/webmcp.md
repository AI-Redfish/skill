# 字节跳动简历: source conversions

在字节跳动社招简历编辑页填写并校验各栏目，最终提交由用户完成。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: jobs.bytedance.com. Routes: /experienced/resume/view, /experienced/resume/edit.

- 仅匹配社招简历查看/编辑页
- 按页面 data-form-field-* 锚点填写
- 重复经历按 0-based index 新增或更新，不删除其他条目
- 附件单个不超过 10 MiB
- 不提供完成或提交能力

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `bytedance_resume_get_context`

读取当前简历页的栏目、字段、条目数量、可见值和页面校验错误。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### `bytedance_resume_set_basic_info`

填写姓名、国家/地区代码、手机号、邮箱和期望工作地点。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "countryCode": {
      "type": "string",
      "minLength": 1,
      "maxLength": 16
    },
    "mobile": {
      "type": "string",
      "minLength": 5,
      "maxLength": 32
    },
    "email": {
      "type": "string",
      "minLength": 3,
      "maxLength": 254
    },
    "preferredCities": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100
      }
    }
  },
  "minProperties": 1,
  "additionalProperties": false
}
```

### `bytedance_resume_upload_attachment`

将明确提供的 Base64 文件设置到简历附件控件；会触发页面上传。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "filename": {
      "type": "string",
      "minLength": 1,
      "maxLength": 255
    },
    "mimeType": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "base64": {
      "type": "string",
      "minLength": 1,
      "maxLength": 14000000
    }
  },
  "required": [
    "filename",
    "mimeType",
    "base64"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_set_no_work_experience`

设置或取消“没有工作经历”；取消后可继续填写工作经历。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "value": {
      "type": "boolean"
    }
  },
  "required": [
    "value"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_work_experience`

按 0-based index 新增或更新一条工作经历，不删除其他条目。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "company": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "title": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "startDate": {
      "type": "string",
      "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
    },
    "endDate": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
        },
        {
          "type": "string",
          "enum": [
            "present"
          ]
        }
      ]
    },
    "description": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10000
    }
  },
  "required": [
    "index",
    "company",
    "title",
    "startDate",
    "endDate",
    "description"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_education`

按 0-based index 新增或更新一条教育经历，不删除其他条目。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "school": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "degree": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "fieldOfStudy": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "startDate": {
      "type": "string",
      "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
    },
    "endDate": {
      "type": "string",
      "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
    }
  },
  "required": [
    "index",
    "school",
    "degree",
    "fieldOfStudy",
    "startDate",
    "endDate"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_internship`

按 0-based index 新增或更新一条实习经历，不删除其他条目。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "company": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "title": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "startDate": {
      "type": "string",
      "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
    },
    "endDate": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
        },
        {
          "type": "string",
          "enum": [
            "present"
          ]
        }
      ]
    },
    "description": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10000
    }
  },
  "required": [
    "index",
    "company",
    "title",
    "startDate",
    "endDate",
    "description"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_project`

按 0-based index 新增或更新一条项目经历，不删除其他条目。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "role": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "startDate": {
      "type": "string",
      "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
    },
    "endDate": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\d{4}-(0[1-9]|1[0-2])$"
        },
        {
          "type": "string",
          "enum": [
            "present"
          ]
        }
      ]
    },
    "link": {
      "type": "string",
      "maxLength": 2000
    },
    "description": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10000
    }
  },
  "required": [
    "index",
    "name",
    "role",
    "startDate",
    "endDate",
    "description"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_work_sample`

按 0-based index 新增或更新一条作品，可填写链接、描述和附件。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "link": {
      "type": "string",
      "maxLength": 2000
    },
    "description": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10000
    },
    "attachment": {
      "type": "object",
      "properties": {
        "filename": {
          "type": "string",
          "minLength": 1,
          "maxLength": 255
        },
        "mimeType": {
          "type": "string",
          "minLength": 1,
          "maxLength": 100
        },
        "base64": {
          "type": "string",
          "minLength": 1,
          "maxLength": 14000000
        }
      },
      "required": [
        "filename",
        "mimeType",
        "base64"
      ],
      "additionalProperties": false
    }
  },
  "required": [
    "index"
  ],
  "anyOf": [
    {
      "required": [
        "link"
      ]
    },
    {
      "required": [
        "description"
      ]
    },
    {
      "required": [
        "attachment"
      ]
    }
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_award`

按 0-based index 新增或更新一条获奖经历。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "year": {
      "type": "integer",
      "minimum": 1900,
      "maximum": 2100
    },
    "description": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10000
    }
  },
  "required": [
    "index",
    "name",
    "year"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_language`

按 0-based index 新增或更新一条语言能力。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "language": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "proficiency": {
      "type": "string",
      "enum": [
        "入门",
        "日常会话",
        "商务会话",
        "无障碍沟通",
        "母语"
      ]
    }
  },
  "required": [
    "index",
    "language",
    "proficiency"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_set_self_evaluation`

填写或更新自我评价。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "value": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10000
    }
  },
  "required": [
    "value"
  ],
  "additionalProperties": false
}
```

### `bytedance_resume_upsert_social_account`

按 0-based index 新增或更新一个社交账号。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "index": {
      "type": "integer",
      "minimum": 0,
      "maximum": 49
    },
    "platform": {
      "type": "string",
      "enum": [
        "微信",
        "QQ",
        "领英",
        "脉脉",
        "微博",
        "Github",
        "知乎",
        "脸书",
        "推特"
      ]
    },
    "value": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2000
    }
  },
  "required": [
    "index",
    "platform",
    "value"
  ],
  "additionalProperties": false
}
```
