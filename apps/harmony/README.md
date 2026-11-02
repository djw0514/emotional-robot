# 心伴鸿蒙客户端运行指引

目标系统为 HarmonyOS 7.0.0，工程配置采用 API 26。华为官方页面将 HarmonyOS 7 标为 API 26。[华为开放能力说明](https://developer.huawei.com/consumer/cn/harmonyos-ai)

当前已提供原生 ArkTS 页面、Stage UIAbility、清单、资源与构建配置。聊天、历史会话、记忆确认和纠错、来源、版本、删除及连接设置均调用真实后端接口。2026 年 11 月 2 日已用本机 API 26 SDK 编译、调试签名，并在 API 26 手机上安装和启动成功；聊天与记忆操作仍待手机联调。

## 构建与安装

1. 使用已安装的 `D:\Huawei\DevEco Studio`，其中已包含 API 26 SDK。本机无需重新下载；其他电脑可从[华为官方下载页](https://developer.huawei.com/consumer/cn/deveco-studio/)安装配套版本。
2. 用 IDE 打开本目录，复制 `build-profile.json5.example` 为 `build-profile.json5`。当前工作区已经准备该文件。
3. 同步工程。当前已验证 `compileSdkVersion`、`compatibleSdkVersion`、`targetSdkVersion` 和工具链 `modelVersion` 均使用 `26.0.0`，配套 Hvigor 为 6.26.9。这里填写 SDK 的版本名称，不填系统营销名称 `7.0.0`。
4. 手机开启 USB 调试并连接电脑，在 Signing Configs 自动生成自己的调试签名。再到 Project/Product 选择 `default`，将其 Signing Config 设为已生成的 `default`，点击 Apply / OK。仅生成证书而未关联构建，仍会得到未签名包。实际 `build-profile.json5` 已忽略入库，避免签名资料进入仓库。
5. 同步依赖，执行 Build HAP，然后安装到已开启开发者模式的手机。
6. 打开设置页，填写后端地址及本应用的连接口令，连接后开始聊天。

本仓库没有附带私有证书或 IDE 的二进制构建工具。签名成功后用于安装的包是 `entry/build/default/outputs/default/entry-default-signed.hap`；同目录的 `entry-default-unsigned.hap` 不能直接安装到手机。在项目根目录运行以下命令可复现检查和构建；CLI 首次安装步骤及版本记录见[SDK 安装记录](../../docs/sdk-setup.md)。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 doctor -ToolchainRoot 'D:\Huawei\DevEco Studio'
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 check
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 build
```

## 手机连接后端

在同一局域网联调时，后端以 `--host 0.0.0.0` 启动，手机填电脑的局域网地址，例如 `http://192.168.1.10:8000`，并根据本机防火墙规则允许该端口。手机中的 `127.0.0.1` 指向手机本身，不是开发电脑。

公网服务使用 HTTPS；客户端仅允许回环和私网地址使用 HTTP 联调。默认演示口令来自后端 `.env` 的 `ROBOT_DEMO_TOKEN`，正式用户使用 `robot create-user` 签发的独立口令。此处不填写 DeepSeek Key。

若 SDK 的网络安全策略拒绝本地 HTTP，使用可访问的 HTTPS 开发入口，或按所选 SDK 文档设置仅限调试的网络策略，不关闭 TLS 证书校验。

## 本轮客户端取舍

- 口令仅保存在进程内存，服务地址通过 Preferences 保存；重新打开需重新输入口令。
- 会话和记忆以服务端为准，端侧不保存聊天正文；离线阅读与加密缓存尚未实现。
- DeepSeek 新记忆显示为待确认，确认后才进入长期召回。
- 删除会展示影响范围，先停止使用，再等待后台清理。版本、来源和列表在成功后刷新。
- 停止回复会销毁当前流请求；服务端中断或上下文变化会作为错误处理，不显示完成。
- 当前会话列表最多读取 100 条，记忆页最多读取 200 条；更大规模的分页界面留到后续。

客户端网络适配依据平台的 `requestInStream`、`dataReceive` 与增量 TextDecoder API；纯 SSE 分帧模块通过 Node 测试，平台网络回调时序仍须真机核实。[网络 API](https://github.com/openharmony/docs/blob/master/en/application-dev/reference/apis-network-kit/js-apis-http.md)
