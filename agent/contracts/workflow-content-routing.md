# 信息载体与方法选择

总入口见 [workflow](workflow.md)。

## 信息载体与方法选择记录

新请求记录 routing_contract_version=1。按 [三类广告条件](../../knowledge/rules/content-led-localization-v1.md) 判断 audio_led、onscreen_text_led 或 mixed；只发现音乐/非语言音效且无待译文字时可有据写 preserve_only。全片有主类型，实际需要时记录片段例外；不按字数、镜头人数或剧情地点自动归类。旁白、对白、独白及片尾口播全部进入人声清单，不受主类型影响。

在 inventory.routing_assessment 填 version=1、primary_type、reason、真实 evidence，以及 method_choices：每个需要翻译的 speech/visual 域记录 domain、命中的 method_id、reason、alternative、switch_when、stop_when。程序在 plan/fast-register 前检查完整性及已适用方法，语义判断仍由 Agent 负责。每句 speech_role 区分 dialogue/narration/monologue/spoken_cta/unknown，character_id 未确认可写 unknown 并补证。

已确认不同 character_id 自动补多人检索，待译文字补 onscreen_text；context.feature_origins 说明补齐依据。required 方法及政策完整返回，六条上限仅限制额外可选方法。快速模式同样冻结计划、知识正文、选择和待反馈项目；旧计划缺记录时提示重新登记现有资产，不伪造旧事实或重发模型。
