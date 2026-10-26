# 口播与字幕同步

来源：用户于2026-10-19指出当前中日样片音频与字幕不统一，并要求加入 Agent 项目。典型失败是口播“手势翻转棱镜特效怎么做……跟我一起学”，字幕另译为“如何制作……跟我学”；配音约4.1秒结束，字幕仍沿英文节奏显示到5.6秒。先锁定共同译稿，再按实际译后声音排字幕。

## 定稿与分类

有人声的清单中，每条文字填写 `text_role`：

- `speech_caption`：对应口播的字幕，填写 `speech_id`。
- `scene_text`：标题、按钮、UI、商品标语，保持画面含义与布局，不强行复述口播。
- `preserve`：品牌等明确保留项，配合 `action: preserve`。

`speech_segments[].target_text` 是最终说出的唯一稿件。每句设置 `caption_policy: verbatim` 和有序 `caption_ids`，这些字幕拼起来须等于该句；只容许句末标点/空白差异，数字、单位、顺序、用词须一致。若原片确实没有对应字幕，设 `caption_policy: none`、空 `caption_ids` 并填写 `caption_reason`，成片仍审查分类是否完整。把字幕误标为标题会造成遗漏，Agent 应对照原片逐实例判断。

TTS 的 `model-task` 请求填写有序 `speech_ids`，其文本来自上述定稿。`bin/mix_localized_narration.py` 在混音前检查同一稿件及完整人声覆盖。改变译稿应同时重建配音、字幕和评审。

## 实际音频对齐

独立配音路线使用已经裁切、变速、偏移并回混的完整音轨，以成片时间轴的秒数表示字词或短语。可用强制对齐工具、经核对的 ASR 或实际听审取得时间；保留提供者、方法和审核人。均匀按字数分配、套用源英文时间、从粗 ASR 句长猜逐词时间，都不能算已对齐。

Agent 参照 `agent/templates/caption-alignment-example.json` 填写 `analysis/caption-alignment.json`。`audio.path` 指向清单中选用的完整 `replacement_path`；音轨/原片/语种绑定哈希。每个 `units` 元素是一段实际听到的字词或短语，全文拼接须与定稿相同，并在字幕实例的分界处分开。

```powershell
# 先预览，再应用；均为本地操作，不提交模型任务
.\bin\va.ps1 captions RUN --alignment analysis/caption-alignment.json
.\bin\va.ps1 captions RUN --alignment analysis/caption-alignment.json --apply
.\bin\va.ps1 plan RUN
.\bin\va.ps1 render RUN
```

命令生成 `display.timed_fragments`，本地排版器按该片段显示整词或短语。原文擦除范围另存 `source_interval`，避免中文提前结束后原英文重新露出。模型去字底片覆盖完整原字及进出场；透明艺术字层需重建，且包含新的片段时间绑定。只修改 JSON 不会自动重绘已有 alpha 视频。

对齐数据和混音都进入 `caption_assets`；文件变化使计划失效。换语种、换译文或换音轨，应重做相应对齐；无字底片和原音乐/音效仍按既有资产合同复用。此命令不自动运行强制对齐引擎；没有实际时间证据时保留 pending。

直接由视频模型同时生成口播和字幕时，可以先用定稿和暂定源区间建立实验计划，随后从实际成片取得时间证据。若返工为本地排版，先使用已审完整混音和上述对齐合同，不能把暂定区间当成已核验结果。

## 成片核验与打回

`capture` 在实际视频哈希目录导出 WAV，并对每个字幕片段的进场前、进场、中间、结束前和结束处抽帧，创建待填写的 `caption-sync.json`。根据真实音频与画面填写：

- 顶层 `reviewer`、`method`、`decision`、成片音频和画面 `evidence`。
- 每实例的 `audio_units`：实际说出的内容和起止时间。
- 每实例的 `visual_units`：实际显示的内容和起止时间。
- 每实例的方法、结论和对应 `caption-tNNN-…` 边界帧与 WAV 证据。

`planned_units` 仅是计划，不是实际观测。必要时加密逐帧检查、使用视听模型或实际播放，不能因为模板给出时间就填 pass。没有听音或识字证据时保持 pending；同一 Agent 自审要如实署名。

完成审查后重新 `capture`，把修改后的报告纳入哈希清单，再运行：

```powershell
.\bin\va.ps1 caption-check RUN
.\bin\va.ps1 quality RUN
```

`caption-check` 只读检查，方便诊断旧候选；`quality` 同时检查字幕门禁、声音保留和其余画面要求。同步报告绑定实际视频、源片、清单、计划、字幕轨和成片 WAV。逐片段比较内容及实际视听时间，并与计划时间比较；阈值集中在 `config/quality.json`。音乐/音效保留、对白译文质量、字幕同步和口型同步是分别核验的事项。

脚本负责一致性、覆盖与证据绑定，实际声音和像素内容仍依赖有署名的审查。合成回归只能证明执行和拦截行为，不能代替真实广告视听验收。

## 历史迁移

质量配置2026-10-19.2开始启用本门禁。旧视频、账单和旧评审保留，重用旧视频前需补分类、共同稿件、对齐及新评审；不能把旧音频报告的 sync 字段补写成字幕通过。质量配置升级会让旧计划提示“标准已变化”，由 Agent 新建后续运行/明确有界迁移，不消耗旧任务的剩余返工次数来伪造新通过。
