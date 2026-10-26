# 项目语言别名：输入阶段使用

来源：用户于2026-10-20直接提供 LANGUAGE_ALIAS_GROUPS，并要求作为今后视频目标语言的项目知识。原始分组保存于 evidence:aliases，授权说明见 evidence:request。与具体视频无关，不以案例视频作为触发条件。

收到视频和目标语言时，先解释目标语言，再进行视频解析、翻译和选路。执行器通过 `language-resolve` 及创建任务入口读取 `config/language-aliases.json`。此为输入字典，单独按 `phase=language_resolution` 查询；不参与视频制作阶段的六条方法排名。

## 用户给定的完整映射

| 语言代码 | 中文名称 | 接受的别名 |
| --- | --- | --- |
| en | 英语 | en, us, us2 |
| pt | 葡萄牙语 | pt, por, portuguese, portugal, br, bra, brazil, brasil, ptbr, pt-br |
| es | 西班牙语 | es, esp, spanish, spain, mx, mexico, cl, co, pe |
| ja | 日语 | ja, jp, jpn, japanese, japan |
| de | 德语 | de, deu, ger, german, germany |
| fr | 法语 | fr, fra, fre, french, france |
| it | 意大利语 | it, ita, italian, italy |
| id | 印度尼西亚语 | id, ind, indonesian, indonesia |
| th | 泰语 | th, tha, thai, thailand |
| vi | 越南语 | vi, vie, vietnamese, vietnam, vn |
| ko | 韩语 | ko, kor, korean, kr, korea |
| zh | 中文 | zh, cn, chs, chinese, china, hk |
| zh-TW | 繁体中文 | zh-tw, zhtw, cht, traditionalchinese, tw, taiwan |
| ru | 俄语 | ru, rus, russian, russia |
| tr | 土耳其语 | tr, tur, turkish, turkey |
| ar | 阿拉伯语 | ar, ara, arabic |
| hi | 印地语 | hi, hin, hindi, in, india |
| pl | 波兰语 | pl, pol, polish, poland |
| nl | 荷兰语 | nl, dut, dutch, netherlands |
| fi | 芬兰语 | fi, fin, finnish, finland |
| sv | 瑞典语 | sv, swe, swedish, sweden, se |
| da | 丹麦语 | da, dan, danish, denmark, dk |
| ms | 马来语 | ms, may, malay, malaysia |
| ro | 罗马尼亚语 | ro, ron, romanian, romania |
| bn | 孟加拉语 | bn, ben, bengali, bd, bangladesh |
| fil | 菲律宾语 | fil, tl, tgl, tagalog, filipino, ph, philippines |
| hu | 匈牙利语 | hu, hun, hungarian, hungary |

## 解释与执行

- 忽略首尾空白和大小写。例如 `JA`、`jp`、`Japan`、`日语` 均解释为 `ja`。表内中文名称也可作为输入。
- 严格保留用户的分组：`br`、`pt-BR` 归 `pt`，`hk` 归 `zh`，`in` 归 `hi`，`tl` 归 `fil`。这些是本项目约定，不作为国家只有一种语言、地区没有差异的通用知识。
- `zh` 与 `zh-TW` 不合并。`hk → zh` 本身不说明简繁或粤语要求；明确提出繁体、粤语或地区口音时，主控应保留这些具体要求，必要时澄清后使用更具体的语言标签。
- 没有命中别名的已有语言标签（如 `zh-CN`、`ja-JP`、`es-MX`、`zh-HK`）保持原值，不擅自删掉地区。未知的自然语言名称不能猜成另一种语言。
- 新任务同时保留原始目标输入与解析后的目标语言；不回写旧任务、计划和已审核结果。表内代码只说明输入解释，不代表所有语言都已完成字体、配音、排版和视频质量验收。
- 例如“把视频翻译为 ja”就是翻译成日语；“翻译为 zhtw”就是繁体中文；“翻译为 br”按用户约定进入葡萄牙语组。地区用词与口音若有明确要求，应随任务简述一并传递。

后续修改映射时发布新版本并保留用户来源与原表，不把自动猜测写成新别名。此规则不调整视频制作方法、预算、审核标准或其他知识的适用范围。
