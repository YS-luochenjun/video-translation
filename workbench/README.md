# 视频本地化工作台

本机需求台账与制作查看入口。使用项目已有 Python 和标准库，无需 npm、额外模型或云服务。浏览器每5秒读取一次，独立采集线程每15秒核对本地规范记录。关闭页面不影响采集；关闭服务不影响原CLI/MCP制作。台账核心在 `src/video_localizer/ledger.py`，适配与页面在本目录。

第一期说明与统计口径见 [需求台账](../docs/ledger-phase1.md)。默认打开需求台账；原任务/视频、知识和运行概况继续保留。

## 启动

macOS/Linux：

```sh
sh workbench/start.sh --background
# 指定已通过 doctor 的 Python
WORKBENCH_PYTHON=/实际路径/python3 sh workbench/start.sh --background
```

通用启动为 `python workbench/start.py --background`。后台PID和日志在work/workbench；不安装系统开机项，不自动停止占用端口的进程。

在项目根目录运行：

```powershell
workbench/start.ps1
# 独立后台启动并打开浏览器（关闭启动终端后仍运行）
workbench/start.ps1 -Background -Open
# 自定义端口
workbench/start.ps1 -Port 8769
```

打开 <http://127.0.0.1:8768>。服务只监听本机，前台模式在终端按 Ctrl+C 停止。后台模式的进程号和日志写入 `work/workbench/`。端口占用时选择其他端口，不会自动杀进程。

也可以直接运行：

```powershell
.venv/Scripts/python.exe -B workbench/server.py --port 8768
```

## 当前版本

- 台账：关联已登记Fireplay需求、预算、批次、run及经哈希核验的独立交付包；无法可靠关联的记录单列，不计需求完成量。
- 效率：首次完整输出、交付周期、首次ETA偏差、已到期预测准时率、缺失覆盖率与每日趋势；原视频/语言完成粒度分别保留。
- 跟踪：原视频认领租约、实际阶段/心跳、等待原因、首次/滚动ETA及历史；脚本执行器心跳与Agent活动分开。初始规则估算明确标未校准。

- 任务：读取 `runs` 与根 `outputs/index.json`，现场清理后仍显示独立交付包。按源视频分组，支持语言/名称搜索及状态筛选。
- 视频：原片与当前结果并排、单路选听、同步定位、按实例跳转、前后帧近似寻址、独立版本播放。需要精确判断时仍使用实际导出帧与 PTS。
- 内容：文字/口播实例、译文、处理理由、已有问题观察、质量失败、成片瑕疵。
- 知识：现行方法、同源参考、候选索引；任务的冻结知识、Codex 工作包、声明阅读和真实 `knowledge-use` 回执分别展示。未记录不推断为采用或有效。
- 执行：最近模型回执、Codex 观察/产物、阶段耗时、维护暂缓和持久后续待办。
- 运行概况：当前模型路由、本地重任务上限、资源锁、按请求去重的费用账本快照。

制作记录仍只读。新增的受控本机POST只登记台账认领、阶段、等待、ETA和关联事件，检查同源、防跨站令牌、幂等ID与记录版本。没有制作、重试、质量审批、清理或对外提交按钮，不把命令字符串发送给shell。

## 与当前框架的关系

制作规则集中在 `agent/contracts` 和 `agent/workflows`，执行仍由 `src`/`bin` 承担。Codex 主导视觉、翻译及判断；专用模型处理真实音视频。安装资产属于 `.runtime`，`work` 只承担临时内容；`runs` 是现场，`outputs` 是独立交付，`state` 是跨任务状态。工作台不搬迁这些数据。

新版默认快速交付，达到边界后 `finalize` 输出最佳完整译片。因此输出状态与质量状态分开，`delivered_with_issues` 不显示成质量通过；历史质量异议优先提醒。`state/deferred-delivery` 是持久待办，不代表后台已运行。`maintain --close` 可能退休 run，工作台从独立交付包继续查看。

工作台不调用 `work-packet`、`budget-status` 或生产模块；部分现有状态命令会同步费用记录。这里直接读取规范文件，避免刷新触发写入。页面阶段是基于记录的导航摘要，不是执行许可。执行时仍以项目原门禁为准。

## 真实性与读取边界

- 自动刷新的是已落盘状态。Fireplay只读取现有宿主流程登记的快照，不代表平台全队列实时同步；展示快照时间。不能根据“没有新日志”认定进程卡死，资源锁也不证明进程存活。
- 计划/回执/版本保留原绑定。交付索引与 manifest、视频哈希核对后才显示正常；哈希缓存只用于查看性能，不替代交付门禁或完整包审计。
- 质量标签是记录的结论，不证明实际视听、独立审核或用户验收。全流程仍需要实际观察。
- 仅提供范围内媒体和知识文本；拒绝隐藏路径、父路径、工作区外链接、任意静态目录与非台账写入。隐藏常见凭据字段、Bearer值及远端签名地址，不开放state数据库文件下载。
- 浏览器关闭不改变任务。未接入项目规范记录的临时脚本可能无法显示完整过程。
- 历史包不一定保留所有源帧和任务文件；缺失内容显示“未记录”，不会自动重建或调用模型。

## 验证

```powershell
.venv/Scripts/python.exe -B workbench/test_workbench.py
python -B -m unittest discover -s tests -p test_ledger.py -v
python -B workbench/test_ledger_http.py
```

测试使用 `work/test-tmp` 内的一次性工作区，覆盖只读不改文件、任务新增与损坏隔离、已归档任务、带瑕疵输出、版本篡改、质量异议、旧审核失效、路径隔离、凭据隐藏、视频 Range/HEAD 和禁止写接口。

代码：`store.py` 负责只读制作数据投影；`collector.py`负责证据关联和持续采集；`server.py`负责本机HTTP；`static/`为原生HTML/CSS/JavaScript。台账数据持久保存在state/ledger，可用 `bin/va.py ledger backup` 一致性备份。前端没有外部字体、CDN、分析追踪或构建依赖。
