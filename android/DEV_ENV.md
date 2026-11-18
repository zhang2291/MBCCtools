# Android 开发环境与清理清单

项目侧统一目录：`D:\a-maa-dev\MBCCtools\android`

## 项目内目录
- `build-android.ps1`：Android 构建脚本
- `pi-profile.yaml`：MaaFwApp 打包配方
- `app-icon.png`：Android 图标
- `output\`：最终 APK 统一复制到这里
- `temp\`：临时构建/测试文件，完成后可整体删除

## 外部环境
- Android SDK：`D:\Android\Sdk`
- JDK 17：`C:\jdk\jdk17`（亦支持 Eclipse Adoptium / JetBrains JBR JDK 17）
- MaaFwApp：`D:\a-maa-dev\MaaFwApp`
- Gradle 缓存：`C:\Users\zhang\.gradle`

## 打包与资源热更新说明
1. **本地快速出包**：在 `MBCCtools` 根目录运行 `pwsh -File android/build-android.ps1`，产物自动输出至 `android/output/MBCCtools-debug-arm64.apk`（正常体积约 145 MB；已排除桌面端 `agent/python/**`）。
2. **仅改资源/Python 脚本时的手机端热更新**：推送 `resource-v<版本号>` 标签（如 `git tag resource-v20261118-01 && git push origin resource-v20261118-01`），GitHub Actions 会自动构建包含 `interface.json`、`resource/**` 与 `agent/**` 的资源包并更新 `resource-manifest` 分支，手机端直接点「资源更新」即可热更，无需重打 APK。
