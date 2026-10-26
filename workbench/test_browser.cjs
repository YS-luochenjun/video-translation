/* Optional development QA. Requires Playwright; the workbench itself does not. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require(process.env.WORKBENCH_PLAYWRIGHT || 'playwright');

(async()=>{
  const root = path.resolve(__dirname, '..');
  const artifacts = path.join(root,'work','test-tmp','workbench-browser');
  fs.mkdirSync(artifacts,{recursive:true});
  const child = spawn(path.join(root,'.venv','Scripts','python.exe'),['-B',path.join(__dirname,'server.py'),'--port','0'],{cwd:root,windowsHide:true});
  let browser;
  try {
    const base = await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Server startup timeout')),10000);
      child.stdout.on('data',chunk=>{const match=String(chunk).match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
      child.once('error',reject);child.once('exit',code=>{clearTimeout(timer);reject(new Error('Server exited: '+code));});
    });
    browser=await chromium.launch({headless:true,executablePath:process.env.WORKBENCH_BROWSER || undefined});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base);
    await page.locator('#detail-body').waitFor({timeout:45000});
    assert(await page.locator('.task-button').count()>0,'real task records visible');
    await page.screenshot({path:path.join(artifacts,'desktop.png'),fullPage:true});
    const readAt=await page.locator('#read-time').textContent();
    await page.waitForFunction(old=>document.querySelector('#read-time').textContent!==old,readAt,{timeout:15000});
    await page.locator('#auto').uncheck();
    assert((await page.locator('#connection').textContent()).includes('暂停'));
    for(const name of ['instances','knowledge','execution','versions','overview']){
      await page.locator('[data-tab='+name+']').click();
      assert.equal(await page.locator('[data-tab='+name+']').getAttribute('aria-selected'),'true');
    }
    const media=page.locator('#output-video');
    if(await media.count()){
      await page.waitForFunction(()=>document.getElementById('output-video')?.readyState>=1,null,{timeout:15000});
      const duration=await media.evaluate(video=>video.duration);
      assert(duration>0,'real video metadata decoded');
      await media.evaluate(video=>{video.currentTime=Math.min(2,video.duration/2);});
      await page.waitForTimeout(400);
      assert(await media.evaluate(video=>video.currentTime)>0,'video Range seeking works');
    }
    await page.locator('#task-search').fill('NO_MATCH_FIXTURE');
    assert.equal(await page.locator('.task-button').count(),0);
    await page.locator('#task-search').fill('');
    for(const width of [768,414,375,320]){
      await page.setViewportSize({width,height:1000});
      const sizes=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert(sizes.scroll<=sizes.width+1,`no horizontal overflow at ${width}: ${JSON.stringify(sizes)}`);
      await page.screenshot({path:path.join(artifacts,`tasks-${width}.png`),fullPage:true});
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('[data-nav=knowledge]').click();
    await page.locator('.knowledge-entry').first().waitFor({timeout:15000});
    await page.locator('.knowledge-entry [data-document]').first().click();
    await page.waitForFunction(()=>document.querySelector('#document-text').textContent!=='读取中…');
    assert((await page.locator('#document-text').textContent()).length>20,'knowledge body visible');
    await page.locator('#close-document').click();
    await page.screenshot({path:path.join(artifacts,'knowledge.png'),fullPage:true});
    await page.locator('[data-nav=system]').click();
    await page.screenshot({path:path.join(artifacts,'system.png'),fullPage:true});
    assert.equal(errors.length,0,JSON.stringify(errors));
    fs.writeFileSync(path.join(artifacts,'result.json'),JSON.stringify({decision:'pass',viewports:[1440,768,414,375,320],checks:['real records','auto refresh','pause','tabs','search','video metadata and seek','knowledge text','no page errors'],screenshots:artifacts},null,2));
    process.stdout.write(JSON.stringify({decision:'pass',screenshots:artifacts})+'\n');
  } finally {
    if(browser)await browser.close();
    child.kill();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
