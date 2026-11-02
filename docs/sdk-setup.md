# 鸿蒙开发环境与构建记录

2026 年 11 月 2 日已接入用户提供的 `D:\Huawei\DevEco Studio`，并使用其中的 API 26 SDK 编译成功。随后使用用户在 IDE 中生成的调试签名，在已连接的 API 26 手机上安装和启动成功。该目录已经包含目标 SDK，无需重新下载安装。

| 工具 | 已验证版本 | 实际来源 |
| --- | --- | --- |
| DevEco Studio | 26.0.0.865 | `D:\Huawei\DevEco Studio` |
| HarmonyOS SDK | API 26 / 26.0.0.105 / Release | Studio 的 `sdk/default` |
| Hvigor 与 HarmonyOS 插件 | 6.26.9 | Studio 的 `tools/hvigor` |
| Node.js | 24.14.1 | Studio 的 `tools/node` |
| JetBrains Runtime JDK | 25.0.2 | Studio 的 `jbr` |
| 华为 DevEco CLI | 1.3.10 | `data/private/toolchains/deveco-cli` |

SDK 版本依据安装包内 `sdk/default/openharmony/ets/oh-uni-package.json` 及工具链元数据核对。工程的 compile、compatible、target SDK 版本与 Hvigor 模型版本使用 `26.0.0`，不填写系统名称 `7.0.0`。

构建脚本优先使用已登记 Studio 自带的 Node 与 JDK。此前下载并核对过官方 SHA-256 的 Node 24.14.1、Temurin JDK 21.0.13+9 仍保留在项目私有目录，作为工具链未提供运行时时的备选；未改动系统全局 Node 或 Java。

## 在当前电脑复现

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 doctor -ToolchainRoot 'D:\Huawei\DevEco Studio'
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 check
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 build
```

`doctor` 验证运行时和 CLI，并将工具链路径保存到忽略入库的 `data/private/toolchains/sdk-install.json`。后续调用无需重复指定 `-ToolchainRoot`。构建时只在子进程中配置环境变量，不写系统环境；Hvigor 与 ohpm 会正常写入用户缓存。

新克隆仓库时，还需安装 CLI 并创建本机构建配置：

```powershell
& 'D:\Huawei\DevEco Studio\tools\node\npm.cmd' install --prefix data/private/toolchains/deveco-cli --no-audit --no-fund @deveco/deveco-cli@1.3.10
if (-not (Test-Path apps/harmony/build-profile.json5)) {
    Copy-Item apps/harmony/build-profile.json5.example apps/harmony/build-profile.json5
}
```

实际 `build-profile.json5`、本机路径、证书、下载包、缓存和构建产物均已忽略入库。现有配置可能包含自己的签名信息，保留该文件，不直接覆盖。

## 已验证结果

- `doctor`：退出码 0，使用 Studio 自带 Node 24.14.1 和 JBR 25.0.2，识别 API 26。
- `check`：5 个 ArkTS 文件，0 错误、6 条提示。
- `build`：`BUILD SUCCESSFUL`，签名关联修复后生成 `entry-default-signed.hap`。
- SSE 回归：4 项通过，涵盖中文 UTF-8 分包、CRLF、多行事件、不完整和超长帧。
- HAP 校验：ZIP 完整性通过，包含模块清单、`ets/modules.abc`、资源及 SDK 信息。
- 真机安装：`hdc install` 返回 `install bundle successfully`。
- 真机启动：手机解锁后 `aa start -a EntryAbility -b com.djw0514.emotionalrobot` 返回 `start ability successfully`。

用于手机安装的产物：`apps/harmony/entry/build/default/outputs/default/entry-default-signed.hap`。

同目录还会生成 `entry-default-unsigned.hap`，该包不能直接安装到手机。调试签名包、证书与签名配置只保存在本机，不提交 GitHub。

检查器对网络请求报告权限提示，已核对清单及 HAP 中存在 `ohos.permission.INTERNET`；另有 4 处平台 API 异常处理提示。网络调用由上层页面捕获错误，Preferences 初始化调用带有失败回调。构建器另对模块包版本 `0.1.0` 给出警告：其当前校验规则要求主版本从 1 开始；保留原型版本，未影响 HAP 生成。

## 自动签名与构建关联

手机安装时报 `9568320 / no signature file` 时，先看正在安装的文件名。本次失败的包是 `entry-default-unsigned.hap`；本机证书文件已生成，但 `app.products` 中的 `default` 未选择签名配置。

新电脑按以下顺序配置：

1. 手机开启开发者模式和 USB 调试，连接电脑并同意调试授权，确认 `hdc list targets` 能列出设备。
2. 在 DevEco Studio 打开 `apps/harmony`，进入 File > Project Structure > Signing Configs，使用自己的开发者账号自动生成 `default` 调试签名。
3. 到 Project/Product 选择 `default`，将 Signing Config 设为已生成的 `default`，点击 Apply / OK。对应本机 `build-profile.json5` 中 `app.products` 的 `default` 对象需要有 `"signingConfig": "default"`；保留 IDE 已生成的 `app.signingConfigs` 及其中的证书配置。
4. 同步项目并重新构建，确认输出中出现 `entry-default-signed.hap`。
5. 在 IDE 选择手机运行应用。手机需保持解锁亮屏；锁屏时启动可能报 `10106102`，解锁后重试即可。

本次已完成上述步骤，安装与启动均成功。后续只需沿用本机配置；新克隆的仓库不包含个人证书，仍需自行生成并关联签名。

## 下一步：手机业务联调

1. 启动本地后端，在客户端输入局域网服务地址与应用连接口令，核对聊天、跨会话召回、记忆确认、纠错和删除。
2. 验证切后台、断网、停止回复、重连、中文增量显示和文字选择；真实 DeepSeek 调用需在后端本机配置 Key。

安装与启动通过说明签名及应用入口可用，业务流程和异常场景仍须在目标 HarmonyOS 7 手机上验证。
