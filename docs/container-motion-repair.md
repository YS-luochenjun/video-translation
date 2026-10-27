# 使用气泡排版与局部动态修复

实际选路与限制见 [知识规则](../knowledge/rules/container-layout-and-local-motion-repair-v1.md)。两个入口均不调用付费服务，也不选择具体视频模型。

```sh
python3 bin/render_container_text.py recipe/bubble.json work/bubble.png
python3 bin/prepare_local_repair.py recipe/repair.json work/repair
```

气泡规格从 [container-text.json](../agent/templates/container-text.json) 开始，重新测量容器、头像与安全区，填写本机已验证字体路径和各语言换行；输出 PNG 与布局报告。

动态修复规格从 [local-repair.json](../agent/templates/local-repair.json) 开始，先探测实际视频。`source_frames` 是原视频总帧数；每个 clip 的 `source_frames` 是其原时轴半开区间，`actual_frames`/`fps` 来自实际媒体。可选 `use_frames` 必须落在该片段内，用于裁掉重复上下文。程序验证声明的一致性，不替代媒体探测、文件哈希绑定或真实去字审核。

按 `preparation.json` 的输入顺序给 FFmpeg：输入 0 为原片或已核验底片，接下来为各实际修复片段，最后 `-loop 1 -i mask.png`。加载 `filter.txt`，输出 `[v]`，保持原始视频帧数和帧率。mask 中 255 表示完全使用修复像素，0 表示完全保护底片。采用区域由人工看连续帧决定，不硬编码为某条广告坐标。

图像滤镜不接管音轨；画面完成后以完整已核验音轨单独 remux，再验证音频包哈希及成片完整解码。保留模型任务与输入证据，按项目现有 `fast-register` 或 `finalize` 入口完成登记和真实评审。此工具输出不能充当自动质量通过。
