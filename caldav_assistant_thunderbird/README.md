# CalDAV Assistant Thunderbird 0.4.2

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
