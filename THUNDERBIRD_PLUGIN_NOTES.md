# CalDAV Assistant Thunderbird 插件维护说明

> 这是仓库级开发约束，用来避免再次混淆旧 Thunderbird 集成线与当前主力插件。

## 1. `integrations/thunderbird/manifest.json` 的版本号不是主力插件版本

当前仓库历史代码中存在：

```text
integrations/thunderbird/manifest.json
version = 0.1.7
```

这个 `0.1.7` 属于较早的 Thunderbird Integration / Native Host / Python bridge 开发线。

**禁止仅根据这个 manifest 的版本号，把 `0.1.7` 判断为当前
`caldav_assistant_thunderbird` 主力插件的“最新版”。**

以后回答、发布、打包、安装或升级 Thunderbird 插件前，必须先确认：

1. 当前主力 `caldav_assistant_thunderbird` 的 canonical source 在哪里；
2. 主力插件自己的 manifest / release metadata 的版本；
3. 该构建是否来自当前主力插件代码，而不是 legacy integration 目录；
4. 不能因为 `caldav_assistant_skeleton/main` 里的 legacy manifest 版本更低，
   就把用户从较新的插件版本降级到 `0.1.x`。

如果 canonical 插件版本与 legacy `integrations/thunderbird/manifest.json`
发生冲突，**以 canonical `caldav_assistant_thunderbird` 插件版本为准**。

## 2. `caldav_assistant_thunderbird` 必须归属于本仓库

`caldav_assistant_thunderbird` 是 CalDAV Assistant 的主力 Thunderbird 用户界面，
不应作为一个与 Core 脱节的独立产品线维护。

它的源码、测试、构建、版本记录和发布流程应该放在：

```text
ZhouAndrew/caldav_assistant_skeleton
```

仓库内部。

也就是说，产品结构应理解为：

```text
caldav_assistant_skeleton
├── caldav_assistant/                 # Core / service / public API / fallback CLI
├── caldav_assistant_thunderbird/     # 主力 Thunderbird 插件（canonical）
├── integrations/
│   └── thunderbird/                  # 旧 integration 代码；迁移完成前视为 legacy
├── tests/
└── ...
```

上面的目录名表达的是**仓库归属和 canonical 责任边界**。
如果实际迁移采用别的仓库内子目录，也必须满足同一个原则：
`caldav_assistant_thunderbird` 与 Core 在同一个 `caldav_assistant_skeleton`
仓库中共同版本管理、测试和发布。

**不要再创建或依赖一个脱离 `caldav_assistant_skeleton` 的独立主仓库，
让插件和 Core 版本线各自漂移。**

## 3. 产品主次关系

日常用户路径应以 Thunderbird 插件为主：

```text
Thunderbird / caldav_assistant_thunderbird
        ↓
Thunderbird Calendar / Tasks API + CalDAV Assistant Core
        ↓
CalDAV / WordPress
```

CLI 的定位是：

- 安装；
- 诊断；
- 修复；
- 开发验收；
- emergency fallback。

CLI 不是判断 Thunderbird 插件版本的来源，也不应重新成为普通用户的主入口。

## 4. 发布/合并检查

任何涉及 Thunderbird 插件的“最新版”“发布”“合并所有更新”任务，在宣布完成前必须检查：

- canonical `caldav_assistant_thunderbird` 版本；
- legacy `integrations/thunderbird` 是否只是历史代码；
- 是否错误地把旧 `0.1.x` XPI 当成主力插件；
- 插件源码是否仍位于 `caldav_assistant_skeleton` 仓库内；
- 插件与 Core 的 human-path / interactive acceptance 是否一起通过。

这条规则的目的不是冻结具体实现，而是防止**版本线和产品线识别错误**。


## 5. Canonical source 已归位

截至 2026-10-02，当前主力插件 **CalDAV Assistant Experimental 0.3.15**
已经归位到本仓库：

```text
caldav_assistant_thunderbird/
```

迁移来源是先前开发仓库 `ZhouAndrew/thunderbird-taskfix` 的
`fix/caldav-assistant-switch-restore-incomplete-0.3.15`，
已测试 head 为 `81ba6042271e31857c46a50aadeec67bf82267cd`。

从此以后，Thunderbird 主力插件的新版本应从
`caldav_assistant_skeleton/caldav_assistant_thunderbird/addon/manifest.json`
判断和发布。旧 `integrations/thunderbird/` 继续视为 legacy。
