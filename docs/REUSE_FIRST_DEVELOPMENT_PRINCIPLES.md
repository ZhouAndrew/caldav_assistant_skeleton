# CalDAV Assistant — 开发方法：先学习与复用，后设计

> 状态：开发原则 / 适用于 CalDAV Assistant、Thunderbird 插件及相关工具  
> 核心目标：**简单、可用第一位；以最少的新代码完成可靠功能。**

## 1. 这份原则来自什么问题

过去项目出现过以下现象：

- 一个相对简单的功能被拆成很多 Pull Request；
- 很多 CLI 构想实现成本越来越高，最终没有形成稳定可用的功能；
- 在充分研究 Thunderbird、CalDAV 标准和同类开源实现之前，就自行设计新的 Core、Service、Adapter、State、Selector、Parser、API；
- 后来才发现 Thunderbird 或成熟开源项目已经解决了其中大量问题；
- 因此产生重复造轮子、回退、重构、救援分支和额外维护成本。

这些问题的共同根源不是需求天然复杂，而是开发顺序经常反了：

```text
过去：
需求
→ 自行设计完整架构
→ 实现
→ 碰到真实平台限制
→ 再研究现有实现
→ 重构 / 回退 / 新 PR
```

今后应改为：

```text
需求
→ 调查现有实现
→ 研究标准 / 宿主 / 成熟开源项目 / 库
→ 找到真正缺口
→ 只实现缺口
→ 真实验收
```

## 2. Thunderbird 不是“后来才想到的替代方案”

Thunderbird 已经是成熟的 Calendar / Task / CalDAV 客户端。

因此以下能力，原则上优先由 Thunderbird 提供：

- Task / Event UI；
- Task 选择；
- Calendar；
- Due / Start；
- Category；
- Status；
- Task / Event 编辑；
- CalDAV 账户、同步及相关成熟行为。

Assistant 不应重新实现一套 Thunderbird 已经成熟提供的 Task/Event UI 和工作流。

当前 Thunderbird 主线的核心边界保持简单：

```text
Thunderbird
├─ Task / Event
├─ 原生 Tasks UI
├─ Calendar / 编辑 / Category / Status / Due / Start
└─ CalDAV 客户端能力

Assistant
├─ currentWorkId
├─ start
├─ stop
├─ complete
├─ cancel
└─ Thunderbird 没有而产品真正需要的少量工作逻辑

WordPress
└─ 独立输出模块
```

## 3. “自行设计”必须有举证责任

以后准备新增以下任何东西之前：

- 数据库；
- 状态模型；
- 同步层；
- Task/Event 选择器；
- 日期解析器；
- UI；
- API；
- 后台服务；
- IPC；
- 缓存/冲突系统；
- 新框架或新抽象；

必须先回答：

1. **标准已经有吗？**
2. **Thunderbird / WordPress / CalDAV 宿主已经有吗？**
3. **成熟开源产品已经有吗？**
4. **成熟库已经有吗？**
5. **能否直接复用、组合或做薄封装？**
6. **真正缺失的最小部分是什么？**

只有前面的方案都不合适，才自行设计。

即使必须自行设计，也只设计缺失的部分，而不是重造整个体系。

## 4. “学习现有积木”是开发的必经步骤

开发前的调查不是可选工作。

应主动研究：

- Thunderbird 的公开 API、扩展能力和必要时的内部实现；
- CalDAV / iCalendar 标准；
- Radicale；
- 成熟 CalDAV/iCalendar 库；
- 其他成熟开源 Calendar / Task / CalDAV 客户端和 CLI 工具；
- WordPress REST/API/现有成熟能力；
- 当前仓库里已经存在的模块。

用户不应该负责指出所有可复用的轮子。

开发者/Assistant 应主动寻找、阅读、比较并选择这些积木。

## 5. 复用优先级

默认顺序：

```text
直接使用现有能力
→ 组合现有能力
→ 薄封装
→ 薄适配层
→ 移植成熟实现
→ 参考成熟实现
→ clean-room 重写
→ 最后才从零设计
```

目标不是“原创代码比例高”。

目标是：

> **以最少的新代码，组合出可靠、可维护、真正能用的软件。**

## 6. 开源许可证不是默认拒绝复用的理由

本项目为 GitHub Public 项目。

因此不应为了假想的闭源商业化需求，默认重写已经存在的成熟开源实现。

实际流程应该是：

```text
发现成熟实现
→ 检查 LICENSE
→ 兼容：按许可证要求直接复用/修改/移植
→ 不兼容：寻找替代实现
→ 确实没有合适选择：再考虑 clean-room
```

常见许可证只需要按各自条款处理：

- MIT / BSD：通常保留版权与许可证声明；
- Apache-2.0：遵守许可证、NOTICE/专利相关要求；
- MPL / LGPL：按文件级或库级义务处理；
- GPL：如果项目选择兼容 GPL 的发布方式，则按 GPL 履行源码和许可证义务。

**是否商业化不是判断能否复用的核心；LICENSE 才是。**

公开仓库也不等于“没有许可证就能随便复制”，因此仍必须检查来源和许可证。

## 7. CLI 的教训

早期 CLI 曾试图承担过多职责，包括：

- Task/Event 选择与编辑；
- Menu / Prompt；
- Session 上下文；
- Background Service；
- IPC；
- Offline cache；
- 冲突处理；
- 智能 Next；
- Extension runtime。

其中很多能力不是技术上绝对无法实现，而是：

- 与 Thunderbird 已有能力重复；
- 为个人规模项目带来过高复杂度；
- 缺少足够明确的产品规则；
- 需要维护跨平台后台、并发和同步一致性。

今后 CLI 只在有明确、独立、真实需求时实现功能。

不得因为“架构上看起来完整”而实现一整套新的 Task 管理系统。

## 8. PR 原则

“小步开发”不等于“每个小步都开一个 PR”。

对单一开发者/个人项目，优先：

```text
一个明确功能
→ 一个工作分支（需要时）
→ 在该分支持续修到真实验收通过
→ 一个 PR（需要审查/隔离时）
→ merge
```

文档、小型安全修改等不需要为了流程本身制造额外 PR。

PR 数量不是开发质量指标。

## 9. 真实验收仍然必须保留

复用现有实现不代表降低可靠性要求。

真实修改继续遵守：

```text
write
→ read back
→ compare
→ receipt
```

同时继续坚持：

- 真实 Thunderbird / CalDAV 环境验收；
- 不以 mock/test-only 结果代替用户路径验收；
- WordPress 故障不得阻塞 Thunderbird / CalDAV 主工作流；
- 不因为复用第三方代码而跳过边界测试。

## 10. 最终原则

以后开发默认遵循：

> **先学习，先复用，后设计。**

> **已有积木能解决的问题，不重新发明。**

> **Thunderbird 已经做好的，让 Thunderbird 做。**

> **CalDAV 标准已经表达的，不另造私有事实源。**

> **成熟开源实现能合法复用的，优先复用。**

> **许可证不合适时，才考虑替代实现或 clean-room。**

> **自行设计只针对真正缺失的最小部分。**

> **简单、可用第一位。**

> **最少的新代码完成可靠功能。**
