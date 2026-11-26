# 已授权去字试验

总入口见 [model-routing](model-routing.md)。

## 用户授权的三模型去字测试

2026-10-26用户明确授权用同一复杂片段比较Wan 2.7、Wan 2.6 Flash与Seedance Mini。`model-task`允许持有源哈希、run、请求预算、共同片段哈希、共同提示词和费用绑定的 `video_erasure_comparison` 授权测试；每模型一笔，合计有限额度。当时生产默认仍为Wan 2.7；Seedance Fast及其它模型不因此解禁。结果与实际计费审核后再决定默认，不把参考生成误写成保真编辑。当前模型按下述2026-11-09授权执行。

Gemini2.5ProTTS角色数量按[已观察输入预检](../../knowledge/rules/gemini25-tts-speaker-preflight-v1.md)检查；该版本的本地门禁、真实供应商500与unknown费用分别记录，不能把预检回归当作收费或音频质量证明。

2026-11-09用户明确将当前和在制视频处理切至Wan3.0，真实API模型为`wan/3-0-video`。新视频走单源reference编辑，audio:false与独立配音/回混；旧Wan2.7仅恢复原任务/结果，不重新提交。原位文字、运动、主体及实际时轴检查和原请求预算不变。历史三模型试验记录中的2.7身份不因此改写。
