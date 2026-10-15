# Fork 后遗留资源整理（2026-10-15）

## 范围与规则

检查 MBCCtools 资源仓库、MFAAvalonia 桌面端、MaaFwApp 手机端，以及本地 `build-local-final`、编辑器工具和 Android 打包链路。目的为识别 fork 后闲置文件，不删除项目或整体功能。静态搜索无引用不等于无用：Pipeline 模板目录、反射、跨服 overlay、生成代码、运行时库都需核对实际加载方。

## 本轮已处理

| 内容 | 处理 | 验证与恢复 |
|---|---|---|
| Python 可再生字节码、运行包 NumPy 的 tests 文件 | 去重后 1541 文件、26,832,144 bytes（25.59 MiB）移出工作目录；保留 numpy/testing | 外部备份 `D:\gpt\MBCCtools\cleanup-backups\20261015-152645-167`，manifest.csv 含原路径、备份路径、SHA256、Bytes；移动前后校验；包内 Python -B 验证 NumPy、Maa、PIL、openpyxl、Excel 往返 |
| 桌面隐藏的 Resources 示例空页 | 移出 ResourcesView.axaml、code-behind、ResourcesViewModel.cs，并去除 App 注册、隐藏菜单项、Instances 字段 | 原页面空 Grid，VM 只有 Hello/World/Goodbye；真实资源选择由 TaskLoader/首页实现。移出前 Git 点 df894c1；外部备份 `D:\gpt\MBCCtools\cleanup-backups\unused-desktop-source-20261015` |
| MFAAvalonia/dependencies.json | 移出误保存的 3448 字节命令帮助文本 | 不是 JSON、无构建/代码引用；同上备份和 Git 恢复 |

桌面清理后重新构建成功（0 error，保留既有依赖与弃用警告）。本轮不删除外部备份，等待用户真实游戏验收后再作最终回收。因此这里的“移出体积”不等于整块磁盘净释放空间；字节码以后仍可能重新生成。

## 审查后保留

- 本地真实抽卡档案、配置、日志和此前回溯备份。
- 当前手机 APK、Android Agent runtime、arm64 native 库；这些分别是交付物和打包输入。
- MPE 前端与 LocalBridge：桌面编辑器仍需要。真正初始化发生在进入编辑器页面时，正常离开会释放；不能因为文件较大而删除。
- MaaCommonAssets 中旧 OCR 版本：虽然本项目默认仅选 v5 中文模型，这些文件属于 Git submodule，不能直接拆删。
- base/bilibili/global 资源：共享模板与 overlay 有跨目录引用。
- 手机上的 Shizuku、SMTP、Sentry、FloatingX 等：有实际功能或构建消费点，不因暂时不用而认定无用。

## 仍需进一步验证的候选

- MaaFwApp 的 app/build 约 1555.83 MiB，主要为可再生构建副本；不是废弃源码。保留当前交付 APK后可单独执行构建清理，但下次构建会重新生成。
- 手机 x86_64 native 输入约 217.49 MiB：当前 arm64 profile 不使用，通用/模拟器构建可能使用，暂保留。
- Android Semi 图标库：592 个 XML 中静态业务调用涉及 39 个 Mono 图标，553 个成员为候选；需连同生成索引、R/XML 和动态加载验证后再精简。
- 桌面 `MpePipelineExportService.Register` 旧入口没有找到业务调用，现有流程使用 SaveToResource/UpsertTask。保留当前服务，避免误删仍使用的保存/返回模型。
- `build_local_gui.ps1` 对已存在 OutDir 会直接递归删除，执行前必须核对目标与源码/基础包路径，不能用它对当前测试包盲目覆盖。此次未运行该脚本。

## 完整审查资料

- `D:\gpt\MBCCtools\audit-desktop-features.md`：桌面功能与引用依据。
- `D:\gpt\MBCCtools\audit-android-unused.md`：Android 资源/依赖/打包路径依据。
- `D:\gpt\MBCCtools\audit-resource-publishing.md`：资源仓库与发布链路。确认 assets/resource/model/ocr 与交付模型存在约 20.37 MiB 同哈希副本，但生成脚本仍写入前者，需统一路径后才能移出；本轮保留。根目录旧 Linux testapp desktop 模板列为后续候选。

本轮按用户要求仅迭代电脑版抽卡界面；手机第二版分类/页面改造仍待桌面反馈稳定后进行。

## D 盘空间追查与待回收产物

后续确认本次测试/编译新增了多份输出，包括 UI 测试工程约 604 MiB、桌面构建约 634 MiB、核心库副本约 358 MiB、测试 Python 环境约 154 MiB。已将这些生成目录，以及 Android core 下载缓存、与交付 APK 同哈希的构建侧 APK，移入 `D:\gpt\MBCCtools\cleanup-backups\generated-artifacts-20261015`，总文件内容约 1.93 GiB。实际运行包、源码、交付 APK 和用户数据保留。

移出后使用运行包自带 Python 执行 9 项数据回归，全部通过。最后删除该临时目录的工具调用被自动审批拒绝（仅返回 `blocked by policy`），未执行。因此这里尚未释放磁盘空间。清单及重建说明为 `D:\gpt\MBCCtools\generated-artifact-cleanup-20261015.json`；确认后的人工回收只针对上述 generated-artifacts 临时目录，不要删除整个 cleanup-backups 或其他项目目录。
