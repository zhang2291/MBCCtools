<!-- markdownlint-disable MD033 MD041 -->
<div align="center">

<img alt="LOGO" src="https://github.com/quietlysnow/MBCCtools/blob/main/resource/base/image/logo.jpg" width="256" height="256" />

# MBCCtools
 
基于MaaFramework的 无期迷途 小助手。图像技术 + 模拟控制，解放双手！  
由 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 强力驱动！
</div>

## ⚠️ Fork 说明

> 本仓库是 [quietlysnow/MBCCtools](https://github.com/quietlysnow/MBCCtools) 的个人 Fork。项目主体、GUI 打包方案及原始功能均来自上游项目。
>
> 本仓库仅针对个人设备和使用习惯调整了部分任务逻辑，仅供个人本地使用与测试，不代表上游官方版本，也不承诺适用于其他环境或提供用户支持。
>
> 如需通用版本、完整文档或问题反馈，请优先访问[上游仓库](https://github.com/quietlysnow/MBCCtools)，并遵守上游项目的开源许可证。

## 📖 项目说明

本项目基于 [MACC](https://github.com/mxia9416/MACC) 项目开发，因原项目长期未更新且无法联系作者，故重新编写此项目，开发过程中参考了 MACC 的设计思路。

本项目主要使用 Pipeline 低代码方式实现，欢迎各位开发者指导交流。

> ⏰ 项目为个人业余时间开发，随缘更新。发现的 Bug 会找时间修复，建议及时更新最新版本。

### 已实现功能
- **游戏启动**：关闭广告、禁闭者情绪检测
- **秘盟捐赠**
- **好友点数**
- **日常奖励**：监管奖励、免费礼包、体力领取
- **每日派遣**：可选区域
- **体力扫荡**：浊暗之阱、记忆风暴、淘金狂热、恶兆之种、极域搜寻、禁区探查、帕尔马废墟
- **刷取材料**：在秘金盛宴 N3/N4 刷取对应材料
- **监察密令奖励**
  

## 使用说明

- 上游正式版本：<https://github.com/quietlysnow/MBCCtools/releases>
- 本 Fork 的个人构建（如有）：<https://github.com/zhang2291/MBCCtools/releases>

#### Windows 用户
- **绝大多数用户**：下载 `MBCCtools-win-x86_64.zip`
- **ARM 架构用户**：下载 `MBCCtools-win-aarch64.zip`  
  ⚠️ 注意：Windows 设备绝大多数为 x86_64 架构，除非明确知道自己的设备是 ARM 架构，否则请选择 x86_64 版本
- 解压后运行 .exe 文件。
- 本人没有用过macos,无法给出使用指南。

## 注意事项

**应用程序错误**：通常缺少运行库，请安装 [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) 以及 [.NET 10.0](https://dotnet.microsoft.com/en-us/download/dotnet/10.0)
- **兼容性**：基于 MuMu模拟器5，2560×1440（280DPI）平板版开发
- **分辨率建议**：
  - 1280×720 (240DPI)：MAA 原生支持，兼容性最佳
  - 如遇问题可尝试切换至 720p 分辨率

## 🔧 编译说明

> 以下为本 Fork 当前实际使用的构建方式。普通用户直接下载 Release 即可。

### 目录建议

建议三个源码仓库放在同一级目录，方便桌面版和 Android 版一起维护：

```text
D:\a-maa-dev\
├─ MBCCtools
├─ MFAAvalonia
└─ MaaFwApp
```

其中 `MFAAvalonia` 用于 Windows GUI，`MaaFwApp` 用于 Android GUI。后续可以正常 `git pull/fetch` 更新；各仓库生成的 `bin`、`obj`、`build` 目录都可以安全删除，需要时重新构建即可。

### 1. 准备 MBCCtools / MaaFramework

克隆本项目：

```powershell
git clone --recursive https://github.com/zhang2291/MBCCtools.git
cd MBCCtools
```

从 [MaaFramework Releases](https://github.com/MaaXYZ/MaaFramework/releases) 下载对应 Windows 包并解压到 `deps`，确认至少存在：
```text
deps\bin
deps\share\MaaAgentBinary
```

可先单独生成资源安装目录：

```powershell
python .\install.py v1.4.3-local.1
```

生成内容位于 `install\`。

### 2. 构建 Windows 桌面版

本 Fork 的桌面版包含对 MFAAvalonia 的本地修改以及内置 MaaPipelineEditor，因此推荐从修改后的 MFAAvalonia 源码构建，而不是直接下载官方 GUI 覆盖。

环境要求：

- Windows 10/11 x64
- .NET 10 SDK
- Python 3
- 已准备好的 `MBCCtools\deps`
- 同级目录中的修改版 `MFAAvalonia` 源码

先构建 MFAAvalonia：

```powershell
cd D:\a-maa-dev\MFAAvalonia
dotnet publish .\MFAAvalonia.Desktop\MFAAvalonia.Desktop.csproj -c Release -r win-x64
```

当前 publish 输出通常位于：

```text
D:\a-maa-dev\MFAAvalonia\bin\AnyCPU\Release\win-x64\publish
```

然后回到 MBCCtools 根目录组装最终桌面目录：

```powershell
cd D:\a-maa-dev\MBCCtools
.\build_local_gui.ps1 `
  -BaseDir "D:\a-maa-dev\MFAAvalonia\bin\AnyCPU\Release\win-x64\publish" `
  -OutDir "D:\a-maa-dev\MBCCtools\build-local-final" `
  -Version "v1.4.3-local.1"
```

首次全新组装后，再把本仓库内置的 MaaPipelineEditor 运行时复制到最终目录：

```powershell
New-Item -ItemType Directory -Force .\build-local-final\tools | Out-Null
Copy-Item .\tools\MaaPipelineEditor .\build-local-final\tools\MaaPipelineEditor -Recurse -Force
```

最终直接运行：
```text
D:\a-maa-dev\MBCCtools\build-local-final\MFAAvalonia.exe
```

修改 `resource`、Pipeline 或 `interface.json` 后，可以重新执行上述组装命令。`build-local-final` 是本地运行目录，不需要提交到 Git。

### 3. 构建 Android 版

Android 版基于修改后的 [MaaFwApp](https://github.com/Aliothmoon/MaaFwApp)。当前测试环境要求：

- Android SDK
- 完整 JDK 17（需要 `jlink`）
- Python 3
- 同级目录中的修改版 `MaaFwApp` 源码
- 真机后台模式使用 Shizuku 或 Root 授权

项目已经提供构建脚本：

```text
android\build-android.ps1
```

构建普通 arm64 真机 Debug APK：

```powershell
cd D:\a-maa-dev\MBCCtools
powershell -ExecutionPolicy Bypass -File .\android\build-android.ps1 `
  -MaaFwAppDir "D:\a-maa-dev\MaaFwApp" `
  -AndroidSdk "D:\Android\Sdk"
```
构建 MuMu 等 x86_64 模拟器测试包：

```powershell
powershell -ExecutionPolicy Bypass -File .\android\build-android.ps1 `
  -MaaFwAppDir "D:\a-maa-dev\MaaFwApp" `
  -AndroidSdk "D:\Android\Sdk" `
  -Emulator
```

脚本会自动把 MBCCtools 的 `interface.json` 和 `resource/**` 打进 APK，输出统一放在：

```text
android\output\
```

常用输出文件：

```text
MBCCtools-debug-arm64.apk          # Android 真机
MBCCtools-debug-arm64-x86_64.apk   # MuMu/模拟器测试
```

如需尝试 Release 构建可增加 `-Release`；正式发布前还需要自行确认 Android 签名配置。APK 建议作为 GitHub Release 附件发布，不要直接提交进 Git 仓库。

### 4. 清理构建缓存

为了节省磁盘空间，可以随时删除以下目录，不会影响 Git 源码或以后拉取上游更新：
```text
MFAAvalonia\**\bin
MFAAvalonia\**\obj
MaaFwApp\**\build
```

删除后，下次重新执行 `dotnet publish` 或 `android\build-android.ps1` 即可恢复。

## 开发相关

- [MaaFW 开发思路](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.1-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md#%E5%BC%80%E5%8F%91%E6%80%9D%E8%B7%AF)  
  MBCCtools 目前使用其中第一种方式（纯 Pipeline 低代码）
- [Pipeline 流水线协议](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md)

更多文档请前往 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 主仓库查看

## 🙏 致谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！

感谢以下开发者对本项目作出的贡献:

[![Contributors](https://contrib.rocks/image?repo=quietlysnow/MBCCtools&max=1000)](https://github.com/quietlysnow/MBCCtools/graphs/contributors)
