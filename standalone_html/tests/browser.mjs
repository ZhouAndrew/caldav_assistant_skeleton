import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(process.env.SELECTOR_TEST_URL);
  await page.locator('#connect [name=url]').fill(process.env.CALDAV_TEST_URL);
  await page.locator('#connect [name=username]').fill('test');
  await page.locator('#connect [name=password]').fill('test');
  await page.getByRole('button', {name:'连接并读取'}).click();
  await page.getByRole('button', {name:'Browser task'}).waitFor();
  await page.locator('#query').fill('no match');
  await page.getByText('没有匹配的未完成任务。').waitFor();
  await page.locator('#query').fill('Browser');
  await page.evaluate(() => document.addEventListener('task-selected', event => { globalThis.selectedTaskId = event.detail; }));
  await page.getByRole('button', {name:'Browser task'}).click();
  assert.deepEqual(JSON.parse(await page.evaluate(() => globalThis.selectedTaskId)), [process.env.CALDAV_TEST_URL + 'browser/', 'browser-task', null]);
  await page.getByText('已从服务器重新读取任务详情。').waitFor();
  await page.locator('#task-details').getByRole('heading', {name:'Browser task'}).waitFor();
  // WordPress is independently mocked: exercise settings, capture, read-back and iframe preview.
  let wordpressContent = '';
  let wordpressOffline = false;
  await page.route('http://wordpress.test/**', async route => {
    if(wordpressOffline) return route.abort();
    const request=route.request(), url=new URL(request.url());
    if(url.pathname==='/daily-post') return route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><title>Daily</title><article>Full post</article>'});
    if(url.pathname.includes('/wp-json/wp/v2/posts') && url.searchParams.has('search')) {
      const body=wordpressContent ? [{id:9,link:'http://wordpress.test/daily-post',title:{rendered:'CalDAV Assistant Work Log 2026-10-08'},content:{raw:wordpressContent}}] : [];
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    }
    if(url.pathname.endsWith('/wp-json/wp/v2/posts') && request.method()==='POST') return route.fulfill({status:200,contentType:'application/json',body:'{"id":9}'});
    if(url.pathname.endsWith('/wp-json/wp/v2/posts/9') && request.method()==='POST') {wordpressContent=JSON.parse(request.postData()).content;return route.fulfill({status:200,contentType:'application/json',body:'{"id":9}'});}
    if(url.pathname.endsWith('/wp-json/wp/v2/posts/9') && url.searchParams.has('context')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:9,link:'http://wordpress.test/daily-post',title:{rendered:'CalDAV Assistant Work Log 2026-10-08'},content:{raw:wordpressContent}})});
    return route.fulfill({status:404,body:'not found'});
  });
  await page.locator('#wordpress-connect [name=url]').fill('http://wordpress.test');
  await page.locator('#wordpress-connect [name=username]').fill('editor');
  await page.locator('#wordpress-connect [name=password]').fill('application-password');
  await page.getByRole('button',{name:'保存到本设备'}).click();
  wordpressOffline=true;
  await page.locator('#quick-capture').fill('Capture text');
  await page.locator('#quick-capture').evaluate(element=>{const data=new DataTransfer();data.setData('text/plain',element.value);element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));});
  await page.getByText('已持久保存，仍有 1 项等待补写。').waitFor();
  await page.reload();
  await page.getByText('待补写 1 项。').waitFor();
  wordpressOffline=false;
  await page.getByRole('button',{name:'重试待补写'}).click();
  await page.getByText('✓ 已补写 1 项，Outbox 为空。').waitFor();
  assert.match(wordpressContent,/Capture text/);
  await page.locator('#post-preview').waitFor({state:'visible'});
  assert.equal(await page.locator('#post-preview').contentFrame().locator('article').textContent(),'Full post');
  // Break WordPress and prove the Task lane remains usable.
  await page.unroute('http://wordpress.test/**');
  await page.getByRole('button',{name:'刷新 Post'}).click();
  await page.getByText('读取 Post 失败；Task 操作不受影响。').waitFor();
  await page.locator('#connect [name=url]').fill(process.env.CALDAV_TEST_URL);
  await page.locator('#connect [name=username]').fill('test');
  await page.locator('#connect [name=password]').fill('test');
  await page.getByRole('button', {name:'连接并读取'}).click();
  await page.getByRole('button', {name:'Browser task'}).click();
  await page.getByText('已从服务器重新读取任务详情。').waitFor();
  await page.getByRole('button',{name:'Start / 开始',exact:true}).click();
  await page.getByText('操作已写入并回读验证。').waitFor();
  await page.reload();
  await page.locator('#connect [name=url]').fill(process.env.CALDAV_TEST_URL);
  await page.locator('#connect [name=username]').fill('test');
  await page.locator('#connect [name=password]').fill('test');
  await page.getByRole('button', {name:'连接并读取'}).click();
  await page.getByRole('button', {name:'Browser task'}).click();
  await page.getByText('已从服务器重新读取任务详情。').waitFor();
  assert.equal(await page.getByRole('button',{name:'Start / 开始',exact:true}).isEnabled(),false);
  await page.getByRole('button',{name:'Stop / 停止',exact:true}).click();
  await page.getByText('操作已写入并回读验证。').waitFor();
  assert.equal(await page.getByRole('button',{name:'Start / 开始',exact:true}).isEnabled(),true);
  let dropped = false;
  await page.route('**/browser/task.ics', async route => {
    if (route.request().method() === 'PUT' && !dropped) {
      dropped = true;
      await route.fetch();
      await route.abort();
    } else await route.continue();
  });
  await page.getByRole('button',{name:'Start / 开始',exact:true}).click();
  await page.getByText('操作未确认成功，请重新连接读取服务器状态；不要重复提交。').waitFor();
  assert.equal(await page.getByRole('button',{name:'Start / 开始',exact:true}).isEnabled(),false);
  await page.reload();
  await page.locator('#connect [name=url]').fill(process.env.CALDAV_TEST_URL);
  await page.locator('#connect [name=username]').fill('test');
  await page.locator('#connect [name=password]').fill('test');
  await page.getByRole('button', {name:'连接并读取'}).click();
  await page.getByRole('button', {name:'Browser task'}).click();
  await page.getByText('已从服务器重新读取任务详情。').waitFor();
  assert.equal(await page.getByRole('button',{name:'Start / 开始',exact:true}).isEnabled(),false);
  await page.getByRole('button',{name:'Stop / 停止',exact:true}).click();
  await page.getByText('操作已写入并回读验证。').waitFor();
  assert.equal(await page.evaluate(()=>Object.keys(localStorage).some(key=>key.endsWith(':pending'))),false);
  assert.deepEqual(errors, []);
  console.log('PASS browser + real Radicale: connect/discover/read/search/select taskId');
} finally { await browser.close(); }
