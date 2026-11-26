# 跨语言源解析及文字复用

总入口见 [batch-production](batch-production.md)。

## 文字识别与源解析复用

`codex-packet RUN --stage recognize` 提供实际图片和项目知识，由 Codex 看图完成实例识别，再用 `codex-result` 登记真实观察。`bin/ocr.py RUN` 是同一工作包的兼容入口。登记成功不代表实例覆盖、翻译或质量已通过，缺失观察继续 pending。

源解析库可复用已核验的源帧和历史 OCR 观察；复用仍需核对当前源哈希及覆盖范围。新识别不调用 RapidOCR 或 GLM，具体合同见 [文字识别](ocr.md) 和 [模型分工](../contracts/model-routing.md)。

新增语言时，主控将真实用户授权、完整targets和修订后总额度填入 `agent/templates/budget-amendment.json`，执行 `budget-amend ID SPEC`；旧费用和未知占位保留。同一授权重复提交幂等；不通过再次budget-open重置账本。历史账本只修额度时省略targets，不能自动迁移或降低已占用金额。
