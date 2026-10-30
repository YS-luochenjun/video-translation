"""A portable browsing page linking canonical videos without copying media."""
from __future__ import annotations

import os
import tempfile
from html import escape
from pathlib import Path
from urllib.parse import quote

from .common import ROOT, WorkflowError, file_hash, inside, lock, read_json, require, utc_now


def _video(entry, root):
    """Validate the displayed result, not every reusable asset in the package."""
    folder = inside(root, entry["package"])
    require(folder.is_relative_to(root / "outputs") and folder != root / "outputs",
            "Package must stay within outputs")
    manifest_path = inside(folder, "manifest.json")
    video = inside(folder, "final.mp4")
    require(manifest_path.is_file(), "Missing manifest.json")
    require(video.is_file(), "Missing final.mp4")
    require(file_hash(manifest_path) == entry["manifest_sha256"], "Manifest changed")
    manifest = read_json(manifest_path)
    require(manifest["kind"] == "delivery" and manifest["identity"] == entry["video_sha256"],
            "Wrong delivery manifest")
    for key in ("source_sha256", "target_language", "video_sha256", "status", "origin_run_id"):
        require(manifest["metadata"][key] == entry[key], f"Catalog differs from manifest: {key}")
    require(file_hash(video) == entry["video_sha256"], "Video changed")
    from .quality_holds import active
    if active(entry["source_sha256"], entry["video_sha256"], root):
        return video, "质量异议 / 待返工"
    delivered = entry["status"] == "delivered" and manifest["metadata"].get("technical_decision") == "pass"
    if entry['status'] == 'delivered_with_issues':
        return video, '已输出 / 有瑕疵'
    return video, "已交付" if delivered else "参考 / 待改进"


def refresh(root=None):
    root = Path(root or ROOT).resolve()
    from .delivery_layout import catalog as delivery_catalog, settings
    managed = settings(root).get('enabled')
    out = inside(root, 'state/delivery-browser' if managed else 'outputs')
    out.mkdir(parents=True, exist_ok=True)
    with lock(out / ".catalog.lock"):
        path = delivery_catalog(root)
        if not path.exists():
            path = root / 'outputs/index.json'
        catalog = read_json(path) if path.exists() else {"entries": []}
        rows, counts = [], {"delivered": 0, "with_issues": 0, "reference": 0, "unavailable": 0}
        diagnostics = []
        for entry in sorted(catalog["entries"], key=lambda e: (e.get("origin_run_id", ""), e.get("archived_at", ""))):
            reason = ""
            try:
                video, status = _video(entry, root)
            except (WorkflowError, OSError, ValueError, KeyError, TypeError) as exc:
                video, status = None, "核验失败"
                reason = str(exc)
                diagnostics.append({"package": entry.get("package"),
                                    "target_language": entry.get("target_language"),
                                    "reason": reason})
            counts["delivered" if status == "已交付" else "with_issues" if status == '已输出 / 有瑕疵' else "reference" if video else "unavailable"] += 1
            link_text = "查看问题版本" if status == "质量异议 / 待返工" else "打开视频"
            action = (f'<a href="{quote(os.path.relpath(video, out), safe="/")}">{link_text}</a>'
                      if video else f"请检查交付包<details><summary>查看原因</summary>{escape(reason)}</details>")
            cells = [escape(str(entry.get(k, ""))) for k in
                     ("origin_run_id", "target_language", "video_sha256")]
            rows.append(f"<tr><td>{cells[0]}</td><td>{cells[1]}</td><td>{status}</td>"
                        f"<td>{action}</td><td><code>{cells[2][:16]}</code></td></tr>")
        html = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>视频交付目录</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px;color:#202833;background:#f8fafc}}
table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #dde3ea}}
a{{color:#1257aa}}code{{font-size:12px}}p{{color:#526071}}</style>
<h1>视频交付目录</h1>
<p>质量通过 {counts['delivered']} · 已输出 / 有瑕疵 {counts['with_issues']} · 参考 / 待改进 {counts['reference']} · 文件异常 {counts['unavailable']}</p>
<p>按任务、语言查看原有视频；此页面不保存视频副本。参考版本不代表通过验收。
质量异议优先于历史通过记录，问题版本只供追溯，不可直接交付或复用。</p>
<table><thead><tr><th>任务</th><th>语言</th><th>状态</th><th>视频</th><th>版本</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p><a href="reports/">历史批次字幕与说明</a>（如有）</p>
<p>生成于 {utc_now()}。已核对清单与视频哈希；全部复用依赖请用 archive-verify 核验。
交付状态沿用原记录，不代表新增人工验收。文件调整后运行 bin/va.ps1 delivery-index 刷新。</p>
</html>
"""
        target = inside(out, "index.html")
        descriptor, temporary = tempfile.mkstemp(dir=out, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(html)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {"page": target.relative_to(root).as_posix(), "counts": counts, "copied_media": 0,
            "diagnostics": diagnostics}
