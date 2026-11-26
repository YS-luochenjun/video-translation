# Fireplay按编号接入与固定回传

宿主Agent读取Fireplay、操作已授权聊天及外部提交；项目CLI只登记证据、媒体、账本与状态，不复制登录凭据或假装调用连接器。政策入口是[AGENTS](../../AGENTS.md)，来源及参数分别在config/fireplay-intake.json、config/fireplay-publication.json、config/fireplay-youtube-routing.json、config/kie-access.json。新需求自动发现另见[巡检](fireplay-monitor.md)。本文保留接口和恢复步骤，不重复历史聊天原话。

按当前阶段进入对应章节。各专题保留原章节正文与执行依据。

## 持续执行到平台受理

[阅读此章节](fireplay-execution.md#持续执行到平台受理)。

## 读取与下载

[阅读此章节](fireplay-source-intake.md#读取与下载)。

### 原片优先级

[阅读此章节](fireplay-source-intake.md#原片优先级)。

### YouTube 缺片补取

[阅读此章节](fireplay-source-intake.md#youtube-缺片补取)。

## 聊天、授权与制作

[阅读此章节](fireplay-production-start.md#聊天授权与制作)。

## 需求状态

[阅读此章节](fireplay-production-start.md#需求状态)。

## 就绪、部分提交与unknown

[阅读此章节](fireplay-publication.md#就绪部分提交与unknown)。

## 上传命名与标签

[阅读此章节](fireplay-publication-metadata.md#上传命名与标签)。

## 平台路由与结案

[阅读此章节](fireplay-publication-metadata.md#平台路由与结案)。

