# CalDAV Assistant Thunderbird 0.4.5 (Post preview fix test release)

正式整合版。Thunderbird 153.0.2–153.1.x；保持原安装 ID，可覆盖升级 0.4.1。

Task 只从 Thunderbird 原生 Tasks UI 选择，工具栏 Start 位于 Mark Completed 旁。Work 提供 Stop、Complete、Cancel；currentWorkId 是唯一当前工作指针。核心是 pure functional core + thin effect boundary。Task/Event 事实归 Thunderbird/CalDAV，任务修改遵循 write → read back → compare → receipt。工作历史保存于 VTODO DESCRIPTION，不新建 Work VEVENT 或第二套 Task 状态库。

WordPress 0.3.3 的已验收行为已正式整合：WP-CLI 和 Application Password REST、按 origin 保存的本地 TLS 授权、同日多文章明确选择、持久目标与 Outbox、附件 checkpoint、原日期保留、完整读回比较、marker 幂等与冲突拒绝。自动日志从已验证的 closed session 派生并持久排队。网络发送及 WordPress receipt 独立，不阻塞或回滚四 Action。

详见 [WordPress 集成说明](WORDPRESS-INTEGRATION-0.4.2.md) 与 [正式发布验收及包身份](acceptance/0.4.2/README.md)。旧 Native Host/Python 实验线不是此正式插件。

## 安装

Thunderbird → 附加组件和主题 → 齿轮 → 从文件安装附加组件 → 选择正式 0.4.2 XPI → 重启。独立 caldav-wordpress-test 插件不是必要组件。

## 开发验证和打包

```bash
cd caldav_assistant_thunderbird
npm ci
npm test
bash packaging/build-xpi.sh
```

每次新构建使用新的唯一 Build ID；不得覆盖已有包。复现旧 ID 仅允许用于完全相同字节的验证。已经真实验收的准确发布包保持原样，发布文档和 CI 的修复不改变该包。

## 0.4.3：原生 Thunderbird 外部状态同步修复

当 Thunderbird 原生 Tasks 中唯一当前 VTODO 变为 `COMPLETED` 或 `CANCELLED`，插件通过任务变更事件、启动以及再次进入 Work 页面触发权威回读；只有身份与 `currentWorkId` 相同，且指针在回读后未变化，才将指针写为 `null` 并回读验证，留下系统审计回执。不会改写 Task、本来已有的 DESCRIPTION 或其历史 session；也不会把外部取消伪装为插件 Complete。

如果刚好点击插件 Complete/Stop，则工作操作返回冲突失败，但已结束的任务可以经验证解除失效指针。离线、任务不存在、非终态或身份冲突时不会清除指针。修复不修改已发布的 0.4.2 XPI。

自动化测试及 CI 构建并不等于已在用户 Thunderbird 环境完成真实安装验收。

## 0.4.4：已验收的 Quick Capture 与独立 Post 预览合并

`feat/work-quick-capture` 的 Quick Capture（文字、图片、文件剪贴板粘贴及文件拖放）及独立只读 Post iframe 预览已经整合到主线，同时保留主线 0.4.3 的 Thunderbird 原生任务终态 `currentWorkId` 对账修复。旧版实验分支的独立实机验收证据保留在 `acceptance/0.4.4/independent-preview/`。此合并改变了 XPI 源码，旧包的实机验收不能自动等同于合并后安装包的实机验收；正式发布前须再进行构建和回归。

## 0.4.5：WordPress Post 正文末尾预览修复（测试发布）

- 使用 WordPress REST `link` 或 WP-CLI `wp post url <ID>` 获取真实永久链接；不再把 WP-CLI 的 `guid` 当作 Post URL。
- 跨域 iframe 使用独立 Thunderbird PostPreview actor，将 **文章内容的末尾** 滚动到可视范围，不再滚动到整个网站的页脚。
- 允许 WordPress 将预览地址规范化重定向到同源 permalink；未找到文章正文则明确报告错误，不再静默滚动到底部。
- 包含 URL 和滚动目标的自动化回归测试，保持 Task 原生选择、四操作、`currentWorkId`、Quick Capture 不变。
- 这是新的独立测试包；不覆盖、也不重新声称 0.4.2 正式实机验收。用户 Thunderbird 实机回归需要单独完成。
