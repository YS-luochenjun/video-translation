# 存储、保全与清理合同

当前 AI 判断保留价值并提纯经验；执行器负责锁、复制、哈希、依赖闭包和账本门禁。目录职责见 [项目布局](../../docs/project-layout.md)，知识分类见 [知识入口](../../knowledge/README.md)。

## 独立保留的对象

- `runs/<任务>/` 保存制作现场，包含输入、定稿、计划、任务、候选和评审；制作中和恢复时使用。
- `media/<源哈希>/<版本>/` 保存原片、源帧、音轨、OCR/转写及中性观察；只用于核验过的同源解析，不继承目标语言结果。
- 根 `outputs/` 保存可独立恢复的交付/复用包。manifest 绑定成片、源片、准备资产、语言层和评审；历史 revise 包仍是待改进参考。
- `knowledge/` 保存方法、必要案例和反例；`knowledge/local/` 保存私有证据、质量异议、候选及检查点。
- `state/` 保存预算、批次、锁、保全、恢复和删除回执。未知费用继续预留。
- `.runtime/` 和 `.venv/` 是安装资产；`work/` 是可重建缓存和临时工作。

这些对象有各自的恢复合同。相同字节可以出现在多个独立包中；同一包可用内部硬链接，交付包不能链接到可变 run。知识案例使用独立文件，不依赖生产目录长期存在。

2026-10-23 用户要求减少空目录和无用半成品：新 run 仅创建收件所需目录，其余由实际阶段写入时创建。续作先查询 `work-packet` 的 `reusable_packages`，优先使用已核验 outputs 包。阶段结束后，Codex 判断保留价值；无用 run 走下述保全/删除，过时版本走选择清单。普通空目录与无引用的可重建缓存可在明确清理授权内删除；安装资产、正在使用的目录、未结算记录和必要证据继续保留。2026-10-23 用户进一步授权将增量整理作为后续每次运行的固定流程；具体执行见下节。

`storage-report --duplicates` 提供定位线索，不是删除清单。`storage-policy` 与 `storage-plan` 提供数量、容量和最低剩余空间预警，目前不会自动删除。

## 每次运行的增量整理

由 `config/maintenance.json` 启用，用户授权来源为 2026-10-23 本项目会话。运行中的阶段操作成功后，`guarded` 自动检查本任务账本与活动锁、移除本任务普通空目录，并写 `state/maintenance/<run>/latest.json`；清理失败单独记录 deferred，不影响已经生成的视频。嵌套操作只在最外层检查，保全/删除操作不触发二次整理，避免改变已冻结指纹。

1. 开始和续作：读取 `work-packet.maintenance` 与 `reusable_packages`。临时文件放 `work/runs/<run>/`，目录按需创建。长期执行能力进入 src/bin，回执进入 state，实际审核与必要失败证据进入 run/knowledge，正式成片进入 outputs。
2. 阶段收尾：确定某个文件只是可重建缓存后，用 `scratch-register RUN work/runs/RUN/文件 --reason 重建方法` 登记当前哈希。成片实际文件哈希与交付记录一致、账本/任务已结清时，交付阶段 Hook 自动核对内容与引用，保存指纹预览，再删除已登记且未变化、未被引用的缓存。未登记文件不按扩展名或年龄猜测删除。返工中的中间阶段不会因为存在旧交付记录而释放缓存；其它 run 活动时暂缓引用扫描。
3. 每次任务结案：完成外部提交和必要记录后，执行 `maintain RUN --close`。它串行执行保全、删除预览与当前指纹删除；源片、知识案例和独立交付包验证通过才移除 run。仍需被其它任务引用、账本未结清、活动锁或缺少完整译片时保留，并输出具体原因。后续续作先处理这个回执；不建立隐式后台定时器。
4. `work/` 中旧的未归属文件先分类，不自动认定全是垃圾。新任务统一归属路径，避免继续累积。`work/cache/uv` 等共享包缓存可复用，不随单个视频结束反复清空；按容量报告单独安排清理，安装资产保留在 `.runtime`。已经作为审核依据或复用依赖的文件先迁入正式包，再重新核对引用后整理。
5. 根 `outputs/` 是交付库，每次结案检查成片已独立归档，保留现行最终版和有价值复用包。空目录可移除；旧完整版本按选择清单保全。重复字节、低分、时间久都不单独构成删除理由。失效/缺文件的包记录问题，不能将缺失文件报告为释放空间。

入口：`bin/va.ps1 maintain RUN`、`bin/va.ps1 maintain RUN --close`；MCP 为 `localizer_maintain`。回执留在 state，即使 run 删除仍可复查。维护脚本不得递归清空整个 work/outputs/media/state。

## 源解析与素材复用

`analyze` 按完整源 SHA256、抽帧参数、分段上限和解析版本查找快照，命中后核验源解析资产。已有 inventory 不覆盖；源观察仍需确认覆盖，新语言重新定稿、配音、时轴、字层和审核。`source-save RUN` 显式保存观察，`source-find SHA256` 查询。

同源底片和语言素材由交付库单独管理；`library-find SHA256` 显示 expired 时不能从哈希恢复文件。重新编码文件当前不视为精确同源。缓存只复用机械结果，失效规则见 [缓存与恢复](../../docs/workflow-optimization.md)。

## 删除一个 run

```powershell
bin/va.ps1 run-preserve RUN
bin/va.ps1 run-delete RUN
# 仅在用户授权范围内，使用本次 ready 预览的完整指纹
bin/va.ps1 run-delete RUN --execute --expect 完整指纹
```

保全冻结源状态、观察、决定和账本，建立独立候选案例及 inbox；已有成片时保留原技术状态的交付包，原片另存恢复包。未启用观察不会因此成为正式规则。

删除要求当前内容与保全指纹一致、知识审计通过、独立包及必要文件完整、任务终结、费用明确且没有活动锁。每次只处理一个明确 run；不存在 force 绕过。删除失败保留 deleting 回执和恢复包，检查后恢复处理。保全会占用持久空间，删除 run 不代表删除 media、outputs、state 或全部源素材。

费用门禁同时读任务与请求总账。失败、超时、无 taskId 或无 billing 字段均不证明未扣费；有估算/预留而实际费用未知时阻止删除。只有有依据的数值零费用与未知不同。任务文件缺失也不能释放总账中的未知预留。

## 清理旧比较图和旧视频

`run-prune` 在正常保全与删除预览之后，只处理未被当前成品/底片使用的过时比较图。保留原始观察、明确失败与代表性图片、脚本、配方、账本和当前完整审核；缺失必要失败证据会阻止清理。

```powershell
bin/va.ps1 run-preserve RUN
bin/va.ps1 run-delete RUN
bin/va.ps1 run-prune RUN
bin/va.ps1 run-prune RUN --execute --expect 完整预览指纹
```

旧完整视频采用 [选择清单](../templates/prune-versions-example.json) 明确指定：

```powershell
bin/va.ps1 run-preserve RUN
bin/va.ps1 run-prune-versions RUN inputs/prune-versions.json
bin/va.ps1 run-prune-versions RUN inputs/prune-versions.json --execute --expect 完整预览指纹
```

执行先建立并核验独立 `knowledge/local/retired-versions/` 证据，再删除所选视频。当前计划、候选、交付、任务和其他 run 引用的资产受保护；重任务锁、未知费用、内容变化或证据缺失都会拒绝。运动/声音问题需保留连续或声音证据，单图不足时保留整段。

部分清理后旧 manifest 仍保留历史原文，但缺图的历史审核不再是完整可复用证据。清理改变内容后重新保全，旧指纹失效。历史脚本以数据保留，不执行其旧审核结论。

## 知识与质量异议

必要知识证据由案例 manifest 声明，旧路径仅是来源标签。`knowledge-evidence` 可追加不可变补证；`knowledge-audit` 检查正文、哈希、scope 和必要证据。精简案例支持理解方法，不承诺逐帧重放整支生产视频。

质量异议独立保存在 `knowledge/local/quality-holds/`，删除 run 或交付包不会撤销否决。迁移历史客户素材时一并迁移相关异议；只复制旧交付包不能证明其当前可用于制作。详见 [质量反馈](../workflows/quality-feedback.md)。

## 恢复与迁移

`archive RUN` 创建交付包，`archive-verify PACKAGE` 核验，`archive-restore PACKAGE --id NEW` 恢复历史工作副本。恢复不等于新语种验收。

全新部署只导出公共源码和知识，见 [干净导出](../../docs/project-layout.md)。迁移既有业务还须带上需要的私有知识及索引、质量异议、账本、检查点、源解析、交付包和未完成现场；凭据和安装资产分别配置。项目 Hook 的首次 baseline 和调度见 [每日提纯](../../docs/daily-knowledge-curation.md)。

任何清理均按实际阻塞清单报告已删与保留，不为追求空目录绕过门禁。一次用户明确授权的历史重置不构成日后自动清空规则。

## 按需求名组织交付目录（2026-10-26 用户要求）

交付一级目录使用明确需求名，通常为原视频文件名去掉扩展名；结构为 `outputs/<需求名>/<语言>/<版本>/`。实际源 SHA256 仍是身份依据。当前映射登记于 `state/delivery-folders.json`，归档器按映射续写，未登记的旧来源保持哈希路径兼容；新需求先核实名称并登记，同名不同源须明确区分，不能合并覆盖。改名同步 catalog 和当前展示链接，保留迁移映射及旧索引；包内不可变 manifest、源片和审核证据不改写。`reports` 与索引文件是公共入口，不是视频需求目录。
