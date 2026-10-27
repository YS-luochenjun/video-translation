# 字体检查与绑定

运行 doctor 时必须使用能加载项目依赖的 Python 3.10+。本机已有 Pillow/字体工具的二进制依赖使用 Python 3.12，macOS系统Python 3.9不适用。

`config/fonts.json` 记录实际字体家族、TTC集合中的字面索引、字重与验证样例。Mac默认使用已安装的真实字体：简中Heiti SC、繁中Heiti TC、日语Hiragino Sans、韩语Apple SD Gothic Neo、泰语Thonburi、印地语Devanagari Sangam MN；拉丁/西里尔及阿拉伯语使用已验证字形覆盖的Arial。其他可选字体仍可明确指定。Heiti常规位对应Light、粗体位对应Medium；doctor返回实际face名称，不假装另一个字重。

doctor的language_fonts分别检查各组常规/粗体的实际加载、字体家族和样例字符覆盖。未安装的Microsoft YaHei、SimSun、KaiTi、Yu Gothic、Malgun Gothic保留为optional_legacy_fonts_unavailable，不因为没有选用的Windows专有字体而阻止Mac路线。**明确指定了缺失字体时仍报错**，不把其他字体改名冒充该家族；实际稿件仍需逐字检查，并执行成片审核。

未明确指定家族时按目标locale选择；仅无locale才根据文本脚本判断。繁体或纯汉字日语应提供目标locale。工作流把请求locale传给实际渲染和缓存，不继承另一语种的字体选择。FFmpeg按真实字面抽取本次字体并加载到本段fonts目录，测量与渲染使用相同字重。字体回执保存在font-records目录，避免libass把JSON误当字体文件。缺字、非法家族、绑定字节变化均阻止继续。

Remotion动态文字需要单字面TTF/OTF，可执行：

```sh
python3 bin/va.py font-bind RUN --family 'Apple SD Gothic Neo' --bold --text '지금 시작'
```

返回的path/sha256直接填写到该实例display.font_asset。该命令将集合中正确字面提取到run/inputs/fonts，保留真实家族、轮廓和字重，并生成来源哈希/字面索引回执；重复绑定会核验已有产物，不能悄悄覆盖变化的字体。字体路径不能跨机器当作已安装证明；换宿主重新运行doctor，并将实际需要的字体资产按现有交付/安装合同保全。

渲染缓存包含实际系统/项目字体、字体配置及渲染代码身份。字体字节或配置改变后不能复用旧视觉段；已有完整成片和历史审核不被改写。缺少字体的主机不会因缓存索引存在就宣称支持。
