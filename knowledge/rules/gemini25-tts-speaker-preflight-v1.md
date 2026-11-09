# Gemini 2.5 Pro TTS角色数预检

范围：KIE的google/gemini-2-5-pro-tts输入预检；依据2026-11-04保存的供应商错误与本地确定性回归，不假定未来接口或其他模型仍有同一限制。

五角色提交曾返回“speakers must contain at most 2 items”，没有taskId；该次6 credits预留保持unknown，不能据500推断免费或安全重发。当前执行器在建任务前要求每请求一至两名角色，三角色中性夹具验证会在inventory处理及jobs创建前拒绝。

新的多角色稿按真实轮次拆成每次不超过两角色的请求，保持角色身份、定稿和最终时间轴；不得通过换请求重发旧unknown。原费用、taskId查询能力、持续授权与预算分别核对。模型输入限制改变时先保存真实合同与回归证据再修订预检，不用生产付费调用探测。

证据为evidence:observation、evidence:regression和evidence:current_receipt。该回归只证明本地预检拒绝路径，不证明配音完整、性别正确、混音同步、供应商无扣费或成片通过；实际编码音轨仍按音频合同审核。
