# 飞书多维表格: source conversions

复用当前飞书网页登录态，管理数据表、字段、选项、记录与视图。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: *.feishu.cn. Routes: /base/*, /wiki/*?table=tbl*.

- 只操作当前页面已加载的 Base 模型
- A1/B4 等位置引用按当前视图可见行列顺序解析
- 写入前按页面真实结构校验
- 批量单次最多 200 条
- 删除类工具要求 confirm=true
- 不读取或导出 Cookie 与访问令牌

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `feishu_base_get_table_context`

读取当前 Base、数据表、视图、字段结构、可写性和加载范围；写入前先调用。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    }
  },
  "additionalProperties": false
}
```

### `feishu_base_list_tables`

列出当前 Base 页面模型中已加载的数据表、字段数、视图数和记录数。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### `feishu_base_create_table`

在当前 Base 中创建数据表并设置名称。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    }
  },
  "required": [
    "name"
  ],
  "additionalProperties": false
}
```

### `feishu_base_rename_table`

按数据表 ID 或精确名称重命名数据表。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    }
  },
  "required": [
    "tableId",
    "name"
  ],
  "additionalProperties": false
}
```

### `feishu_base_delete_table`

删除明确指定的数据表；不可逆，必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "tableId",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `feishu_base_create_field`

在指定数据表创建文本、数字、选项、日期或复选框字段；type=select 时用 multiple 区分单选/多选，并可同时创建选项。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "type": {
      "type": "string",
      "enum": [
        "text",
        "number",
        "select",
        "single_select",
        "multi_select",
        "datetime",
        "checkbox"
      ]
    },
    "multiple": {
      "type": "boolean",
      "default": false
    },
    "options": {
      "type": "array",
      "maxItems": 1000,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100
      }
    }
  },
  "required": [
    "name",
    "type"
  ],
  "additionalProperties": false
}
```

### `feishu_base_rename_field`

按字段 ID 或精确名称重命名字段，不改变字段类型和已有值。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "fieldId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    }
  },
  "required": [
    "fieldId",
    "name"
  ],
  "additionalProperties": false
}
```

### `feishu_base_add_field_options`

向单选或多选字段追加选项；不会删除或覆盖已有选项。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "fieldId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "options": {
      "type": "array",
      "minItems": 1,
      "maxItems": 1000,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100
      }
    }
  },
  "required": [
    "fieldId",
    "options"
  ],
  "additionalProperties": false
}
```

### `feishu_base_delete_field`

删除明确指定的非主字段；不可逆，必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "fieldId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "fieldId",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `feishu_base_list_records`

按当前视图可见行顺序分页返回记录 ID、1-based 行号、字段值和易读展示值；若无法确认视图顺序会明确警告。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "offset": {
      "type": "integer",
      "minimum": 0,
      "maximum": 1000000,
      "default": 0
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 200,
      "default": 50
    }
  },
  "additionalProperties": false
}
```

### `feishu_base_verify_records`

在页面内按唯一键比较预期记录与当前可见记录，只返回数量、缺失项、多余项和字段差异摘要。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "keyField": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "expectedRecords": {
      "type": "array",
      "minItems": 1,
      "maxItems": 200,
      "items": {
        "type": "object",
        "properties": {
          "fields": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": true
          }
        },
        "required": [
          "fields"
        ],
        "additionalProperties": false
      }
    },
    "maxDiffs": {
      "type": "integer",
      "minimum": 0,
      "maximum": 100,
      "default": 20
    }
  },
  "required": [
    "keyField",
    "expectedRecords"
  ],
  "additionalProperties": false
}
```

### `feishu_base_resolve_range`

按当前视图可见行列顺序解析 A1、B4 或 A1:C5，返回对应 recordId、fieldId、值和 1-based 行列号。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "range": {
      "type": "string",
      "minLength": 2,
      "maxLength": 64,
      "pattern": "^[A-Za-z]+[1-9][0-9]*(?::[A-Za-z]+[1-9][0-9]*)?$"
    }
  },
  "required": [
    "range"
  ],
  "additionalProperties": false
}
```

### `feishu_base_add_records`

向当前数据表批量新增记录；字段可用精确字段名或字段 ID，单次最多 200 条。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "records": {
      "type": "array",
      "minItems": 1,
      "maxItems": 200,
      "items": {
        "type": "object",
        "properties": {
          "fields": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": true
          }
        },
        "required": [
          "fields"
        ],
        "additionalProperties": false
      }
    }
  },
  "required": [
    "records"
  ],
  "additionalProperties": false
}
```

### `feishu_base_update_records`

按 recordId 批量更新当前数据表记录；字段可用精确字段名或字段 ID，单次最多 200 条；清空单元格必须使用 feishu_base_clear_cells，不要传 null。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "records": {
      "type": "array",
      "minItems": 1,
      "maxItems": 200,
      "items": {
        "type": "object",
        "properties": {
          "recordId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128
          },
          "fields": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": true
          }
        },
        "required": [
          "recordId",
          "fields"
        ],
        "additionalProperties": false
      }
    }
  },
  "required": [
    "records"
  ],
  "additionalProperties": false
}
```

### `feishu_base_clear_cells`

按 recordId 和字段 ID/精确名称清空单元格，并在返回前验证页面模型中的值确已为空；单次最多 200 个。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "cells": {
      "type": "array",
      "minItems": 1,
      "maxItems": 200,
      "items": {
        "type": "object",
        "properties": {
          "recordId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128
          },
          "fieldId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128
          }
        },
        "required": [
          "recordId",
          "fieldId"
        ],
        "additionalProperties": false
      }
    }
  },
  "required": [
    "cells"
  ],
  "additionalProperties": false
}
```

### `feishu_base_delete_records`

按 recordId 批量删除记录；不可逆，单次最多 200 条且必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "recordIds": {
      "type": "array",
      "minItems": 1,
      "maxItems": 200,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 128
      }
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "recordIds",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `feishu_base_list_views`

列出指定数据表的视图及其类型、筛选、排序、分组和可见字段配置。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    }
  },
  "additionalProperties": false
}
```

### `feishu_base_create_view`

创建表格、看板、画册、甘特图或日历视图。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "type": {
      "type": "string",
      "enum": [
        "grid",
        "kanban",
        "gallery",
        "gantt",
        "calendar"
      ],
      "default": "grid"
    }
  },
  "required": [
    "name"
  ],
  "additionalProperties": false
}
```

### `feishu_base_rename_view`

按视图 ID 或精确名称重命名视图。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    }
  },
  "required": [
    "viewId",
    "name"
  ],
  "additionalProperties": false
}
```

### `feishu_base_update_view`

配置视图的可见字段、排序、分组或页面原生 filterInfo。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "visibleFieldIds": {
      "type": "array",
      "minItems": 1,
      "maxItems": 500,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 128
      }
    },
    "sort": {
      "type": "array",
      "maxItems": 20,
      "items": {
        "type": "object",
        "properties": {
          "fieldId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128
          },
          "desc": {
            "type": "boolean",
            "default": false
          }
        },
        "required": [
          "fieldId"
        ],
        "additionalProperties": false
      }
    },
    "group": {
      "type": "array",
      "maxItems": 3,
      "items": {
        "type": "object",
        "properties": {
          "fieldId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128
          },
          "desc": {
            "type": "boolean",
            "default": false
          }
        },
        "required": [
          "fieldId"
        ],
        "additionalProperties": false
      }
    },
    "filterInfo": {
      "anyOf": [
        {
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "required": [
    "viewId"
  ],
  "additionalProperties": false
}
```

### `feishu_base_delete_view`

删除明确指定的视图；不可逆，必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "tableId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "viewId": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "viewId",
    "confirm"
  ],
  "additionalProperties": false
}
```
