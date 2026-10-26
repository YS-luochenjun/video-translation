# 逐实例视觉证据与放行

本流程是 strict 的完整逐实例门禁；fast 采用 [模式分支](../../knowledge/rules/neutral-visual-and-animation-gate-v4.md) 的共同要求及基本审核，风险区域可按需使用此工具补证。进入本流程生成的 pending 仍须真实审核，不因 fast 而自动通过。

新任务的 comparisons-v3 使用原尺寸流式裁图，取消临时逐帧 PNG，并复用实际像素完全相同的比较页；逐帧覆盖、源/结果绑定与逐实例质量门禁不变。旧证据按原格式继续验证。

`visual-pages RUN MANIFEST --instance ID --layer final --limit 2` 每次返回最多2页原尺寸图片及 next_frame，使用 `--after-frame` 继续。可选 source、neutral、neutral-0 等实际图层名；选择依据为页面图层顺序，不能按 binding.layers 列表推算横向位置。MCP 提供相同的 layer、limit、after_frame 参数。展示游标在 state/review-progress，既不赋予 pass，也不替代 reviewed_frames；只会减少重复定位和过大输出。动态区域仍按原要求连续观察。

图集支持 `--columns 1..4`（MCP 为整数 `columns`），在不缩放或抽掉帧的情况下横向排列连续原尺寸帧；默认仍为一列。多列图需用原尺寸查看，显示被缩小时改为单列或单页。

本流程核验审查证据和版本，不自动判断图像已经修好。证据生成只产生pending；不得用循环把模板全部填写为pass，或把OCR为空、文件存在、检测零异常写成视觉通过。

## 1. 无字底片

已有inventory和镜头prepared_video后，运行：

```text
bin/va.ps1 visual-evidence RUN --stage neutral --shot s001
```

返回manifest和index.html。证据位于该run的inputs/visual-audit中，绑定源、底片、时间区间、文字位置和风险特征，不绑定目标译文。程序按实际解码PTS配对原片和底片，区域包含文字外围16像素，轨迹使用整个轨迹的包围范围。需要更大上下文时检查整幅构图和播放原片；区域证据不能证明区域外无缺陷。

移动/遮挡或背景静态性未确认时，保留整个实例区间的每个解码帧及边界；明确静态实例保留首、中、末和事件前后两帧。查看index.html中的原尺寸横向对照，不缩成一张总拼图；源/目标帧率不同时记录实际映射PTS，时间不匹配仍须评审打回。

先看原片和无字底片，再记录该实例的源样式、实际播放/构图观察、实际看过的帧、检查结论与具体观察。优先用下方精简输入；已有模板也可继续提交。引用页面必须来自同一份证据，动态区间不能只看抽样。兼容的单实例提交：

```text
bin/va.ps1 visual-review RUN <返回的manifest路径> <该实例观察文件路径>
```

观察文件使用run相对路径。source_appearance的四类字段分别描述字形/粗细、字面高度与对齐/留白、色彩效果、运动/遮挡。review_type标明same_agent、independent或human，reviewed_at使用带时区ISO时间。不能自动声称独立审查或用户验收。具体观察应指出帧号/PTS和实际发现，重复的成组套话不能放行。

提交fail或pending会保留记录并阻止放行；空字段、缺页、错误哈希均不通过。全部实例审查完成后显式放行：

```text
bin/va.ps1 visual-release-neutral RUN --shot s001
```

此命令汇总已通过的逐实例结论，生成新的准备记录，更新inventory的准备记录指针。不会重编码底片，不覆盖原准备记录或旧审核。随后重新plan。新失败观察会阻断继续使用，失败历史和旧评审保留。

## 2. 代表语言与各语言成片

完成实际编码后运行 `visual-evidence RUN`。若有可分离资产，自动生成原片、无字底片、透明字层、实际成片的同时间对照；透明层显示在灰底上。模型直接编辑或普通本地叠字没有独立图层时，不伪造底片/图层，观察中必须说明route_limitations，并对实际源/成片完成全部必要检查。

成片观察另需target_requirements，以及erasure、background_and_foreground、typography_fit、motion_occlusion_timing四项结论。只有保留项的erasure允许有明确依据的not_applicable；其他必需项必须pass。共享底片通过不复制成目标语言审核。

`production RUN` 会自动生成这份待审证据；也可继续使用原命令分步操作。完成逐实例visual-review和原有整片/音频/字幕评审后重新capture，再运行quality。代表语言通过后batch-approve；其余语言自己的观察和质量检查仍不可省略。

## 3. 三处门禁与版本失效

- 底片：prepared.verify_for_production检查独立准备证据及逐实例记录，未通过不能进入生产合成或共享。
- 代表语言：batch-approve和后续扩语重新验证其视觉审查，冻结审核哈希；修改后需重新放行。
- 最终交付：quality缺少或未通过视觉记录时返回revise，deliver重新执行质量门禁，不能凭旧pass复制交付。

实际视频、源片、字层或最终inventory/plan改变后，旧观察不能继续放行。同输入完整证据可复用，模板生成不覆盖已有观察；中断生成保留incomplete目录后另起一次生成，完整证据被篡改则停止调查。观察版本不可变，reviews.json只记录当前采用版本。

同一成片的代表语言放行与最终交付使用同一组逐实例观察，放行时重新核验完整性，不要求重填一份相同审核。`production`续跑保留已有编码；修改`inputs/visual-audit`中的审核草稿不触发重编码，正式底片记录、媒体和已冻结证据仍在每次使用前核验。`capture`按实际产物补齐概览、拼图和审核音频，视觉对照先创建目录也不会漏采，已有完整产物不重复生成。一次生成内部复用已解码的时间戳，跨次运行仍重新核验实际输入。

## 4. 历史与部署边界

没有批量回写旧run、原评审或交付包。已有final.mp4仍可使用；将旧底片用于新制作或主动再次交付时，需要补齐当前门禁。归档恢复保留已冻结审查及全部依赖，新的目标语言仍要审查。技术证据按现有run/交付保留策略管理，长期知识独立保存。

CLI和项目MCP均提供生成、单实例提交、底片放行接口，不依赖Codex专用API。程序能检查记录、覆盖和实际字节，不能证明评审人确实看过每一帧，也不能防止拥有本地源码/文件写权限的人伪造记录。对复杂修补仍需实际视觉判断；不以增加字段或减少检查冒充质量提升。

## 5. 精简记录与查看（2026-10-21）

新建run使用`comparisons-v2`：长期保留每个必要帧的无损原尺寸比较图、PTS/图层映射、构图图、视频和评审；比较图中已有的独立裁剪图只作生成临时文件。旧run和已有manifest按原格式读取，不回写。运行中被强制终止可能留下临时目录；续跑仍按原来的incomplete保护逻辑处理。提取临时文件不承担任务恢复或知识证据职责。

先用通用图集查看，省去为每个视频编写拼图脚本：

```text
bin/va.ps1 visual-pages RUN MANIFEST --instance t001 --max-height 1600
bin/va.ps1 visual-notes RUN MANIFEST review/visual-notes.json
```

图集按原尺寸拼接、不缩放，返回实际帧号、绝对路径和manifest哈希；用查看工具的original模式，若显示缩小则打开单帧。单帧超过指定高度时完整保留。图集缓存位于`work/visual-pages`，可再生成，不进入交付或知识证据依赖；原始比较图仍按完整证据归档。图集生成不等于已查看；整片播放、构图、音频仍按原要求审查。

观察草稿放在`review/`中，避免被当作制作输入触发重编码。notes顶层填写`manifest_sha256`（使用命令返回值）、`reviewer`、`review_type`，以及`instances`数组。数组内每项对应一个独立实例：

- `instance_id`、`reviewed_frames`，例如`[[20,35],40]`表示真实看过20至35及40帧；帧号取自manifest，不是抽样序号。没有默认“全部看过”。
- 原有`source_appearance`四类观察，以及`playback_observation`；成片另填`target_requirements`和适用的`route_limitations`。
- `checks`逐项填写`status`、具体`observation`、`frames`，后者也接受上述区间格式。类别和放行条件与原接口一致。

程序补齐binding_id、提交时间和页面路径。可一次提交多个已独立审查的实例，共享证据只校验一遍；不会复制检查结论、继承其他语言的通过状态或自动填pass。缺帧/缺观察保留待审，重复套话仍被最终门禁拒绝。观察文件不可变，索引原子更新；中断不会半更新多个实例的索引。放行、复用和交付继续完整核验。

发现失败时只记实际问题，无需为了阻断制作而填完通过表单。例如：

```json
{
  "manifest_sha256": "使用当前manifest的真实SHA256",
  "reviewer": "实际审查者",
  "review_type": "same_agent",
  "instances": [{
    "instance_id": "t001",
    "issue": {"check": "erasure", "frames": [82], "observation": "第82帧手机标题左侧仍有英文残留"}
  }]
}
```

失败记录更新该实例当前观察并阻断放行，历史记录保留。修复后按新产物重建证据并重新审查。知识总结继续通过reflect/deliver形成独立候选，不能从失败问题单直接推导通用已启用规则。
