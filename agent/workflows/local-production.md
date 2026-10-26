# 本地配音与成片前失败结案

`work/` 是草稿桌，不是工具箱。代码放 `src/` 和 `bin/`，参数模板放 `agent/templates/`，模型注册表放 `config/`，安装好的依赖和权重放 `.runtime/`。后者不上传 Git，但安装入口和校验规则随项目提供。知识与独立错误案例保存在 `knowledge/`。

## 声音与图片

新配音统一使用 `tts-packet → model-task` 的 Gemini TTS。`local-tts` 只核验和复用已有完整声音，不产生新 Piper 推理；缺失或改稿时使用当前配音入口。模型、旧声音和用户素材不在本次策略切换中删除。

图片直接交给 Codex，使用 `codex-packet --stage image → codex-result`，遵循 [模型分工](../contracts/model-routing.md)。实际混音、字幕时间和成片审查继续使用原有合同。

## 没有成片的失败

```powershell
bin/va.ps1 close-failure RUN inputs/preproduction-failure.json
```

规格见 `agent/templates/preproduction-failure.json`。填写真实阶段、观察人、原因假设、逐项观察、实际文件 SHA256，以及尚未检查的范围。独立保存必要证据并建立候选与 inbox；相同输入幂等，新判断建立新案例。已有 candidate 时仍走正常 quality/reflect。不会改预算，不会把失败结案变为交付或正式知识。

## 修复与旧脚本

可选本地程序能力通过 `repair-run` 调用；LaMa 新推理已停用，图片方法由 Codex 自主选择。现有程序工具，包含颜色/连通域掩模、保护区域、显式实验性的泊松融合，以及之前迁出的三类修复。参数仍需按实际素材填写，详见 [修复配方](repair-recipes.md)。旧脚本的具体坐标、阈值和视觉判断不是通用默认值。尚未验证的光流对齐等素材专用尝试仅保存为历史参考，不作为可发布能力。

## 清空边界

只有在相关任务停止、草稿不再是唯一输入、知识和错误案例独立保全后，才可清空 `work/`。下次运行可能自动重建 `work/tmp` 或缓存，这是正常行为，不应重新出现安装依赖。平时的 run 清理继续遵守 [存储门禁](../contracts/storage.md)。历史一次性重置不构成日后自动清空规则；未知费用保留原账本与占位。

有价值的临时计算进入正式模块，具体参数进入配方，观察进入独立案例。历史脚本只作为来源数据，不由生产入口执行或自动进入规则检索。
