# CalDAV Assistant Thunderbird 0.4.2 — 正式整合版验收

**安装包完成：PASS。最终准确安装包的真实验收：PASS。**

- 文件：`caldav-assistant-thunderbird-0.4.2-20261005T090627Z-bb8c684b828b46b3a4cdba3bdd62a91e.xpi`
- 唯一 Build ID：`20261005T090627Z-bb8c684b828b46b3a4cdba3bdd62a91e`
- SHA-256：`254314340f4cd4b33f4c60eba5b4d041b27ff36a2db358dc71f5a0eb688c46d4`
- 源码提交：`5ae563e24868e1454fcc6ca564ad78e707afbdaf`（干净工作树）
- 分支：`integrate/wordpress-verified-release`
- 原生 add-on ID 保持 `ZhouAndrew.thunderbird-taskfix-lab@addons.thunderbird.net`，用于覆盖升级 0.4.1。
- GitHub 源码发布：**未推送、未合并**。自动审批拒绝远程推送，理由是当前请求未明确授权发布源码到该远程仓库。安装包交付与此分开。

## 集成结果

已把独立 WordPress 0.3.3 已验收行为接入正式插件：双 transport、按 origin 保存本地 TLS 授权、全部候选列举、同日多文章明确选择、保存后重启恢复、持久 Outbox、完整正文/标题/状态读回比较、标记幂等和冲突拒绝。

手动日志及附件在网络写入之前进入 Outbox；不静默丢弃超出 500 条的记录。重试保存原日期、时间和时区。已经上传的附件保存 checkpoint 并检查所属文章。

自动日志从已验证的 VTODO DESCRIPTION 闭合 session 派生，先持久排队，网络发送独立运行。WordPress receipt 使用独立位置，后台发送不会覆盖工作操作 receipt。审计及队列写入分别串行化。

原生 Tasks 工具栏 Start、唯一 currentWorkId、Start/Stop/Complete/Cancel、纯函数核心和任务 write/read-back/compare 保持通过。没有新建 Work VEVENT 或第二套 Task 状态。

## 准确包的测试环境

本次为独立真实环境测试，不是用户原有 andrew.local 数据库：

- Thunderbird：153.1.0 ESR，真实安装未修改的最终 XPI，Marionette 操作原生 Tasks/工作页/设置页/记录页。
- Radicale：3.8.1，真实 CalDAV Task/VTODO 和服务器读回。
- WordPress：7.1.2，真实 PHP 8.3.6 + MariaDB 10.11.14。
- WP-CLI：WP-CLI 2.12.0。
- REST：真实 Application Password 与本地自签名 HTTPS；确实执行明确授权的 TLS 跳过。

## 验收结果

`npm test`：严格 TypeScript、typed/core、全部 adapter/workflow/native-toolbar/WordPress harness、最终 XPI contract、唯一 build ID 和相同 ID 字节重现均通过。

真实 Thunderbird/CalDAV：30 项通过。包括 native selection 0/1/>1、TOCTOU、四 Action、循环 occurrence、currentWorkId、重启、离线拒绝误报成功、WordPress 真实不可用时的失败隔离、禁用/重启用/卸载清理。

WordPress 设置页“完整读写测试”一次运行两条路径，不受 Transport 下拉框限制；在两种所选 transport 下均真实执行。下面为正式 UI 与真实服务检查：

| 检查 | 结果 |
|---|---|
| XPIInstall | PASS |
| wp-cli connection | PASS |
| wp-cli full read/write/media/cleanup | PASS |
| wp-cli real manual log + same day | PASS |
| application-password connection | PASS |
| SelfSignedTLS | PASS |
| application-password full read/write/media/cleanup | PASS |
| application-password real manual log + same day | PASS |
| Ambiguous4Retained | PASS |
| ExplicitSelection4Recovered | PASS |
| RealOutageRetained | PASS |
| OutboxSurvivesThunderbirdRestart | PASS |
| RealRecoveryRetry | PASS |
| NoDuplicateOnRecovery | PASS |
| OriginalDateRetained | PASS |
| RealNativeActionsAutomaticWordPressOutput | PASS |

在线自动输出另以同一准确 XPI 跑完真实 Task 主线：关闭的 **5 个 session 全部写入同一选定 WordPress 文章，标记各出现一次**。Outbox 已确认发送，其他同日候选正文未变化。

## 安装

Thunderbird → 附加组件和主题 → 齿轮 → 从文件安装附加组件 → 选择本次唯一命名的 XPI → 重启。

打开 WordPress 设置，核对现有连接。需要本地自签名 HTTPS 时勾选授权并保存；点击“WP-CLI + REST 完整读写测试”。已有多候选 Outbox 时点击重试，选择目标文章，再使用所选文章并重试。

独立 `caldav-wordpress-test-0.3.3.xpi` 不再是使用此正式模块的必要组件。没有读取或改动用户原有 WordPress/Thunderbird 数据。

## 永久打包规则

所有新包必须有唯一构建标识，同时出现在文件名与包内 `build-info.json`；元数据含源码提交与源码摘要，最终包另附 SHA-256。不得覆盖旧包，插件安装 ID 则保持稳定以便升级。规则已写入项目 AGENTS.md、打包脚本及回归测试。重现已有 ID 仅用于完全相同字节的复现，禁止用于不同的新发布内容。
