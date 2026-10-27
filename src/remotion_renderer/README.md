# Optional Remotion typography renderer

This renderer is integrated through `video_localizer.typography` for explicit title/CTA/emphasis motion. Simple text keeps FFmpeg; model routing is unchanged. Use the [production adapter](../../docs/remotion-typography.md), which owns locking, font fitting, provenance, alpha checks and fallback. The earlier [evaluation](../../docs/research/2026-10-26-remotion-evaluation.md) remains a historical experiment.

Install the exact dependencies from this directory's package manifest and pnpm lockfile into `.runtime/deps/remotion`, keeping `node_modules` outside `src`. Supply a local Chrome executable to the job. On the tested Mac, the default Headless Shell 157 failed; official Headless Shell 156.0.8078.47 worked with a task-specific shell launcher:

```sh
#!/bin/sh
exec /absolute/path/to/chrome-headless-shell --disable-gpu --in-process-gpu "$@"
```

This is a measured local compatibility workaround, not a portable default or evidence that WebGL works. No system browser settings are changed. For a full Chrome for Testing executable, set `chromeMode` to `chrome-for-testing`.

Run `node src/remotion_renderer/render.mjs /absolute/path/to/job.json`. A job contains:

```json
{
  "runtime": "/absolute/project/.runtime/deps/remotion",
  "bundleDirectory": "/absolute/project/work/runs/RUN/bundle",
  "publicDirectory": "/absolute/project/runs/RUN/inputs/fonts",
  "browserExecutable": "/absolute/path/to/local-browser-launcher",
  "result": "/absolute/project/runs/RUN/review/render-metrics.json",
  "renders": [{"props": "/absolute/path/to/locale.json", "output": "/absolute/path/to/layer.mov"}]
}
```

Locale props contain `width`, `height`, `fps`, `durationInFrames`, explicit `fonts` (`family`, local filename), and `blocks`. Each block has a stable `id`, exact `text`, font `family`, `fontSize`, RGB `color`, `[x,y,width,height]` `box`, inclusive `startFrame` and exclusive `endFrame`. Optional `direction` supports `rtl`; `animated` adds a short scale/fade envelope; `emphasize` changes one whole word/phrase's color 25 frames after entry. Optional `track` contains increasing `{frame,x,y,rotation}` keys. Geometry uses pixels; rotation uses degrees. The caller supplies all tracking and timing. Keep Arabic words intact for joining. Preflight actual glyph coverage and inspect every language; the input validator is not a translation or font-quality gate.

The renderer emits PNG-based ProRes 4444 with transparency, plus timings. It uses a shared browser/bundle and concurrency 2. Production rendering is the default; explicitly set `isProduction:false` only for a development evaluation. Rendering flags do not establish commercial license eligibility. Local fonts and browser/runtime binaries are excluded from source exports.

On the tested FFmpeg, native ProRes decodes as `yuva444p12le`. The existing surface interface does not accept that format. The tested adapter is:

```sh
ffmpeg -i layer.mov -an -c:v qtrle -pix_fmt argb layer-argb.mov
```

The Python adapter creates source/locale/instance/font/parameter bindings, verifies actual alpha, uses the existing surface interface and records the actual renderer. Browser failures receive a checked static FFmpeg fallback whose effect losses require reviewer acknowledgement. The raw Node entry is a low-level component; it does not own workspace locks, production plans, speech alignment or acceptance. Production scope excludes tracks, masks and deformation. The optional track feature from the experiment remains available only to low-level callers and is not enabled by the production adapter.

Run input checks with `node --test tests/remotion-input.test.mjs`.
