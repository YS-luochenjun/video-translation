// Usage: node render.mjs JOB.json. Dependencies live in an isolated runtime directory.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {performance} from 'node:perf_hooks';
import {validateJob, validateProps} from './validate.mjs';

const job = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
validateJob(job);
const req = createRequire(path.join(path.resolve(job.runtime), 'package.json'));
const {bundle} = req('@remotion/bundler');
const {openBrowser, selectComposition, renderMedia, renderStill} = req('@remotion/renderer');
const start = performance.now();
const serveUrl = await bundle({entryPoint:fileURLToPath(new URL('./index.tsx',import.meta.url)),
  rootDir:path.resolve(job.runtime),
  outDir:path.resolve(job.bundleDirectory),publicDir:path.resolve(job.publicDirectory),
  webpackOverride: config => ({...config,resolve:{...config.resolve,
    modules:[path.join(path.resolve(job.runtime),'node_modules'),'node_modules']}})});
const bundled = performance.now();
const browser = await openBrowser('chrome',{browserExecutable:path.resolve(job.browserExecutable),
  chromeMode:job.chromeMode ?? 'headless-shell',logLevel:job.logLevel ?? 'error'});
const opened = performance.now();
const result = {versions:{remotion:req('remotion/package.json').version,node:process.version},browserExecutable:job.browserExecutable,
  chromeMode:job.chromeMode ?? 'headless-shell',concurrency:2,
  scope:'Typography rendering only; no model calls or localization quality approval',isProduction:job.isProduction !== false,
  bundleSeconds:(bundled-start)/1000,browserSeconds:(opened-bundled)/1000,renders:[]};
try {
  for (const render of job.renders) {
    await fs.mkdir(path.dirname(path.resolve(render.output)),{recursive:true});
    const props = JSON.parse(await fs.readFile(render.props,'utf8'));
    validateProps(props);
    const t = performance.now();
    const composition = await selectComposition({serveUrl,id:'Typography',inputProps:props,puppeteerInstance:browser});
    await renderMedia({composition,serveUrl,inputProps:props,puppeteerInstance:browser,
      outputLocation:path.resolve(render.output),codec:'prores',proResProfile:'4444',pixelFormat:'yuva444p10le',
      imageFormat:'png',concurrency:2,muted:true,isProduction:job.isProduction !== false,logLevel:'error'});
    const elapsed = (performance.now()-t)/1000;
    const stills = [];
    for (const sample of render.stills ?? []) {
      await fs.mkdir(path.dirname(path.resolve(sample.output)),{recursive:true});
      await renderStill({composition,serveUrl,inputProps:props,puppeteerInstance:browser,
        output:path.resolve(sample.output),frame:sample.frame,imageFormat:'png',logLevel:'error'});
      stills.push(sample);
    }
    result.renders.push({output:render.output,props:render.props,seconds:elapsed,
      frames:composition.durationInFrames,width:composition.width,height:composition.height,stills});
    await fs.writeFile(job.result,JSON.stringify(result,null,2)+'\n');
    process.stdout.write(JSON.stringify(result.renders.at(-1))+'\n');
  }
} finally {await browser.close({silent:true});}
result.totalSeconds=(performance.now()-start)/1000;
await fs.writeFile(job.result,JSON.stringify(result,null,2)+'\n');
