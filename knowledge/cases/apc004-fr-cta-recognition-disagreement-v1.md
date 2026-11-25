# APC004 法语片尾短句的识别分歧

适用范围为原片 `b7047ff003799971658f1465158243d1fd7de8ae3abfcee6d7795cdda1ab0d0b` 的法语 V6 成片及其 V7 对照试验。V6 成片哈希为 `6f24280848ece1025d8fd1fed7d0c7de105d9ed9f95f56a6eaf7d1b2c8da1e07`。

- V6 实际编码片尾的转写为「Teste magneau」，减速后的同段转写为「Teste maintenant」。两份转写各自绑定对应音频指纹。见 evidence:v6_normal_audio、evidence:v6_normal_asr、evidence:v6_slow_audio、evidence:v6_slow_asr。
- V7 降速重混试验的成片哈希为 `c1ce06430d69bb111874def2c63bee69561ea8ba464ca6f8f70c59cde1ff43b7`，其片尾转写为「Test Magno」。历史记录把 V7 留作未选试验，V6 的片尾口播仍待确认。见 evidence:v7_change、evidence:v7_audio、evidence:v7_asr、evidence:review。

同源续作按[首尾口播政策](../rules/audio-head-tail-review-v1.md)复核当前编码音轨。保留不同速度的原始结果，优先补正常速度听审。现有自动转写支持记录分歧，实际发音和可辨度仍待听审。该版本的发布阻断和内部 `revise` 以原评审为准。
