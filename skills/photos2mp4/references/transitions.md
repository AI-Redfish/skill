# 切换效果总表与逐页 JSON

> 本文件是 SKILL.md 的扩展参考，按需加载。

## 逐页切换 JSON（`--transitions-json`）

```json
[
  {"slide": 1, "transition": "fade",    "duration": 0.8, "advance": 3.0},
  {"slide": 2, "transition": "push",    "direction": "left", "advance": 2.5},
  {"slide": 3, "transition": "wipe",    "direction": "up", "advance": 2.5},
  {"slide": 4, "transition": "wheel",   "options": {"spokes": "3"}, "advance": 2.5},
  {"slide": 5, "transition": "reveal",  "direction": "throughblack", "advance": 2.5},
  {"slide": 6, "transition": "glitter", "direction": "l", "options": {"pattern": "hexagon"}, "advance": 3.5}
]
```

- `slide`：1 起始页码；**省略时按数组位置顺序对应**（第 1 个未指定者→第 1 页）
- 每个字段均可选；未指定的页沿用命令行全局值
- `direction` 友好别名自动归一化：`left→l`、`up→u`、`horizontal→horz`、`throughblack`…

## 切换效果总表（40 种）

### 经典（PowerPoint 2007+，21 种）

| 名称 | direction | 其它参数 |
|------|-----------|----------|
| blinds / checker / comb | `horz`\|`vert` | |
| circle / diamond / dissolve / newsflash / plus / random / wedge | — | |
| cover / pull | `d`\|`l`\|`r`\|`u`\|`ld`\|`lu`\|`rd`\|`ru` | |
| cut / fade | `throughblack` | |
| push / wipe | `d`\|`l`\|`r`\|`u` | |
| randombar | `horz`\|`vert` | |
| split | `in`\|`out` | `orient=horz\|vert` |
| strips | `ld`\|`lu`\|`rd`\|`ru` | |
| wheel | `1`\|`2`\|`3`\|`4`\|`8` | 或 `--opt spokes=N` |
| zoom | `in`\|`out` | |

### PowerPoint 2010+（18 种，旧版自动回退为 fade）

| 名称 | direction | 其它参数 |
|------|-----------|----------|
| conveyor★ / ferris★ / flip★ / gallery★ / switch★ | `l`\|`r` | |
| vortex | `l`\|`r` | |
| flythrough | `in`\|`out` | `hasBounce=0\|1` |
| glitter | `d`\|`l`\|`r`\|`u` | `pattern=diamond\|hexagon` |
| shred | `in`\|`out` | `pattern=strip\|rectangle` |
| reveal | `throughblack` | |
| warp | `in`\|`out` | |
| doors / flash / honeycomb / pan / prism / ripple / window | — | |

★ `dir` 为 schema 必填属性，未指定时自动补 `l`（PowerPoint 严格校验，缺失会拒开文件）。

### PowerPoint 2019/365（1 种）

| 名称 | 其它参数 |
|------|----------|
| morph（平滑，对纯图片页无意义） | `option=byObject\|byWord\|byChar`（必填，自动补 `byObject`） |

## 背景音乐行为

写入第 1 页（OOXML 音频形状 + 时间轴）：

- 放映/导出视频时**自动开始播放**，**跨全部幻灯片**（numSld=999）
- 默认**循环**直到演示结束（`--music-no-loop` 关闭）
- 音乐图标放在页面外 + `showWhenStopped=0`，**放映和视频中不可见**
- 导出 MP4 时音乐会被渲染进视频音轨
- 推荐格式 mp3 / m4a / wav / wma

## 效果选择速查

| 用户想要的感受 | 推荐 |
|----------------|------|
| 简洁、通用 | fade |
| 方向感、动感 | push / wipe（配 direction） |
| 聚焦、戏剧性 | zoom in / reveal throughblack |
| 炫酷、花哨 | glitter（hexagon）、ripple、vortex |
| 规律机械感 | blinds / checker / comb |
- 图片很多的相册建议 fade/push 这类不易审美疲劳的效果
