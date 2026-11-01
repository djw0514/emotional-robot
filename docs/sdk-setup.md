# 鸿蒙开发环境安装状态

项目的 `main` 分支已推送到 GitHub。当前已在项目私有目录中安装以下构建前置工具：

| 工具 | 已验证版本 | 保存位置 |
| --- | --- | --- |
| Node.js | 24.14.1 | `data/private/toolchains/node-v24.14.1-win-x64` |
| Eclipse Temurin JDK | 21.0.13+9 | `data/private/toolchains/jdk-21.0.13+9` |
| 华为 DevEco CLI | 1.3.10 | `data/private/toolchains/deveco-cli` |

Node 和 JDK 下载包均核对了其官方发行元数据中的 SHA-256。安装目录和元数据均已忽略入库，系统现有的 Node 和 Java 不变。

HarmonyOS API 26 SDK 本体尚未安装。华为官方下载页的当前下载接口要求已登录的开发者会话，当前工具会话没有该登录状态；公开镜像目录中的旧版 SDK 不能代替 API 26。

## 完成 SDK 安装

1. 在[华为官方下载页](https://developer.huawei.com/consumer/cn/download/)登录开发者账号。
2. 下载 Windows 版 Command Line Tools for HarmonyOS，选择 API 26 对应发行版；也可下载配套 DevEco Studio。不要选择 DevEco Device Tool 或旧版 OpenHarmony SDK。
3. 提供压缩包的本机完整路径，即可继续由助手解压、核对 SDK 元数据并配置工具链。
4. 解压后的工具链根应包含 `sdk/default`，并带有配套 Hvigor。安装包内的实际版本名是配置工程版本的依据。

## 检查与构建入口

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 doctor
# 安装包就绪并解压后，登记工具链根目录
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 doctor -ToolchainRoot 本机工具链根目录
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 check
powershell -ExecutionPolicy Bypass -File scripts/harmony.ps1 build
```

`doctor` 在 SDK 缺失时返回退出码 2，只有前置运行时就绪不能视为 SDK 安装完成。当前 SDK 注册逻辑与 HAP 构建仍需安装包到位后验证。
