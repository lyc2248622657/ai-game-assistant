# 原神知识包数据模板说明

本目录是原神知识包数据源，每类条目一个 JSON 文件。`scripts/ingest.py` 会自动读取本目录全部 `.json` 文件入库，**新增文件类型无需修改任何代码**。

## 目录结构

```
data/genshin/
├── characters.json   # 角色（20 条）
├── weapons.json      # 武器（15 条）
├── artifacts.json    # 圣遗物（10 套）
├── materials.json    # 材料（15 种）
├── foods.json        # 料理（特殊料理 + 原型料理，16 条）
├── teams.json        # 配队攻略（8 个）
├── images/           # 图片目录（按类型分子目录，可放本地图片）
└── TEMPLATE.md       # 本说明
```

## 通用字段（所有类型均有）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | ✅ | 全局唯一，小写英文/下划线，如 `hutao`、`food_su_baoyu` |
| `type` | string | ✅ | 条目类型：`character/weapon/artifact/material/food/team` |
| `name` | string | ✅ | 显示名称 |
| `image` | string | — | 图片路径：本地相对路径（`images/characters/hutao.png`）或完整 URL；**留空表示待补充**，后续图形化功能按此字段渲染 |
| `tags` | string[] | — | 检索标签，问答匹配的关键词 |
| `summary` | string | — | 一句话简介（RAG 检索的文本主干） |
| `details` | object | — | 类型特有详情（见下） |
| `extra` | object | — | **自由扩展区**：可随意添加任意键值，例如角色登场时间、特殊料理、CV、命座等，不影响入库 |
| `source` / `source_note` | string | — | 数据来源标注 |

## 类型特有字段

### character（角色）
顶层：`element`（元素）、`weapon_type`（武器类型）、`rarity`、`role`（主C/副C/辅助/治疗）、`region`（地区）、`debut_version`（**登场版本**）、`debut_date`（**登场日期**）、`special_food`（**特殊料理 id，引用 foods 条目**，无特殊料理留空如雷电将军）。
`details`：`birthday`、`ascension_materials`（突破材料 id 数组，引用 materials）、`playstyle`（玩法）、`notes`。

**官方增强字段（2026-09 起，以原神官方 wiki（BWIKI）为主要依据自动获取）**：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `birthday` | string | 生日（官方 wiki，如 `7月15日`） |
| `constellations` | object[] | 命之座 6 条：`[{index, name, effect}]`（官方 wiki） |
| `skills` | object[] | 天赋技能：`[{name, type(normal/skill/burst/passive/utility), description, levels?}]`；`levels` 为技能数值表（官方 wiki 渲染表，Lv1~Lv15 倍率） |
| `teams` | object[] | 主流配队（wiki 无此数据，由 LLM 按官方已知信息补充）：`[{name, members, core}]` |

> 数据来源约定：`birthday/constellations/skills`（含数值）一律以官方 wiki 为准，LLM 不编造；`teams/role/summary` 等推断字段由 LLM 补充。条目 `source` 标注「原神官方wiki（BWIKI）为主要依据 + DeepSeek 仅补缺失」。

### weapon（武器）
顶层：`category`（武器类型）、`rarity`、`main_stat`、`sub_stat`、`passive`（被动效果）、`recommended`（推荐角色 id 数组，引用 characters）、`source`（获取方式）。
`details`：`special_note`。

### artifact（圣遗物）
顶层：`set_pieces`（五个部位）、`rarity`、`two_piece`、`four_piece`、`recommended`（推荐角色 id 数组）、`domain`（刷取秘境）。
`details`：`main_stat`（主属性建议）。

### material（材料）
顶层：`category`（货币/角色突破/怪物掉落/地区特产/料理材料）、`rarity`、`usage`（用途）、`source`（获取来源）。
`details`：`levels`（材料等级链）、`gathering_note`。

### food（料理）
顶层：`food_type`（`special` 特殊料理 / `prototype` 原型料理）、`owner_character`（**制作者角色 id**，原型料理留空）、`prototype_food`（**原型料理 id，引用 foods**，原型料理留空）、`effect`（效果）、`obtain`（**获取方式**：特殊料理=用对应角色烹饪原型料理；原型料理=食谱获取途径）、`rarity`。
`details`：`ingredients`（食材清单）。

### team（配队）
顶层：`members`（成员角色 id 数组，引用 characters）、`core`（核心机制）、`rotation`（输出手法）、`difficulty`（上手难度）、`dps_source`（伤害来源）。
`details`：`note`。

## 扩展机制（重点）

1. **给已有条目加信息**：任意新字段可直接加进 `extra`（或顶层），校验脚本只检查必填与引用，不拒绝新字段。
2. **新增模板类型**：在目录下新建 `xxx.json`（如 `monsters.json`、`quests.json`），条目 `type` 填新类型名即可，`ingest.py` 自动读入；需要「按类型筛选检索」时在 `ingest.py` 的 `chunk_entry` 元数据中已带 `type`。
3. **图片关联**：`image` 字段统一指向 `images/` 下文件或外链；前端图形化（角色图鉴、料理卡片等）直接消费该字段。图片命名规范：`images/<类型>/<条目id>.png`。
4. **交叉引用**：引用一律用目标条目 `id`（如 `special_food: "food_su_baoyu"`），校验脚本会检查引用有效性，保证数据一致。

## 数据质量约定

- 本包 84 条为「模板 + 示例」性质：核心字段（名称、登场版本、特殊料理、原型料理、获取方式）已按官方资料核验；`details` 中部分细节（具体数值、图片资源）留待完善，以空值或 `notes` 标注。
- 图片资源当前未打包（`image` 字段已规划路径但文件待补充），后续可下载官方/合规图源放入 `images/` 或改为外链 URL。
- 修改数据后运行 `python scripts/validate_data.py --game genshin` 校验。
