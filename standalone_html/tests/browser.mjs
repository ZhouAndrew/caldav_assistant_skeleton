import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(process.env.SELECTOR_TEST_URL);
  await page.locator('[name=url]').fill(process.env.CALDAV_TEST_URL);
  await page.locator('[name=username]').fill('test');
  await page.locator('[name=password]').fill('test');
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
  await page.getByRole('button',{name:'Start / 开始',exact:true}).click();
  await page.getByText('操作已写入并回读验证。').waitFor();
  await page.getByRole('button',{name:'Stop / 停止',exact:true}).click();
  await page.getByText('操作已写入并回读验证。').waitFor();
  assert.equal(await page.getByRole('button',{name:'Start / 开始',exact:true}).isEnabled(),true);
  assert.deepEqual(errors, []);
  console.log('PASS browser + real Radicale: connect/discover/read/search/select taskId');
} finally { await browser.close(); }
