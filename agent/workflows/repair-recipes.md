# 本地去字／去水印配方与风险预检查

本功能执行已解释、绑定源片的局部修复；不自动理解水印、挑选供体或认定效果合格。方法正文见 `knowledge/rules/moving-watermark-removal-v1.md`。已有 prepared、资源锁、视觉审核和质量异议继续有效，不另建模型任务系统。

```powershell
bin/va.ps1 repair-preflight RUN
bin/va.ps1 repair-run RUN inputs/repair.json --probe
bin/va.ps1 repair-run RUN inputs/repair.json
```

配方示例为 `agent/templates/local-repair-example.json`。填写实际 source_sha256、产品/姿态边界、操作区间、掩模 bbox 或 polygon、旋转角度、trajectory 和保护区；reason 说明真实观察。bbox 轨迹线性插值，不能代替正确跟踪。当前程序配方可使用 temporal_frame、temporal_median、telea 等操作；图片模型编辑由 Codex 完成。时序供体与目标必须在声明的同一镜头/姿态内；实际边界和干净供体仍需 AI 判断。不要直接使用旧素材的坐标或旋转速度。

预检查复用原分析器的视觉切点检测，并分别列出文字源区间、轨迹事件和完整画面边缘检查。候选切点不是已复核的镜头边界，模糊文字入场也需看原图。探针覆盖事件前后连续帧，输出原尺寸 PNG；它们不能放行整片。MCP 提供 localizer_repair_preflight 和 localizer_repair_recipe，后者默认 probe。

完整结果使用无声 FFV1 无损底片和版本化 provenance，记录真正变化的掩模范围。掩模外及保护区直接保留原像素。配方冻结进该版本目录，后续修改原配方不破坏旧记录。LaMa 新推理已停用；历史结果仅在输入及结果哈希匹配时复用，新的图片编辑按 [模型分工](../contracts/model-routing.md) 执行。当前内存预算限制解码源片不超过512 MiB，VFR须先显式规范化；长片应先选有来源的短片段，不静默改变时轴。

继续按 visual-evidence --stage neutral → visual-notes → visual-release-neutral → plan 建立审核。默认未通过，禁止把执行成功、掩模外像素一致或探针干净当作修复质量通过。

项目 state/repair-trials/<RUN>.json 跨配方累计实际尝试和耗时，默认4次、600秒。缓存命中不增加次数；修改配方不重置预算。需继续时提供 --extension-reason 解释失败和下一变量，仅增加1次及300秒；这不是付费授权或质量豁免。达到时间预算会停止局部计算，半成品不是检查点。

进程中断后先按现有规则核对 run/resource 锁及 PID；不要删除活锁。确认进程已退出后可运行 repair-reconcile RUN --reason "有来源的中断原因"，它只核验本地检查点或标记中断，不重发远端任务。work-packet 返回尝试记录、已有问题和图片展示游标，展示不等于审查通过。旧的一次性脚本未接入此预算，不能据此宣称所有历史脚本都已受控。

## 旧脚本迁移与逐帧复用

不要复制旧脚本再改一个帧号。把输入资产、操作区域、生效区间及参数放进配方，仍从 `repair-run` 执行。本轮把已实测旧脚本中的三类操作提为通用方法：

- `source_restore`：从原片同一帧恢复指定矩形，不借用其他时刻。
- `horizontal_fill`：从当前原帧的左右干净边缘采样，逐行插值；只适用于已经核实的平坦背景，不推广到纹理、产品或其他视频。
- `exposure_patch`：使用已有、哈希绑定的同帧模型画面，按指定参考行修正曝光及过渡；不调用模型，不自动证明生成画面正确。

这三类操作的整数 `bbox` 使用半开范围 `[x,x+w)`、`[y,y+h)`，与 Python 切片一致。旧 `telea/lama/temporal_*` 的掩模约定保持不变。

原脚本按帧号判断时，显式填写 `frame_interval: [起始帧, 结束帧]`，起始为零、结束不包含；它是实际生效范围，`start/end` 保留时间描述，帧区间仍必须落在声明镜头和视频范围内。不要直接将帧号除以帧率当作等价条件，MKV 毫秒时间戳取整可能漏掉边界帧。按秒定义的普通配方继续只用 `start/end`。

`base_video: {path, sha256}` 可指定已有底片。声明区域之外保留底片像素，`source_restore` 才从源片恢复。`proposal_video` 同样绑定路径与真实哈希。源片比底片短时默认拒绝；只有明确设置 `hold_source_tail_frames` 才允许相应数量的末帧延展，时钟不一致仍拒绝。这是显式保留旧行为，不是对新视频自动补帧。

每帧复用依据包含源片、底片、该帧的操作顺序/实际参数/供体、模型、实现与解码工具版本。只改生效边界时，未受影响的帧不重新做修复计算；参数、供体或素材改变时相应帧失效。源片、底片或实现改变时保守失效。旧母版及帧索引必须核验哈希，取出的像素也逐帧校验。

缓存只引用已完成的无损母版并增加小型 JSON 索引，不另存逐帧 PNG。缺失旧母版会重算；被篡改的文件会停止。完全相同配方的资产已过期时，新建 rebuild 版本，不覆盖旧配方、失败记录及旧审核。输出仍默认为 `approved_for_reuse=false`，必须重新绑定实际结果并按原质量流程审查。

目前仍需要读取源片、读取被复用的母版帧以及完整无损编码；不承诺每种廉价修复都提速。已验证的是本次三类旧操作的迁移，任意历史 Python 脚本不会被自动拦截或自动改造成增量执行。

像素等价和边界回归见 `tests/test_incremental_repair.py`；旧实验概述见 [维护历史](../../docs/history.md)。真实画面验收与这些执行测试分开报告。
