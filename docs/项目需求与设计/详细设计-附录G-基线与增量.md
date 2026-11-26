# 详细设计附录 G：基线与增量

总入口见 [详细设计](详细设计.md)。

<a id="section-23"></a>

## 附录 G：执行依据与基线追踪

以下表列出合同、工作流和集成约定入口；它们是执行规范，模型返回和历史素材不能改写它们。

|类别|文件|首个标题|
|---|---|---|
|contracts|[agent/contracts/audio.md](../../agent/contracts/audio.md)|音频本地化|
|contracts|[agent/contracts/captions.md](../../agent/contracts/captions.md)|口播与字幕同步|
|contracts|[agent/contracts/knowledge.md](../../agent/contracts/knowledge.md)|知识、案例与交付素材|
|contracts|[agent/contracts/model-routing.md](../../agent/contracts/model-routing.md)|Codex 与专用模型|
|contracts|[agent/contracts/quality.md](../../agent/contracts/quality.md)|成品质量|
|contracts|[agent/contracts/storage.md](../../agent/contracts/storage.md)|存储、保全与清理合同|
|contracts|[agent/contracts/validation.md](../../agent/contracts/validation.md)|遮蔽测试|
|contracts|[agent/contracts/workflow.md](../../agent/contracts/workflow.md)|制作、检查、返工、交付|
|workflows|[agent/workflows/always-output.md](../../agent/workflows/always-output.md)|尽力改进，最终输出翻译视频|
|workflows|[agent/workflows/batch-production.md](../../agent/workflows/batch-production.md)|批次制作、预算与耗时|
|workflows|[agent/workflows/fast-delivery.md](../../agent/workflows/fast-delivery.md)|快速交付（默认）|
|workflows|[agent/workflows/local-production.md](../../agent/workflows/local-production.md)|本地配音与成片前失败结案|
|workflows|[agent/workflows/ocr.md](../../agent/workflows/ocr.md)|Codex 文字识别|
|workflows|[agent/workflows/production-completion.md](../../agent/workflows/production-completion.md)|从诊断版本完成正式交付|
|workflows|[agent/workflows/quality-feedback.md](../../agent/workflows/quality-feedback.md)|后续质量反馈如何影响旧交付|
|workflows|[agent/workflows/repair-recipes.md](../../agent/workflows/repair-recipes.md)|本地去字／去水印配方与风险预检查|
|workflows|[agent/workflows/video-localization.md](../../agent/workflows/video-localization.md)|广告视频本地化方法|
|workflows|[agent/workflows/visual-review.md](../../agent/workflows/visual-review.md)|逐实例视觉证据与放行|
|integrations|[agent/integrations/editors.md](../../agent/integrations/editors.md)|媒体与编辑器|
|integrations|[agent/integrations/kie.md](../../agent/integrations/kie.md)|KIE 适配器|
|integrations|[agent/integrations/mcp.md](../../agent/integrations/mcp.md)|工具接入边界|

### 基线源文件内容指纹

用于判定文档生成后关键源码是否变化，不替代Git版本或运行时证据。只记录公共代码/配置/规范；不含业务资产。

|文件|SHA256|
|---|---|
|[src/video_localizer/__init__.py](../../src/video_localizer/__init__.py)|`f32e939d2a24743a0e28af0fc2249c2fb538747869ae3fd03d2d15647a6f2294`|
|[src/video_localizer/asr.py](../../src/video_localizer/asr.py)|`5bf170f7edf2ec2438f41f03c3fb7c100566ebe88df322963a9ef5bf6d9dfcb9`|
|[src/video_localizer/audio.py](../../src/video_localizer/audio.py)|`15e25a6d5539b91cd591bdfc07e0b66c22492e14ecd807694cefe2979e2e48ab`|
|[src/video_localizer/batches.py](../../src/video_localizer/batches.py)|`836d4a6f7dcdc3679c82601f0419f2574b370eaca86d3993b5d98fb4dd9a6621`|
|[src/video_localizer/blind.py](../../src/video_localizer/blind.py)|`366fe33a40634faa37f7c1223cf471c11938bd7d54fb05df93c678c99234490d`|
|[src/video_localizer/budgets.py](../../src/video_localizer/budgets.py)|`7029efaef1bfa8c535a35ead3d4146ca291c2c22249f67a1147e68729249855c`|
|[src/video_localizer/bundles.py](../../src/video_localizer/bundles.py)|`08b06d70a0b12dd8025e6a3562806099b4619bc2ffa43f12237aa71182f4a693`|
|[src/video_localizer/candidate_index.py](../../src/video_localizer/candidate_index.py)|`44b5a243b6b4687736f0e17d1fc56530557f48e2a6e440adde76c909c4f0e0d1`|
|[src/video_localizer/captions.py](../../src/video_localizer/captions.py)|`f018fe1cb9e42fa317bf6df10da09583f1d841de3f2c5e87b01d7ba67a0d5fea`|
|[src/video_localizer/cli.py](../../src/video_localizer/cli.py)|`e17f787c42a30d496220e74679b2f70ca29d3cf0610bd087dc4073bd563c3c52`|
|[src/video_localizer/codex_visual.py](../../src/video_localizer/codex_visual.py)|`d0ce0b1644a763b65946d71e15182a4a52e5ca80f758dc9a007412361589f3f2`|
|[src/video_localizer/common.py](../../src/video_localizer/common.py)|`f2eceef23ac22b7f12c28d72867d5d547344072f9ebb40bda278d2248d47ae5e`|
|[src/video_localizer/compositor.py](../../src/video_localizer/compositor.py)|`4eb1483231ebc7c6aa5d9702d0ceafc6f803a504dbf9f571cba9eb0ac373a91c`|
|[src/video_localizer/contracts.py](../../src/video_localizer/contracts.py)|`30a29fb247239ec0db9e37ee00f61effe6dd40cefb54139913dbc57058048e2e`|
|[src/video_localizer/cost.py](../../src/video_localizer/cost.py)|`9eee748ca8e1617107d07106fee9c5c948f8961343a0c894e83bafe4ba726250`|
|[src/video_localizer/crop_stream.py](../../src/video_localizer/crop_stream.py)|`3d3284bdffdede685ea4352a4029ac5f4d38beda48f77bdaecf6e5c642384555`|
|[src/video_localizer/curation.py](../../src/video_localizer/curation.py)|`caa9a702fed84bc16a18b4af765f2e14a36bcce4aa55d43e1b4c178f86ef5255`|
|[src/video_localizer/curation_engine.py](../../src/video_localizer/curation_engine.py)|`fc55519a121ef4f887286f9415f1d2fc3e9be5823dd4a0b9c582f5ebd04292f7`|
|[src/video_localizer/delivery_index.py](../../src/video_localizer/delivery_index.py)|`5b04df7a367422d01965db7d564d22995f10f8f4c14a49c03ca7b86b3956b3d8`|
|[src/video_localizer/demo.py](../../src/video_localizer/demo.py)|`57d0197d51fe0ef278a292c3127e489a2e321f19ef910e7c26f0f5ef1ea6485a`|
|[src/video_localizer/evidence.py](../../src/video_localizer/evidence.py)|`7022ee80961fb5f0569a503ee998d72374c593199dafffd9794128b0057775a4`|
|[src/video_localizer/evidence_storage.py](../../src/video_localizer/evidence_storage.py)|`2bf2c91fa2c7a15826c09e5915206e08a873f0c72041ea31914c8a506eabdd3a`|
|[src/video_localizer/failure_closure.py](../../src/video_localizer/failure_closure.py)|`2a8357d3bbe3056dfe9ecb035b5b842d35fbd19a1bdc1f87e87cc0b63f4440d1`|
|[src/video_localizer/fast_delivery.py](../../src/video_localizer/fast_delivery.py)|`5949c4b8344a2c873d668d0be0a9fba441676dd87b2c4c0d3ec30bb4f54f48f9`|
|[src/video_localizer/finalization.py](../../src/video_localizer/finalization.py)|`acf8ef2f4c92588ad4596aba33933fcd5c0165fd4fcd1c884e36e4d75343466c`|
|[src/video_localizer/kie.py](../../src/video_localizer/kie.py)|`76d07843537fc83cdebc5475395733b059de6578df9fe30c93cb3900a9ba56d5`|
|[src/video_localizer/knowledge.py](../../src/video_localizer/knowledge.py)|`746a009c9c334eb1803006a85ae993d05af6358d7ece25d86dfce83e3036d184`|
|[src/video_localizer/knowledge_advisories.py](../../src/video_localizer/knowledge_advisories.py)|`d1b417bd76e4fe9cc50371d3e976fef97cbbb9ebdbc2de72e733f139f63cdcb2`|
|[src/video_localizer/knowledge_maintenance.py](../../src/video_localizer/knowledge_maintenance.py)|`41abe5e018dbdc33a111dd318ebe2be8475e7be8daee630c911a7b0dc7dce399`|
|[src/video_localizer/knowledge_records.py](../../src/video_localizer/knowledge_records.py)|`ac03e609fbe85e8214aa6bd8106d9dc18fa853c29f3c2b0fb86db5e9a62c3f0a`|
|[src/video_localizer/knowledge_review.py](../../src/video_localizer/knowledge_review.py)|`629c73660413c695e7d35e42b7c61155dd85d613dbeb384215bfb5084f979b0c`|
|[src/video_localizer/knowledge_usage.py](../../src/video_localizer/knowledge_usage.py)|`1a960b7cfb8f188e49666ddd2aac4296b6482508ad2154acbd3435c77d51fca6`|
|[src/video_localizer/languages.py](../../src/video_localizer/languages.py)|`d70fffc703021cfc47536f8e0941d8706e89bece1fb0983d533a6fe5764f317e`|
|[src/video_localizer/layout.py](../../src/video_localizer/layout.py)|`6fc65dec999186d184acbea05e8cc56faeed66d06699c897b06dad997061bd86`|
|[src/video_localizer/learning.py](../../src/video_localizer/learning.py)|`8e499424fb3d6febd723c1f2baba826fa03458c218dd72170dd363d8c1278961`|
|[src/video_localizer/learning_evidence.py](../../src/video_localizer/learning_evidence.py)|`016f8dea1dda545a2f90b1cd2581a0595279d6b93c164c46b823e5edca24a145`|
|[src/video_localizer/library.py](../../src/video_localizer/library.py)|`d397929a941e84a5ac2bff15f8351ada7b2ed76ec3092428299800ed2ea667d1`|
|[src/video_localizer/local_audio.py](../../src/video_localizer/local_audio.py)|`00b2c4e5105f9865744079111f61a63489762e1a86c4e2d6bf71106300915187`|
|[src/video_localizer/local_tts.py](../../src/video_localizer/local_tts.py)|`c9cefe2baf0e9318c80d3135f248c38ea40a2c47a267fb67fa3d981bb1ec0bc4`|
|[src/video_localizer/maintenance.py](../../src/video_localizer/maintenance.py)|`99f95e271d53c7218714197232c7e99f46df5d57aef0c38b5c02349f501bccf4`|
|[src/video_localizer/media.py](../../src/video_localizer/media.py)|`5ba25d3298f83761776264a0fcfa73f7280f7aa22e072e05b4a9d33afa7283bf`|
|[src/video_localizer/model_cache.py](../../src/video_localizer/model_cache.py)|`cacf3c47559f872496f948a669f7f269bf30a790e2ff64d87f5be4d383d0a54d`|
|[src/video_localizer/model_routing.py](../../src/video_localizer/model_routing.py)|`6be82f26e81091f0185f374b259e61a9f4682548ff29321ba7647ffcc1eb8749`|
|[src/video_localizer/model_tasks.py](../../src/video_localizer/model_tasks.py)|`f22c9315c580db28531265db5af67660cb03ddcb367d66244b0a2357fb5dfa0a`|
|[src/video_localizer/native_composition.py](../../src/video_localizer/native_composition.py)|`2bd7837ef573b488ee80d891ff776a86bccc587f3531780e1f065a5ea522150d`|
|[src/video_localizer/ocr.py](../../src/video_localizer/ocr.py)|`fb830a93963851b5c58081b4396b6c48370b366f5942230e75ad0d3f1239aa43`|
|[src/video_localizer/ocr_supplement.py](../../src/video_localizer/ocr_supplement.py)|`995bd71bd82145906f1503622a38664e3554832cfb5c0e016d88b278ef502238`|
|[src/video_localizer/prepared.py](../../src/video_localizer/prepared.py)|`0ff4c6d981565ed5197ed13ae592b1ec99413a395fa12a5fdfd24d6efec6a4df`|
|[src/video_localizer/production.py](../../src/video_localizer/production.py)|`6689975c19621f1e01d3dacab60854f3ebc0e2c3ef6f6d49b0d66d60ea835a2a`|
|[src/video_localizer/quality_holds.py](../../src/video_localizer/quality_holds.py)|`7af8b3d6ec070c55a210f10f276d7de5483ab8c7401047ed37ef121100b4b2e6`|
|[src/video_localizer/render_cache.py](../../src/video_localizer/render_cache.py)|`650c33435913a20e71aea4515a2363ecede9121ac00172cc308be8c9ccf6796e`|
|[src/video_localizer/repair.py](../../src/video_localizer/repair.py)|`bb9e9dab579d52b203dea7aa9a45138257ddddf1f0eeec2769fb197b891e7903`|
|[src/video_localizer/repair_frames.py](../../src/video_localizer/repair_frames.py)|`1520b3fb903892f413d26187a4ebc641e58dbd38f8b5dc9c62146601d585efe8`|
|[src/video_localizer/repair_masks.py](../../src/video_localizer/repair_masks.py)|`ff04895971dc434b962b0c8480fdc4988ac5d573999de2032a3d2c2727cb2440`|
|[src/video_localizer/request_tts.py](../../src/video_localizer/request_tts.py)|`92726bd6bda37ea9808922db923e44e8626580a8142e10817b1119c4fc0776dc`|
|[src/video_localizer/resources.py](../../src/video_localizer/resources.py)|`b9840dae039c599c4e550d4a67db6c9561cdec5bb7c69f6373dab2571c1eaf22`|
|[src/video_localizer/retention.py](../../src/video_localizer/retention.py)|`beacd376ae2093ddd3d9c926689730eb762b7d244cd2563fb2beb31414945938`|
|[src/video_localizer/reuse.py](../../src/video_localizer/reuse.py)|`1bdfc339ccdd0474f6ec2e0c2fd322e62bb28c4934d333159f6a7a317352060d`|
|[src/video_localizer/routing.py](../../src/video_localizer/routing.py)|`31f5fcb1452785788bb78a4f8e315a986074e43bedaf9271bba188a8276d2ac5`|
|[src/video_localizer/runtime.py](../../src/video_localizer/runtime.py)|`0ea37263615761bfe496f21fb4aa9e4f03b314f435cb58bbfbcb9aabeca1b2ba`|
|[src/video_localizer/source_state.py](../../src/video_localizer/source_state.py)|`87f5df110adcf5e55d52d41d20e84ab16bf0ad69a1fde16d8844d9ced55c3012`|
|[src/video_localizer/storage.py](../../src/video_localizer/storage.py)|`acb5c17c19b56c8999c2b7655a912ce5fd540c779174bc4e2c7774bde51481f9`|
|[src/video_localizer/storage_policy.py](../../src/video_localizer/storage_policy.py)|`008ab18745d44cdc78a2ba42629f45b428a7b23b65acd394811af06c3dffba28`|
|[src/video_localizer/surface.py](../../src/video_localizer/surface.py)|`9a5dec3e602666efc78627f6953bb39f3b025fe0c4e73ca5d6cb8dbce5ab8587`|
|[src/video_localizer/timing.py](../../src/video_localizer/timing.py)|`bdfa819c1547b3b61f668f675baf8c19261e8399fde6e9562926fb9a6dcb5b5c`|
|[src/video_localizer/visual_audit.py](../../src/video_localizer/visual_audit.py)|`9fcb5a620e05f0381713f9b303a5dfc0554a2a749c440eeb3be02991898d0134`|
|[src/video_localizer/visual_notes.py](../../src/video_localizer/visual_notes.py)|`0101b196407475e42c6b8df87b24201f418a00d44beb4a975662e0e408a729f7`|
|[src/video_localizer/visual_reuse.py](../../src/video_localizer/visual_reuse.py)|`d8ede9476321f53e2265b4cbfcabfdadecfa56bf4f94105a0efb588b17027f18`|
|[src/video_localizer/visual_storage.py](../../src/video_localizer/visual_storage.py)|`3e095f22d34aaf701ab57e09dfce5cf13522d63e30393ae81b107c4c1fb7fc53`|
|[src/video_localizer/work_packet.py](../../src/video_localizer/work_packet.py)|`662d907d5c2bf7d5fe7060bc209084aaf1374aeb1471955f86ad7e82c1e491d7`|
|[src/video_localizer/workflow.py](../../src/video_localizer/workflow.py)|`1cdae3bab0295bc61beb22e64bce4f89c7fa57b34c84df305df51030ede2b299`|
|[src/video_localizer/workspace.py](../../src/video_localizer/workspace.py)|`27c09778f581a1efaa0477f2f47835679d40539e5db56b9bf347c924f89c8a65`|
|[bin/mcp_server.py](../../bin/mcp_server.py)|`9af1e0052d10eefd44f8c1bb58b0263433dcd858e48dbbd89b07eedeec5eb3db`|
|[workbench/server.py](../../workbench/server.py)|`5cd3bd8ef3d31e83047dd8ff4a2057fdedc5b1ac84411720fdc16596f20eeacc`|
|[workbench/store.py](../../workbench/store.py)|`401d0b665ab94d7cf6cbc3dac9422ce939cdeb911f638b38601796126d9f0546`|
|[config/workspace.json](../../config/workspace.json)|`d8c55ce77e9cc16adce2682b7df009a71f8677fcb5b63b41303847973ff89171`|
|[config/quality.json](../../config/quality.json)|`9ca56ae48f0f2579d155852fd0e5f5f07eaf1206ccd6297bbf29cebc06ebb475`|
|[config/fast-delivery.json](../../config/fast-delivery.json)|`1559659b4436859a29a1c14bf25197015c83cdb8f466023e4daf02c0656940f2`|
|[config/budget-policy.json](../../config/budget-policy.json)|`47845a76c2df49ae319523d0e12f02e2a6dfa179afe0cc9b2d2b55cf8091e9c2`|
|[config/model-policy.json](../../config/model-policy.json)|`7645d5f4696571069a3871af1e3073887e75b5eddb13b151887a99ffb9af9293`|
|[config/model-routing.json](../../config/model-routing.json)|`12aaf2c0f59b081af490faa524250404bc4a9d8af763692acdc83d3ad46e1f81`|
|[config/maintenance.json](../../config/maintenance.json)|`c10e4186c45f952cac403de58e0504a69a47f22814853ea227ff7ba2f3b3a17c`|
|[config/storage-policy.json](../../config/storage-policy.json)|`31c12724a49a72fe874242ffad755d5bc3cb341635d5200eb9526dfe21a10398`|
|[config/hooks.json](../../config/hooks.json)|`f4ec0cf45243077a677032397919a0191322752169fb577d902763d6b1b2865f`|
|[config/language-aliases.json](../../config/language-aliases.json)|`c2018239246f5c5f7d235ded93f77f05b8d2e02352a766c6deef564e7d7d3027`|
|[config/content-features.json](../../config/content-features.json)|`f0c91b9da3dbf8b1ca8e0bc8f609bdb52752b3bdbe5470199961dee1849d6398`|
|[config/local-models.json](../../config/local-models.json)|`e725b25c9da68deb89efdfaad9ce3307408ef0510fc6821362b22ee48533364f`|
|[config/local-voices.json](../../config/local-voices.json)|`c450a49afaae63aa72f6ecdd695f828c2a0a2cd6ac7b634d53ece0365cd3fd2d`|
|[config/mcp.json](../../config/mcp.json)|`88b92d6d7bc7a93e2091c7ad664b20422bee3d75632d2f53cfd7d9abefcc54fb`|
|[config/workflows/video-localization/workflow.json](../../config/workflows/video-localization/workflow.json)|`a882a5a1984943be7f06ba270e82081b2e0ed830c3583505f1cd4cd9e4f7913f`|
|[config/profiles/company-default/profile.json](../../config/profiles/company-default/profile.json)|`39c896b15884582a31d2a44446100999e5de4d31e251d4e2f73518d84fb4a776`|

## 2026-10-26 增量：整理诊断与制作路线预检

`maintenance._references(root, candidates, errors=None)` 保持原返回集合接口。默认调用仍在读失败时抛错；维护流程传入错误列表时继续收集异常路径、异常类型及 JSON 行列号，不记录业务正文。任何读失败均将全部候选缓存视为受保护，维护回执为 deferred，不允许关闭现场。空候选集合直接返回，避免无意义的全库扫描。原始坏文件不改写，未结费用与活动锁检查不变。这是诊断改善，不是跳过坏文件后的删除授权。

新增 `readiness.inspect(root)`，由 `doctor` 输出 `route_readiness`：验证 Pillow 原生扩展、现行 layout 配置字体能否实际加载，以及当前 FFmpeg 是否支持 reference_composite 使用的 filter_complex_script 参数。状态为 ready 或 attention；FFmpeg 查询失败时支持性为 null，不虚报可用。不调用付费模型，不自动换字体，不修改成片或继承质量通过。

测试覆盖损坏 JSON 多项汇总、非法 UTF-8 保留缓存、禁止进入现场删除、缺失/损坏字体、FFmpeg 参数缺失与查询失败。实机诊断和测试回执位于本地 state/optimization-20261026；此目录不作为长期文档依赖。

## 2026-10-26 第二轮：参考合成与精确字体测量兼容

`media.render_reference` 继续保存 reference-filter.txt 作为实际配方，同时将同一滤镜图作为独立 argv 参数传入 `-filter_complex`，不再依赖新版 FFmpeg 已移除的 `-filter_complex_script`。滤镜、时间曲线、局部修复区域及编码配置保持原样。doctor 对应检查 filter_complex 支持性；上节的旧参数预检说明由此更新。

`layout.measurement_font` 集中解析字体：先查项目 assets/fonts，再查 Windows Fonts 中相同文件；macOS 对 Arial 的常规体和粗体使用系统 Supplemental 中的准确对应文件。其他缺失家族仍明确失败，不以 Arial 等替代。readiness 与测量共用解析器，并报告实际字体路径与加载状态。字体路径变化影响 layout 源码哈希，旧渲染缓存不会沿用相同实现指纹。

缓存系统的 Windows 字体环境假设尚未改动：缺少可核验字体环境时返回 None、禁用缓存。跨平台字体回退与字体环境指纹仍是后续设计项，不将取消保护作为性能优化。
