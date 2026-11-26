/* Optional development QA. Requires Playwright; the workbench itself does not. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require(process.env.WORKBENCH_PLAYWRIGHT || 'playwright');

async function checkScrollBoundaries(page, region) {
  await page.evaluate(() => { document.querySelector('main').style.minHeight = '180vh'; });
  try {
    await region.evaluate(element => element.scrollIntoView({block:'center'}));
    if (await page.evaluate(() => scrollY) < 40) await page.evaluate(() => scrollTo(0, 40));
    const bounds = await region.boundingBox();
    const viewport = page.viewportSize();
    const visibleTop = Math.max(0, bounds.y);
    const visibleBottom = Math.min(viewport.height, bounds.y + bounds.height);
    const pagePosition = await page.evaluate(() => ({
      top: scrollY, remaining: document.documentElement.scrollHeight - scrollY - innerHeight
    }));
    assert(visibleBottom - visibleTop > 40 && pagePosition.top > 0 && pagePosition.remaining > 0);
    await page.mouse.move(Math.max(0, bounds.x) + Math.min(bounds.width, viewport.width)/2, (visibleTop+visibleBottom)/2);
    for (const delta of [-330, 330]) {
      const boundary = await region.evaluate((element, direction) => {
        const limit = element.scrollHeight - element.clientHeight;
        element.scrollTop = direction < 0 ? 0 : limit;
        return {limit, top: element.scrollTop};
      }, delta);
      assert(boundary.limit > 50, 'fixture has an inner vertical scrollbar');
      await page.waitForTimeout(100);
      await page.mouse.wheel(0, delta);
      await page.waitForTimeout(240);
      const settled = await region.evaluate(element => element.scrollTop);
      assert(Math.abs(settled - boundary.top) <= 1, 'inner scroll remains at the boundary after pixel rounding');
      assert.equal(await page.evaluate(() => scrollY), pagePosition.top, 'inner scroll stops at either boundary');
    }
  } finally {
    await page.evaluate(() => { document.querySelector('main').style.minHeight = ''; window.scrollTo(0, 0); });
  }
}

(async()=>{
  const root = path.resolve(__dirname, '..');
  const artifacts = path.join(root,'work','test-tmp','workbench-browser');
  fs.mkdirSync(artifacts,{recursive:true});
  const projectPython = process.platform==='win32' ? path.join(root,'.venv','Scripts','python.exe') : path.join(root,'.venv','bin','python3');
  const child = spawn(process.env.WORKBENCH_PYTHON || (fs.existsSync(projectPython)?projectPython:'python3'),['-B',path.join(__dirname,'server.py'),'--port','0'],{cwd:root,windowsHide:true});
  let browser;
  try {
    const base = await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Server startup timeout')),10000);
      child.stdout.on('data',chunk=>{const match=String(chunk).match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
      child.once('error',reject);child.once('exit',code=>{clearTimeout(timer);reject(new Error('Server exited: '+code));});
    });
    browser=await chromium.launch({headless:true,executablePath:process.env.WORKBENCH_BROWSER || undefined});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    await page.clock.install();
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/#tasks');
    await page.locator('#detail-body').waitFor({timeout:45000});
    assert(await page.locator('.task-button').count()>0,'real task records visible');
    await page.locator('#task-list-toggle').click();
    assert(await page.locator('#task-list').isHidden());
    assert(await page.locator('#detail-body').isVisible());
    await page.locator('#task-list-toggle').click();
    await page.screenshot({path:path.join(artifacts,'desktop.png'),fullPage:true});
    const waitForSnapshot = timeout => page.waitForResponse(
      response => new URL(response.url()).pathname === '/api/snapshot' && response.ok(), {timeout});
    const requests = [];
    page.on('request', request => requests.push(new URL(request.url()).pathname));
    await page.clock.fastForward(16000);
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.clock.fastForward(3000);
    assert(!requests.includes('/api/snapshot'), 'idle time and tab visibility do not reload the snapshot');
    await Promise.all([waitForSnapshot(5000), page.getByRole('button',{name:'立即刷新'}).click()]);
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
    await page.locator('[data-nav=efficiency]').click();
    await page.locator('#timing-table').waitFor({timeout:15000});
    assert((await page.locator('#timing-table').textContent()).includes('平均耗时'));
    assert.equal(await page.getByText('预测与时间记录覆盖').count(),0);
    await page.route('**/api/ledger?*',async route=>{
      const response=await route.fetch();const data=await response.json();
      const request={started_at:'2026-11-01T00:00:00Z',finished_at:'2026-11-01T00:50:00Z',
        seconds:3000,task_count:20,language_count:10,seconds_per_language:300};
      data.historical_timing={request_mean_seconds:3000,request_median_seconds:3000,
        requests:Array.from({length:30},(_,index)=>({...request,id:`fixture-${index}`,code:'<img src=x onerror=alert(1)>'}))};
      await route.fulfill({response,json:data});
    });
    await page.evaluate(()=>window.LedgerUI.refresh());
    assert.deepEqual((await page.locator('#timing-table tbody tr').first().locator('td').allTextContents()).slice(3),
      ['50 分钟', '10', '5 分钟']);
    assert.equal(await page.getByRole('button',{name:'按语种'}).count(),0);
    assert.equal(await page.locator('#timing-table img').count(),0,'request codes escaped');
    const timingTable=page.locator('#timing-table');
    await timingTable.evaluate(table=>{table.scrollTop=150;});
    const headerPosition=await timingTable.evaluate(table=>table.querySelector('thead th').getBoundingClientRect().top-table.getBoundingClientRect().top);
    assert(headerPosition>=0 && headerPosition<3,'header stays visible on scroll');
    await page.evaluate(()=>window.LedgerUI.refresh());
    assert.equal(await timingTable.evaluate(table=>table.scrollTop),150);
    await page.screenshot({path:path.join(artifacts,'history-populated.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:700});
    await checkScrollBoundaries(page, timingTable);
    await page.setViewportSize({width:375,height:700});
    await checkScrollBoundaries(page, timingTable);
    for(const width of [768,375,320]){
      await page.setViewportSize({width,height:1000});
      const sizes=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert(sizes.scroll<=sizes.width+1,`timing no overflow at ${width}`);
    }
    await page.unroute('**/api/ledger?*');
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('[data-nav=knowledge]').click();
    await page.locator('.knowledge-entry').first().waitFor({timeout:15000});
    await page.locator('.knowledge-entry [data-document]').first().click();
    await page.waitForFunction(()=>document.querySelector('#document-text').textContent!=='读取中…');
    assert((await page.locator('#document-text').textContent()).length>20,'knowledge body visible');
    await page.locator('#close-document').click();
    assert.equal(await page.locator('#knowledge-kind').inputValue(),'method');
    await page.locator('#knowledge-kind').selectOption('candidate');
    await page.locator('#knowledge-review').selectOption('needs_lesson');
    assert.match(await page.locator('#knowledge-count').textContent(),/^\d+ 项$/);
    await page.locator('#knowledge-kind').selectOption('history');
    assert(await page.locator('#knowledge-review').isHidden());
    await page.locator('#knowledge-kind').selectOption('method');
    await page.screenshot({path:path.join(artifacts,'knowledge.png'),fullPage:true});
    await page.locator('[data-nav=system]').click();
    await page.getByRole('columnheader',{name:'Codex Token 总计'}).waitFor();
    await page.waitForFunction(()=>!document.querySelector('#system-usage').textContent.includes('正在读取会话用量'));
    assert.equal(await page.getByRole('heading',{name:'已完成会话用量'}).count(),1);
    assert.equal(await page.getByText('请求费用快照',{exact:false}).count(),0);
    assert.equal(await page.locator('#system-retries,#system-resources,#console-settings').count(),0);
    assert(await page.getByText('模型分工',{exact:true}).isVisible());
    assert.equal(await page.getByText('待维护事项').count(),0);
    await page.screenshot({path:path.join(artifacts,'system.png'),fullPage:true});
    await page.route('**/api/session-usage',route=>route.fulfill({json:{sessions:[
      {title:'用量明细测试',requirements:[{code:'ABC-20261103-001',language_count:13}],
        codex_total:10200,codex_breakdown:{input:10000,output:200,cached_input:7500},
        kie:{known:15,unknown:0,ambiguous:0}},
      {title:'旧记录测试',codex_total:10200},
      {title:'零实扣测试',codex_total:0,kie:{known:0,unknown:0,ambiguous:0}},
      {title:'待确认测试',kie:{known:20,unknown:1,ambiguous:0}},
      {title:'未归属测试',kie:{known:30,unknown:0,ambiguous:1}}
    ]}}));
    await page.getByRole('button',{name:'立即刷新'}).click();
    const breakdown=page.getByRole('row',{name:/用量明细测试/});
    await breakdown.waitFor();
    assert.deepEqual(await breakdown.locator('td').allTextContents(), ['用量明细测试','13','10,200','10,000','200','7,500 (75%)','15']);
    assert.deepEqual(await page.getByRole('row',{name:/旧记录测试/}).locator('td').allTextContents(), ['旧记录测试','—','10,200','—','—','—','—']);
    const codexSummary=page.locator('#system-codex-summary');
    assert.equal(await codexSummary.locator('strong').textContent(),'6,800 Tokens');
    assert.equal(await codexSummary.locator('small').textContent(),'共 20,400 Tokens · 3 / 5 个会话有记录');
    const kieSummary=page.locator('#system-kie-summary');
    assert.equal(await kieSummary.locator('strong').textContent(),'7.5 Credits');
    assert.equal(await kieSummary.locator('small').textContent(),'2 / 5 个会话费用已确认');
    await page.setViewportSize({width:375,height:1000});
    assert(await page.locator('#system-usage').evaluate(table=>table.scrollWidth>table.clientWidth));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.setViewportSize({width:1440,height:1000});
    await page.unroute('**/api/session-usage');
    await page.goto(base+'/console#requirements');
    await page.locator('#ledger-state').waitFor();
    assert.equal(page.url(),base+'/#ledger');
    for (const width of [1440, 375, 320]) {
      await page.setViewportSize({width,height:1000});
      const breadcrumb = page.getByRole('navigation',{name:'当前位置'});
      assert.match(await breadcrumb.innerText(), /广告视频本地化\s*\/\s*需求台账/);
      assert.equal(await breadcrumb.getByRole('button').count(), 0);
      assert.equal(await page.locator('.page-heading button').count(), 1);
      assert.equal(await page.getByRole('checkbox',{name:'自动更新'}).count(), 0);
      assert((await page.locator('.pathbar').boundingBox()).height <= 38);
      const [heading, refreshButton] = await Promise.all([
        page.getByRole('heading',{name:'需求台账'}).boundingBox(), page.getByRole('button',{name:'立即刷新'}).boundingBox()
      ]);
      assert(Math.abs(heading.y + heading.height/2 - refreshButton.y - refreshButton.height/2) <= 1);
    }
    await page.setViewportSize({width:1440,height:1000});
    assert.equal(await page.locator('#ledger-state option').count(),5);
    await page.locator('#ledger-capacity summary').waitFor();
    assert.equal(await page.getByText('正在读取制作并发…').count(),0);
    assert.match(await page.locator('#ledger-capacity summary').textContent(),/\/10.*剩余.*排队/);
    await page.locator('#ledger-capacity summary').click();
    assert(await page.getByText('每部原片的所有语种共用一个名额。', {exact:false}).isVisible());
    await page.locator('#ledger-capacity summary').click();
    await page.locator('.ledger-table tbody tr[data-progress]').first().waitFor();
    const tableStyles=await page.locator('.ledger-table').evaluate(table=>{
      const colored=[...table.querySelectorAll('tr:is([data-progress=active],[data-progress=done],[data-progress=blocked])')];
      const clear=element=>getComputedStyle(element).backgroundColor==='rgba(0, 0, 0, 0)';
      const header=table.querySelector('th:nth-child(3)');
      table.scrollTop=150;
      return {
        isolated:colored.length>0&&colored.every(row=>clear(row)&&[...row.cells].every((cell,index)=>clear(cell)===(index!==2))),
        edges:[header,...colored.map(row=>row.cells[2])].every(cell=>getComputedStyle(cell).borderInlineStartWidth==='1px'),
        sticky:getComputedStyle(header).position==='sticky'
      };
    });
    assert.deepEqual(tableStyles,{isolated:true,edges:true,sticky:true});
    await page.locator('.ledger-table').evaluate(table=>{table.scrollTop=0;});
    await page.getByRole('columnheader',{name:'重试次数'}).waitFor();
    const retryToggle = page.locator('[data-retry-demand]').nth(8);
    const demand = await retryToggle.getAttribute('data-retry-demand');
    const ledgerTable = page.locator('.ledger-table');
    await ledgerTable.getByRole('columnheader',{name:'序号',exact:true}).waitFor();
    const rowNumbers = () => ledgerTable.locator('tbody tr[data-progress] > td:first-child').allTextContents();
    const serials = await rowNumbers();
    assert.deepEqual(serials, serials.map((_,index)=>String(index+1)));
    const scrollPosition = () => ledgerTable.evaluate(table => ({
      top:table.scrollTop, left:table.scrollLeft, page:window.scrollY
    }));
    const retryMetrics = retryToggle.locator('.ledger-retry-metric');
    assert.deepEqual(await retryMetrics.locator('span').allTextContents(), ['Codex','KIE','Fireplay 回传']);
    const retryCounts = await retryMetrics.locator('strong').evaluateAll(values => values.map(value => ({
      count: value.textContent,
      highlighted: value.classList.contains('has-retries'),
      right: value.getBoundingClientRect().right,
      top: value.getBoundingClientRect().top
    })));
    assert(retryCounts.every(value => value.highlighted === (Number(value.count) > 0)));
    assert(retryCounts.every(value => value.right === retryCounts[0].right));
    assert(retryCounts.every((value,index) => index === 0 || value.top > retryCounts[index-1].top));
    assert.equal(await retryToggle.getAttribute('aria-expanded'),'false');
    await page.route('**/api/retry-activity?*', route => {
      const params = new URL(route.request().url()).searchParams;
      assert.equal(params.get('id'),demand);
      const older = Boolean(params.get('before'));
      return route.fulfill({json:{
        coverage:{kie_history:true,codex_retries:true},
        events:[{at:'2026-11-24T08:00:00Z',source:older?'kie':'fireplay',
          run:older?'运行示例':null,video_index:2,locale:'ja',operation:older?'status':'bind',
          attempt:older?1:2,reason:older?'http_503':'http_502',outcome:older?'failed':'success'}],
        next_cursor:older?null:'1795507200000:retry-fixture'
      }});
    });
    await retryToggle.evaluate(button=>button.scrollIntoView({block:'center',inline:'center'}));
    const desktopPosition = await scrollPosition();
    assert(desktopPosition.top > 0);
    await retryToggle.click();
    const retryPanel = page.locator('#ledger-retry-detail');
    await retryPanel.getByRole('row',{name:/Fireplay 回传.*原片 2.*素材绑定.*第 2 次重试.*502.*成功/}).waitFor();
    assert.equal(await retryToggle.getAttribute('aria-expanded'),'true');
    assert.equal(await retryPanel.getAttribute('colspan'),'7');
    assert.deepEqual(await rowNumbers(),serials);
    assert.deepEqual(await scrollPosition(),desktopPosition);
    assert.equal(await retryPanel.evaluate(node=>node.parentElement.previousElementSibling.querySelector('[data-retry-demand]').dataset.retryDemand),demand);
    await retryPanel.getByRole('button',{name:'下一页'}).click();
    await retryPanel.getByRole('row',{name:/KIE.*运行示例.*状态码 503.*失败/}).waitFor();
    await retryPanel.getByRole('button',{name:'上一页'}).click();
    await retryPanel.getByRole('row',{name:/Fireplay 回传.*原片 2/}).waitFor();
    await retryToggle.click();
    assert.equal(await retryPanel.count(),0);
    assert.equal(await retryToggle.getAttribute('aria-expanded'),'false');
    await page.screenshot({path:path.join(artifacts,'ledger.png'),fullPage:true});
    await page.setViewportSize({width:375,height:1000});
    assert(await ledgerTable.evaluate(table=>table.scrollWidth>table.clientWidth));
    assert(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth));
    await retryToggle.evaluate(button=>button.scrollIntoView({block:'center',inline:'center'}));
    const narrowPosition = await scrollPosition();
    assert(narrowPosition.top > 0 && narrowPosition.left > 0);
    await retryToggle.click();
    await retryPanel.getByRole('row',{name:/Fireplay 回传.*原片 2/}).waitFor();
    assert.deepEqual(await scrollPosition(),narrowPosition);
    await retryToggle.click();
    assert.deepEqual(await scrollPosition(),narrowPosition);
    await page.unroute('**/api/retry-activity?*');
    const requirementButton = page.locator('[data-requirement]').nth(8);
    await requirementButton.evaluate(button=>button.scrollIntoView({block:'center',inline:'center'}));
    const requirementPosition = await scrollPosition();
    const requirementDialog = page.locator('#ledger-detail');
    await requirementButton.click();
    await requirementDialog.waitFor();
    await requirementDialog.getByText('任务与视频',{exact:true}).click();
    assert.deepEqual(await scrollPosition(),requirementPosition);
    await page.keyboard.press('Escape');
    await requirementDialog.waitFor({state:'hidden'});
    await page.waitForURL(/#ledger$/);
    await page.locator('#refresh:not([disabled])').waitFor();
    assert.deepEqual(await scrollPosition(),requirementPosition);
    await page.setViewportSize({width:1440,height:1000});
    await page.getByRole('button',{name:'＋ 按需求号接单'}).click();
    await page.getByRole('dialog',{name:''}).waitFor();
    await page.locator('[data-close=intake-dialog]').click();
    await page.route('**/api/console/detail?*',async route=>{
      const response=await route.fetch();
      const data=await response.json();
      data.selected_run ||= 'run-fixture';
      data.nodes.find(node=>node.id==='publication').state='verified';
      await route.fulfill({response,json:data});
    });
    await page.locator('[data-nav=sessions]').click();
    await page.locator('.session').first().waitFor();
    assert(!requests.includes('/api/console/events'), 'the session page does not subscribe to background refresh events');
    assert.equal(page.url(),base+'/#sessions');
    await page.locator('.session').first().click();
    await page.locator('#chat-input').waitFor();
    const publication = page.locator('[data-node=publication]');
    await publication.getByText('已核验回传').waitFor();
    assert(await publication.evaluate(node=>node.classList.contains('running')));
    assert.equal(await page.getByText('待宿主同步',{exact:true}).count(),0);
    const dialog = page.locator('#artifact-dialog');
    const closeDialog = dialog.getByRole('button',{name:'关闭',exact:true});
    await publication.click();
    await dialog.locator('#artifact-body').evaluate(body=>{
      const content=document.createElement('p');
      content.textContent='弹窗正文 '.repeat(4000);
      body.append(content);
      body.scrollTop=body.scrollHeight;
    });
    assert(await dialog.locator('#artifact-body').evaluate(body=>body.scrollTop>0));
    const closeTop = (await closeDialog.boundingBox()).y;
    const dialogTop = (await dialog.boundingBox()).y;
    assert(closeTop>=dialogTop && closeTop<dialogTop+80);
    await closeDialog.click();
    await dialog.waitFor({state:'hidden'});
    await publication.click();
    await page.keyboard.press('Escape');
    await dialog.waitFor({state:'hidden'});
    await publication.click();
    await page.mouse.click(4,4);
    await dialog.waitFor({state:'hidden'});
    await publication.click();
    await page.evaluate(()=>location.hash='automations');
    await dialog.waitFor({state:'hidden'});
    await page.locator('[data-nav=sessions]').click();
    await page.locator('#chat-input').waitFor();
    await page.locator('#refresh:not([disabled])').waitFor();
    await page.unroute('**/api/console/detail?*');
    const sessionList = page.locator('#session-list');
    assert.equal(await sessionList.evaluate(list => getComputedStyle(list).overflowY), 'visible');
    const chatMessages = page.locator('.chat-messages');
    const previousMessages = await chatMessages.evaluate(messages => {
      const previous = messages.innerHTML;
      const content = document.createElement('div');
      content.className = 'message-body';
      content.textContent = '滚动测试消息 '.repeat(800);
      messages.replaceChildren(content);
      return previous;
    });
    const longMessage = chatMessages.locator('.message-body');
    assert.equal(await longMessage.evaluate(message => getComputedStyle(message).overflowY), 'visible');
    assert.equal(await longMessage.evaluate(message => getComputedStyle(message).borderTopRightRadius), '16px');
    await checkScrollBoundaries(page, chatMessages);
    await chatMessages.evaluate((messages, previous) => { messages.innerHTML = previous; }, previousMessages);
    await page.locator('#chat-input').fill('浏览器回归测试草稿');
    await page.locator('[data-nav=automations]').click();
    await page.locator('.auto-card').first().waitFor();
    await page.locator('[data-nav=sessions]').click();
    await page.locator('#chat-input').waitFor();
    assert.equal(await page.locator('#chat-input').inputValue(),'浏览器回归测试草稿');
    assert.equal(errors.length,0,JSON.stringify(errors));
    fs.writeFileSync(path.join(artifacts,'result.json'),JSON.stringify({decision:'pass',viewports:[1440,768,414,375,320],checks:['real records','manual refresh without background or foreground polling','compact breadcrumb and aligned refresh button','collapsible tasks','tabs','search','video metadata and seek','knowledge text','session usage','sticky timing table and preserved scroll','timing escaping and responsive layout','scroll boundaries in tables and chat'],screenshots:artifacts},null,2));
    process.stdout.write(JSON.stringify({decision:'pass',screenshots:artifacts})+'\n');
  } finally {
    if(browser)await browser.close();
    child.kill();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
