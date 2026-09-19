# 前端接口风格参考

> 说明：以下路径是**风格锚点示例**，仅用于理解该前端仓库的 API 模块组织方式；若调用方提供了真实前端项目路径，一律以真实项目为准。本文档明确：**最终技术文档不输出前端函数名**，但路径语义与参数组织仍应参考现有前端调用习惯，保证后端 URL/参数看起来能落到当前前端仓库。

本 skill 在输出“接口清单”时，除了参考后端 controller 风格，还要参考现有前端 API 模块组织方式，确保“后端 URL / 参数组织”看起来像真会落到当前前端仓库里。当前输出不再展示前端函数名，但路径语义和参数组织仍应参考现有前端调用习惯。

## 1. 重点参考文件

- `D:/develop/project/wukong/apps/operation/src/pages/common/deviceManagement/deviceManage/api/index.js`
- `D:/develop/project/wukong/apps/operation/src/pages/common/deviceManagement/deviceManage/api/monitorBySpace.js`
- `D:/develop/project/wukong/apps/operation/src/pages/memberGrouping/groupManagement/api.js`
- `D:/develop/project/wukong/apps/client/src/plugin/axios.js`
- `D:/develop/project/wukong/packages-web/utils/src/http/request.ts`

## 2. API 模块常见风格

观察到的稳定模式：
- 页面会配套 `api.js` 或 `api/*.js`
- 函数命名偏业务动作：
  - `getSysGroupList`
  - `deleteSysGroup`
  - `updateSysGroupStatus`
  - `listSpaces`
  - `listBySpace`
  - `countBySpace`
- URL 经常保留现有后端动作式风格，不强行转成纯资源式风格
- 前端请求封装统一通过 `httpApi` 或共享 `request` 能力发送

因此接口清单建议按以下粒度组织：
- 功能说明
- 后端 URL
- Method
- 入参结构
- 出参结构
- 备注（是否字典扩展、是否分页、是否组合入参）
- 其中入参、出参需进一步拆成参数表格，体现字段名、类型、字段含义、字典编码（如有）

## 3. 字典映射命名

前端常见风格：
- `applyScopeDictMap`
- `assetStatusDictMap`
- `educationLevelDictMap`
- `serviceItemDictMap`

因此输出接口请求/响应字段时：
- 业务字段保留实际字段名
- 前端映射命名统一使用 `xxxDictMap`
- 如涉及展示态，可在接口字段说明中注明列表/详情/筛选使用该 DictMap 展示名称

`增量字典` 章节不输出 DictMap 或页面位置，只按主 skill 约定列“实体字段字典使用清单”和“字典枚举项”。

## 4. 分页与查询表达

当前前端与后端接口清单里，常见分页表达不是纯 querystring，而是和筛选条件一起组织。因此接口清单描述中可以自然使用：
- `filter + orderParam + pageParam`
- `formData + pageParam`
- `query + pageParam`

如果后端风格明显需要 `@MyRequestBody` 多参数，可在备注中明确写出，而不是硬凑成单对象。

## 5. 输出时要避免

- 不要用与现有前端风格差异很大的函数命名，如 `fetchAllGroupsResource`
- 不要把所有路径都写成纯 RESTful 风格，除非现有模块真这么写
- 不要忽略前端会消费的字典映射字段
- 不要让接口动作命名和参数组织偏离现有前端调用习惯
