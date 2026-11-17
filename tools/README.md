# 工具与辅助脚本 (Tools)

本目录归类存放项目相关的辅助脚本与运行库安装工具：

| 工具文件 | 说明 | 使用方法 |
| --- | --- | --- |
| `check_resource.py` | 校验指定的 Maa 资源目录是否合法 | `python tools/check_resource.py resource/base` |
| `InstallRuntime.ps1` | Windows 下自动检测、下载并安装 VC++ 与 .NET 10 运行库 | 以管理员权限运行 PowerShell 脚本 |
| `DependencySetup_依赖库安装_win.bat` | 通过 winget / certutil 自动安装 Windows 依赖库 | 右键以管理员身份运行 |
