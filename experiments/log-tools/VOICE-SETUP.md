# 离线日志语音输入

1. 在腾讯云开通 ASR，准备 AppID、SecretId 和 SecretKey。
2. 在 WordPress 的 `wp-config.php` 中加入以下三行，把示例值换成自己的值。

   ```php
   define('OFFLINE_LOG_ASR_APP_ID', '你的 AppID');
   define('OFFLINE_LOG_ASR_SECRET_ID', '你的 SecretId');
   define('OFFLINE_LOG_ASR_SECRET_KEY', '你的 SecretKey');
   ```

3. 将 `offline-log-asr.php` 放进 WordPress 的 `wp-content/plugins/`，然后在插件列表启用「Offline Log Tencent ASR」。
4. 在编辑器的「WordPress 连接」填写 HTTPS 地址、用户名和应用密码。该用户需要编辑文章权限。
5. 点输入栏的麦克风并允许录音。看到「正在听」后说话，结束时再点一次。可以修改识别文字，再点「添加」。

语音通过 WebSocket 直接传给腾讯云。WordPress 只签发连接。此版本使用腾讯云普通话模型 `16k_zh`，一次录音最多 60 秒。浏览器若限制本地文件使用麦克风，可以用 WordPress 同站的 HTTPS 地址打开编辑器。文字编辑仍可以离线使用。

[腾讯云实时语音识别接口](https://cloud.tencent.com/document/product/1093/48982)
