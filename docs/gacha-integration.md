# 抽卡记录接入

## 使用

1. 安装带 Agent 运行时的新版 Android APK。旧 APK 仅更新资源不能运行此功能。
2. 手动进入游戏内的抽卡记录页，在任务列表只选择「抽卡记录」。默认不勾选，避免混入日常链路。
3. 首次选完整识别；后续可选识别到已知停止。切换追踪类型后重新运行。
4. 手机首页「抽卡记录」刷新，查看明细、追踪类型/稀有度筛选、角色/卡池搜索和角色统计。
5. 导出 Excel 可在另一端导入；导出 Markdown 为阅读报告，不作为可回导档案。

第一版按单游戏账号管理；导入前确认账号一致。当前识别模板支持官服/B服中文界面，720p 基准；国际服未验证，不开放任务入口。历史缺失不能通过 OCR 恢复。

## 数据与格式

- Android：应用外部私有目录 `data/record/抽卡记录/*.jsonl`，与 `pi/` 同级分离。
- 桌面脚本默认：项目下 `data/record/抽卡记录/`；可通过 `MBCC_DATA_DIR` 指定数据根。
- 资源更新仅替换 PI，数据不受影响；卸载应用仍会删除应用私有数据，换机前导出 Excel。
- JSONL 保留上游字段 index/key/rarity/type/cells。Excel 包含原始列，保留 OCR 原文与重复抽数。
- 支持本版 Excel、上游按追踪类型分工作表的 Excel；不支持公式或任意布局表格。
- 合并使用出现次数，不对同秒同名抽卡简单去重。重复导入同一完整档案不新增抽数。
- 手机端导入使用原子文件替换，并与采集端通过 POSIX 文件锁协调；每页采集重新读取已有计数。

## 来源与构建

采集流程、识别算法及模板来自 quietlysnow/MBCCtools `33ffb57dc1f7dece2af3c1d3ab08c3f2ad863527`。
保留原项目 LICENSE。只引入抽卡相关功能，未引入通用关闭按钮或活动抓取。

Android 保持 MaaFramework 5.13.1，使用 MaaAgentCoreAndroid `3.13.15-maafw5.13.1`，附加 openpyxl 3.1.5。未安装 OpenCV 时使用 numpy 放大页码，避免增加 Android 原生依赖。

`android/build-android.ps1 -AndroidSdk D:\Android\Sdk` 会在缺运行时时下载配套 core 并组装，校验框架版本一致。运行时输出在被忽略的 `android/agent-runtime/`。当前构建 profile 仅包含 arm64-v8a。

正式发布顺序：先安装新 APK，再更新包含 agent 脚本的资源包。尚未向远程发布。

桌面端源码入口使用 PATH 中的 Python，需要 MaaFw 与桌面 GUI 实际加载的 native 版本一致，并安装 numpy/openpyxl。Android runtime 不能复制给 Windows 使用。当前工作不替换已有 `build-local-final` 桌面测试包；在向该目录同步新增 interface 前必须配置桌面 Agent 解释器，避免影响日常任务启动。

## 验证边界

构建、数据往返与离线算法测试不能替代真机游戏验收。需实机验证：页面门卫、前后翻页、末页/卡顿、中途停止后重跑、重复采集、导入后补采、Shizuku 下数据可读写，以及资源更新后档案保留。

2026-10-15 本地验证：

- Android `:app:assembleDebug` 成功，arm64 APK 包含 Python core、MaaFw 5.13.1、openpyxl、Agent 脚本、Pipeline 和模板；打包内容检查通过。
- Kotlin 数据测试 5 项通过；AgentRuntimeDescriptor、RunPlanBuilder 定向回归通过。
- Python `tests/test_gacha.py` 5 项通过：重复抽数、OCR 行整理、独立数据目录与导出、numpy 页码放大、v2 选项覆盖。
- `tests/gacha_native_smoke.py --synthetic`：真实 Windows MaaFramework 5.13.1 加载资源、TCP Agent 握手、Custom 节点执行；黑屏拒绝采集且零点击；人工生成的单页画面通过真实 OCR 采集两条同秒同名记录，判停导出，重复运行无新增。
- 导入 openpyxl 生成的上游分表格式成功；用 openpyxl 独立读取手机端实现导出的 Excel 成功。
- 未连接或操作用户游戏账号，未在 Android 真机运行，未验证手机界面实际显示效果；人工页面不代表游戏页面识别率。

改动前回溯点：MBCCtools `14e49d9`，MaaFwApp `62f1177`。

## 待办：红点清理

等待用户演示游戏页面及点击规则后实现。先识别页面与红点，再按入口配置处理，限制重试次数；流程结束复查，将仍存在或未能复查的红点记录页面、位置、时间、截图和已执行操作。涉及一次性状态的测试留存前后截图，支持离线识别回放；购买、抽卡等消耗行为不由红点自动决定。

后续需求：根据用户描述，用 Maa 截图/OCR 辅助生成 Pipeline 初稿；本次未实现。
