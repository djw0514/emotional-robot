# 鸿蒙开发环境与构建记录

2026 年 11 月 2 日已接入用户提供的 `D:\Huawei\DevEco Studio`，并使用其中的 API 26 SDK 编译成功。该目录已经包含目标 SDK，无需重新下载安装。

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
- `build`：`BUILD SUCCESSFUL`，生成未签名 debug HAP。
- SSE 回归：4 项通过，涵盖中文 UTF-8 分包、CRLF、多行事件、不完整和超长帧。
- HAP 校验：ZIP 完整性通过，包含模块清单、`ets/modules.abc`、资源及 SDK 信息。

产物路径：`apps/harmony/entry/build/default/outputs/default/entry-default-unsigned.hap`。

本次产物大小为 128680 字节，SHA-256：`09ae3d9b48fcd3b3f49a805e6da3f46775ba2be51d96692c90b79ac43b256244`。重新构建后请以实际文件为准。

检查器对网络请求报告权限提示，已核对清单及 HAP 中存在 `ohos.permission.INTERNET`；另有 4 处平台 API 异常处理提示。网络调用由上层页面捕获错误，Preferences 初始化调用带有失败回调。构建器另对模块包版本 `0.1.0` 给出警告：其当前校验规则要求主版本从 1 开始；保留原型版本，未影响 HAP 生成。未配置签名的提示符合当前未签名构建用途。

## 下一步：签名与手机联调

`hdc list targets` 当前返回 `[Empty]`，尚无设备连接。未签名 HAP 不能直接安装到手机。

1. 在 DevEco Studio 打开 `apps/harmony`，登录自己的华为开发者账号，在 Signing Configs 配置调试签名。
2. 手机开启开发者模式和 USB 调试，连接电脑并同意调试授权，确认 `hdc list targets` 能列出设备。
3. 在 IDE 选择该手机运行应用，完成签名构建和安装。
4. 启动本地后端，在客户端输入局域网服务地址与应用连接口令，核对聊天、跨会话召回、记忆确认、纠错和删除。
5. 验证切后台、断网、停止回复、重连、中文增量显示和文字选择；真实 DeepSeek 调用需在后端本机配置 Key。

构建成功说明源码与所用 SDK 能完成编译打包，运行时行为仍须在目标 HarmonyOS 7 手机上验证。
