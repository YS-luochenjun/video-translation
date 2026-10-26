# 换机器部署

项目仓库为 <https://github.com/YS-luochenjun/video-translation>。Git 同步执行器、规则、公共配置、工作台和独立项目知识；每台机器安装自己的运行环境。当前安装入口面向 Windows x64，Linux 与服务器部署尚未验证。

## 新机器首次安装

准备 Git、uv、FFmpeg 和 ffprobe，并加入 PATH。安装目标语言所需字体。首次安装会联网下载 Python、依赖与当前路由所需本地模型；远端音视频服务仍使用 API。

在 PowerShell 中检查工具，再进入准备存放项目的位置：

```powershell
git --version
uv --version
ffmpeg -version
ffprobe -version
git clone -c core.longpaths=true https://github.com/YS-luochenjun/video-translation.git
cd video-translation
.\bin\setup.ps1
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

克隆命令为该仓库开启 Windows 长路径支持，保留知识证据的原目录结构。在本机 `.env` 填写 `KIE_API_KEY`，不要将密钥发到聊天、提交 Git 或写入文档。执行检查：

```powershell
.\bin\va.ps1 doctor
.\bin\va.ps1 check
.\bin\va.ps1 knowledge-audit
.\.venv\Scripts\python.exe bin/check_repository.py
.\bin\va.ps1 kie-authorization
```

确认新机器的实际操作者、付费使用范围和预算授权。授权状态的查询不会代替新授权，也不继承另一操作者的付费权限。`doctor` 只检查本地条件；测试与知识审计通过后，真实视频仍按项目规则制作、逐项审核。

在新机器的 AI 宿主中打开整个项目文件夹。宿主应能执行本地命令、读取文件、查看图片并使用图像编辑工具，依照根目录 `AGENTS.md` 工作。提供实际视频或链接与目标语言即可开始。

## 查看工作台

在项目根目录执行：

```powershell
.\workbench\start.ps1 -Background -Open
```

工作台只监听本机，默认地址为 <http://127.0.0.1:8768>。它读取这台机器已有任务和交付包；新安装且没有迁移旧任务时，显示空列表。详细能力见 [工作台说明](../workbench/README.md)。

## 后续同步

先停止本机制作任务，确认本地修改已经保存，再获取更新：

```powershell
git status --short
git pull --ff-only
.\bin\setup.ps1
.\bin\va.ps1 doctor
.\bin\va.ps1 check
```

存在本地修改或分支分叉时先处理差异，保留已有工作后再同步。使用快速前进更新，不强制覆盖本机文件。setup 安装或复用当前依赖，按新目录重新绑定 Python；不要从旧机器直接搬运 `.venv/`。

## 历史视频和任务另行迁移

源码仓库不携带生产视频、交付库和本机账本。只需在新机器制作新视频时，完成上述安装即可。需要继续旧任务或复用旧成片时，在停止相关制作进程、确认没有正在提交的模型任务后，使用可信的私有传输方式复制所需数据到新机相同相对路径：

| 数据 | 迁移用途 |
| --- | --- |
| `outputs/` | 已输出的视频、交付包和复用资产 |
| `media/` | 原视频、源解析与同源快照 |
| `runs/` | 尚需续作的任务现场和实际模型回执 |
| `state/` | 请求预算、费用账本、批次、恢复及待办记录 |
| `knowledge/local/` | 私有案例与必要原始证据 |

只复制单条任务或部分交付包时，要按 [存储合同](../agent/contracts/storage.md) 保全其依赖。整个库迁移应保留原目录结构与字节，核验文件数量及哈希，保留旧机器数据直到新机器验证可恢复。复制已有任务的账本不代表授权新费用；未结束或费用未知的远端模型任务先核对真实 taskId 和状态，防止重复提交。

本机 `.env`、`*.local.json` 和宿主配置单独配置与确认；模型、字体、缓存与 Python 环境按安装流程准备。项目知识及必要证据已随源码分发，包含共享证据对象与存储索引，不要只摘取方法正文。

## 生成另一份干净源码

在已有安装环境的项目根目录执行，目标目录必须不存在：

```powershell
.\bin\va.ps1 workspace-export dist/new-source
.\bin\va.ps1 workspace-verify dist/new-source
```

导出按正向清单复制文件，包含当前未提交但处于正式源码目录的内容，排除凭据、私有知识、生产视频、运行账本、安装资产与 Git 历史。导出和核验不会删除原项目的 `outputs/` 或其他任务数据。发布前检查导出内容、知识审计、仓库检查及实际 Git 暂存清单；详见 [项目布局](project-layout.md)。
