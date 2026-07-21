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

> ⚠️ 仅当需要开发本项目时才需要关注此部分，普通用户请直接[下载发布版](https://github.com/quietlysnow/MBCCtools/releases) 

0. 完整克隆本项目及子项目

    ```bash
    git clone --recursive https://github.com/zhang2291/MBCCtools.git
    ```

1. 下载 MaaFramework 的 [Release 包](https://github.com/MaaXYZ/MaaFramework/releases)，解压到 `deps` 文件夹中
2. 安装

    ```python
    python ./install.py
    ```

生成的二进制及相关资源文件在 `install` 目录下

### 本地修改后启动 GUI

> 以下步骤是根据上游 GitHub Actions 打包流程补充的个人本地组装方式。上游 README 本身只要求下载 MaaFramework，并未要求单独下载 MFAAvalonia；正式 Release 压缩包中已经包含 GUI。

不需要将修改推送到 GitHub，也不需要创建 Tag 或 Release。本地准备一次 GUI 文件后，后续每次修改都可以直接重新打包并启动。

1. 按上面的编译说明准备好 `deps` 目录。
2. 从 [MFAAvalonia Releases](https://github.com/MaaXYZ/MFAAvalonia/releases) 下载与本机架构对应的 Windows 压缩包。绝大多数 Windows 电脑选择 `win-x64`。
3. 将压缩包内的文件解压到本仓库的 `install` 目录，并确认存在 `install/MFAAvalonia.exe`。
4. 每次修改 Pipeline、图片或 `interface.json` 后，在仓库根目录执行：

    ```powershell
    python .\install.py v1.4.3-local.1
    .\install\MFAAvalonia.exe
    ```

`install.py` 会把当前工作区中的 `resource`、`interface.json` 和 MaaFramework 文件更新到 `install`，并保留已经放入其中的 MFAAvalonia GUI 文件。因此，本地验证可以完全在 `install` 目录中进行。

> 如果删除或重命名了资源文件，建议清理旧的 `install` 目录后，重新解压 MFAAvalonia 并执行 `install.py`，避免旧资源残留影响测试。

## 开发相关

- [MaaFW 开发思路](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.1-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md#%E5%BC%80%E5%8F%91%E6%80%9D%E8%B7%AF)  
  MBCCtools 目前使用其中第一种方式（纯 Pipeline 低代码）
- [Pipeline 流水线协议](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md)

更多文档请前往 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 主仓库查看

## 🙏 致谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！

感谢以下开发者对本项目作出的贡献:

[![Contributors](https://contrib.rocks/image?repo=quietlysnow/MBCCtools&max=1000)](https://github.com/quietlysnow/MBCCtools/graphs/contributors)
