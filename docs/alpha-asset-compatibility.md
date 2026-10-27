# 透明资产的隐藏 RGB 与下游兼容

2026-10-27 对两个不同于原手部样例的新源、四份实际资产进行了验证：SHE053 表情前景（含一个全透明帧），以及同一 Remotion 诊断源的英文/阿语软边字层。结果已合并到 [文字与前景方法 v8](../knowledge/rules/method-animated-text-occlusion-v8.md)，完整来源见 [审查记录](../knowledge/curation/alpha-rgb-validation-20261027.json)。这不是新的广告质量验收。

| 实际操作 | 观察与采用边界 |
| --- | --- |
| Pillow 转 RGB、OpenCV 彩色读取 | 忽略 alpha，实际表情前景中的整幅原画面和英语会露出；需要透明效果就保留 alpha，消费者不支持时在明确底色上正确合成 |
| 仅清零 alpha=0 的 RGB | 已测原尺寸 alpha、可见 RGBA、四背景合成与 FFmpeg RGB 合成逐像素不变；只用于派生副本 |
| 正确预乘的缩放/旋转、已测 Pillow 路径 | 清理前后的实际合成一致；不外推到所有应用、色彩空间或变换 |
| OpenCV 逐通道插值 | 清理前后会改变边缘，表情资产缩放有314像素变化；不能默认在这种滤波前清零 |
| 把 alpha≤8 一并清掉 | 破坏软边；英文/阿语白底合成分别改变2055/2131像素，不采用这种阈值 |
| 按所有非零 alpha 紧裁切 | 保留原尺寸和原点后可原位还原；丢掉偏移会错位，也不能修正本来就不准确的前景遮罩 |

开发辅助函数是 `video_localizer.alpha_assets.sanitize`，明确接收8位 straight-alpha RGBA，返回新图片和位置记录。默认不裁切；没有自动改写或批量接入现有生产资产。调用方仍负责输入色彩/alpha解释、输出元数据、实际消费链以及视觉检查。

```python
from PIL import Image
from video_localizer.alpha_assets import sanitize

original = Image.open("foreground.png")
clean, placement = sanitize(original, crop=True, padding=2)
clean.save("foreground-derived.png")
# 将 placement 与新文件哈希一同登记；合成时恢复 origin。
```

通常在正确处理变换后的导出末步清理完全透明RGB。需要后续滤波时，使用正确的预乘/还原流程并比较实际合成，不靠“PNG支持透明”或“可见像素原值没变”推断所有变换安全。原始绑定资产、旧视频和历史审核保持原样。
