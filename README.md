# MBCCtools（个人 Fork）

本仓库是 [quietlysnow/MBCCtools](https://github.com/quietlysnow/MBCCtools) 的个人 Fork。

- 原仓库：`quietlysnow/MBCCtools`
- 当前 Fork：`zhang2291/MBCCtools`
- 用途：仅用于个人设备上的《无期迷途》自动化、Pipeline 调整、桌面版与 Android 版整合测试。
- 本仓库不是上游官方版本，不提供通用兼容性保证。
- LICENSE、版权与上游来源信息均按原项目保留。

上游项目基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 实现，原上游 README 说明其开发过程中参考过 MACC。

## 相关源码仓库

当前本地构建会同时使用下面三个仓库：

| 仓库 | 当前 Fork | 上游 |
| --- | --- | --- |
| MBCCtools | `zhang2291/MBCCtools` | `quietlysnow/MBCCtools` |
| MFAAvalonia | `zhang2291/MFAAvalonia` | `MaaXYZ/MFAAvalonia` |
| MaaFwApp | `zhang2291/MaaFwApp` | `Aliothmoon/MaaFwApp` |

建议三个仓库放在同一级目录，例如：

```text
D:\a-maa-dev\
├─ MBCCtools
├─ MFAAvalonia
└─ MaaFwApp
```

## Windows 桌面版构建

环境：Windows 10/11、.NET 10 SDK、Python 3，并准备好 `MBCCtools\deps` 中的 MaaFramework 运行文件。

先构建当前 Fork 的 MFAAvalonia：

```powershell
cd D:\a-maa-dev\MFAAvalonia
dotnet publish .\MFAAvalonia.Desktop\MFAAvalonia.Desktop.csproj -c Release -r win-x64
```

然后组装 MBCCtools：

```powershell
cd D:\a-maa-dev\MBCCtools
.\build_local_gui.ps1 `
  -BaseDir "D:\a-maa-dev\MFAAvalonia\bin\AnyCPU\Release\win-x64\publish" `
  -OutDir "D:\a-maa-dev\MBCCtools\build-local-final" `
  -Version "local"
```

MaaPipelineEditor 需要保留在：

```text
MBCCtools\tools\MaaPipelineEditor
```

最终运行目录：

```text
MBCCtools\build-local-final\MFAAvalonia.exe
```

## Android 版构建

环境：JDK 17、Android SDK、Python 3，并将当前 Fork 的 `MaaFwApp` 放在同级目录。

构建 arm64 真机包：

```powershell
cd D:\a-maa-dev\MBCCtools
powershell -ExecutionPolicy Bypass -File .\android\build-android.ps1 `
  -MaaFwAppDir "D:\a-maa-dev\MaaFwApp" `
  -AndroidSdk "D:\Android\Sdk"
```

构建模拟器测试包：

```powershell
powershell -ExecutionPolicy Bypass -File .\android\build-android.ps1 `
  -MaaFwAppDir "D:\a-maa-dev\MaaFwApp" `
  -AndroidSdk "D:\Android\Sdk" `
  -Emulator
```

输出目录：

```text
MBCCtools\android\output\
```

真机后台运行使用 Shizuku 或 Root；具体运行逻辑由当前 Fork 的 MaaFwApp 提供。

## Release 与更新

GitHub Fork 不会自动复制上游仓库的 Releases。

因此 `zhang2291/MBCCtools` 的 Release 需要单独创建，并手动上传当前 Fork 构建出的桌面包或 Android APK。仅 `git push` 代码不会自动生成 Release。

## 可安全清理的构建缓存

下面这些目录都是可重新生成的，不影响 Git 更新：

```text
MFAAvalonia\**\bin
MFAAvalonia\**\obj
MaaFwApp\**\build
```

保留源码、`.git`、`resource`、`interface.json`、`tools\MaaPipelineEditor` 和当前需要的构建脚本即可。

## License

许可证沿用上游项目，详见仓库中的 `LICENSE`。
