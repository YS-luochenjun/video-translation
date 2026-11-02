# 存储、保全与清理合同

现行来源：拥有者2026-10-30要求最终结果按需求／语言／任务组织、默认最新版、最多14天；2026-11-02进一步要求少保存老旧内容、减少制作副本，并授权优化文件清理和知识积累。长期保留少量有价值的方法与必要案例、费用和平台回执；不默认保留整套旧工程。历史一次性重置授权不构成本次清空许可。

## 目录与身份

- `outputs/<需求名>/<语言>/<任务>/final.mp4`是用户查看的交付；编号需求采用真实编号，多原片用任务序号。普通任务可在request填写requirement_name和task_name。
- `outputs/.packages/`保存不可变交付包。默认package_mode=lean，只含一份独立成片和必要JSON审核／请求记录，不复制原片、底片、配音和准备资产闭包。request.delivery_package_mode只允许lean或reusable，并优先于旧keep_reusable_assets标记和配置默认；选择reusable才保存可恢复工程。旧完整包继续兼容。包与展示共用到期规则，不是永久备份。
- `state/delivery-index.json`保存索引和过期历史，浏览页位于`state/delivery-browser`。旧outputs/index.json在实际清理时独立保全并迁出成片目录。已过期历史显示已过期；原先缺包标missing_before_sweep，不谎称本轮删除或可恢复。
- `runs/`是制作现场；`work/runs/<run>`是已登记的任务临时文件；`media/`是可重建源解析库。`knowledge/`保存独立方法／案例，`state/`保存费用、平台提交及清理回执。安装资产、配置与Git不随媒体到期。

## 正常保留与自动清理

交付期限由`config/delivery-policy.json`唯一配置：默认最新版，最多14天；明确request.keep_multiple_versions=true才保留多个版本，仍受14天限制。相同包重导不刷新首建时间，也不能把更旧版本重新覆盖最新版；已标记过期的同身份版本禁止重新落盘，不靠重导复活。新结果核验后原子替换展示。旧包删除后索引保留expired，不再宣称本地可恢复。

制作现场和缓存期限由`config/maintenance.json`配置：

| 内容 | 正常回收条件 |
| --- | --- |
| 已结案run及对应work/runs | maintain --close后24小时，下一轮回收 |
| 已无run的已登记任务缓存 | 闲置24小时，且没有在制任务引用 |
| 明确failed/cancelled/aborted或close-failure结案的现场 | 连续7天无文件活动，且没有在制任务引用 |
| media中的源解析缓存 | 连续7天未保存／实际复用，没有保留任务引用，也没有pin |

成功交付后的已登记可重建缓存仍由maintain即时整理；24小时是完整结案现场的缓冲期。安静或旧pending不等于已失败，不能凭年龄删除未结案任务。未知归属work文件保留待分类，不按文件扩展名猜测归属。源缓存的实际使用时钟写state/media-usage，不改写冻结包。

`config/storage-policy.json`只维护容量、数量及最低剩余空间阈值。默认优先回收中间物，不因普通容量压力提前删除14天内最新版；只有显式evict_latest_under_pressure=true才允许提前回收已结案包。在制依赖、pin或活动锁会暂缓回收并说明原因；不把暂缓冒称已经清理，续作应将必需资产复制到自己的现场。

自动执行要求本机`config/storage-authorization.local.json`的workspace精确绑定和automatic_cleanup=true。新机器从example配置自己的授权，reset_existing_data保持false。常规storage-plan／storage-sweep预览只读，执行使用当前预览指纹：

```sh
python bin/va.py storage-sweep
python bin/va.py storage-sweep --execute --expect <本次预览指纹>
python bin/storage_daily.py
python bin/storage_daily.py --execute
```

每日入口默认只读，--execute才删除；没有授权或存在活动锁时返回deferred。规定每天上海18:30运行，制作阶段按配置间隔增量检查。Windows可用`bin/project-storage.ps1`的Install/Status/Uninstall管理唯一工作区任务，Install和Uninstall需要-Execute；与应用定时任务二选一，不能重复安装。系统触发器设置错过后补跑；配置、代码或安装计划不代表本机已安装成功，真实状态和运行回执分别核实。知识每日18:00采用自己的入口，两项互不等待。单轮候选按当前预览处理，不保留旧的每次只清3个run的限制。

## 执行与重复保存

执行器先检查活动锁，冻结候选路径、文件元数据、完整策略、索引及保留任务的依赖。独立保全必要文本记录，核对指纹后删除；归档从读取源文件到登记索引全程共用run锁，但不撤销原结案状态；结案生产者、新任务及归档均在取得自身锁后再次检查全局清理锁。在制任务的跨run引用按传递关系保护，指纹变化必须重新预览。知识审计前后通过；未知费用保留原预留、真实任务ID和响应，删除媒体不结清费用、不改变质量异议或用户验收。

- 同一需求／语言／任务只有一个默认final入口；相同归档重试不新增copy、backup、final2，不改变业务身份或首建时间。
- 成片必须脱离run仍可读，不能硬链接到可变run。不可变包内相同SHA256资产及正式展示优先硬链接；不支持时复制并校验。禁止原地修改展示文件，改版必须重新制作并原子替换。
- 相同源解析按哈希和提取参数核验复用；新语言仍独立定稿、配音和审核。需要修改的副本放所属work/runs，禁止额外整目录备份。默认lean没有源／准备资产恢复资格；archive-verify通过只证明包完整，不等于可恢复生产。
- 知识只独立保存有用途的必要对照，不复制整片作永久备份；不跨公私或授权范围去重。临时副本登记用途和退出条件，保全记录不复制所有待删视频。
- 清理后移除空展示目录。回执分别报告逻辑字节和磁盘实际净变化；硬链接及并发系统写入下两者不同。当前没有全项目跨包物理去重，不作此宣称。

## 结案与一次性重置

外部提交和必要记录完成后执行`maintain RUN --close`。本机已授权的新布局核验独立交付后写入正式视频哈希结案标志；不再额外建立永久整片恢复副本。旧逐run入口仍走run-preserve → run-delete预览及指纹，不把生命周期执行器当force开关。

storage-reset只适用于用户当前明确确认所有旧任务已完成并要求清空、且本机另有一次性reset_existing_data授权的情况。它可清空runs/work/outputs/media，保留知识、state、费用、平台历史、配置、Git与安装资产；执行后消耗许可。定时入口永远不调用reset，本次优化不执行重置、不删除当前生产数据。
