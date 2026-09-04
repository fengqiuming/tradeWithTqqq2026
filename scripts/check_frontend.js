const fs = require('fs');
const html = fs.readFileSync(process.argv[2] || 'index.html', 'utf8');

let ok = true;
const fail = m => { console.log('  ✗ ' + m); ok = false; };
const pass = m => console.log('  ✓ ' + m);

// ---------- 1. 内联脚本语法 ----------
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
console.log('内联 <script> 块数:', scripts.length);
scripts.forEach((src, i) => {
  try { new Function(src); pass(`脚本块 ${i + 1} 语法正确 (${src.length} 字符)`); }
  catch (e) { fail(`脚本块 ${i + 1} 语法错误: ${e.message}`); }
});

// ---------- 2. DOM 选择器与元素 ID 对应 ----------
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
const used = new Set([...html.matchAll(/\$\('#([A-Za-z0-9_-]+)'\)/g)].map(m => m[1]));
const missing = [...used].filter(u => !ids.has(u));
if (missing.length) fail('选择器找不到对应元素: ' + missing.join(', '));
else pass(`${used.size} 个 id 选择器全部命中`);

// querySelector('.xxx') / querySelectorAll('.xxx') 的类名
const clsUsed = new Set([...html.matchAll(/querySelectorAll?\('\.([A-Za-z0-9_-]+)'\)/g)].map(m => m[1]));
const clsDefined = new Set([...html.matchAll(/class="([^"]+)"/g)].flatMap(m => m[1].split(/\s+/)));
const clsMissing = [...clsUsed].filter(c => !clsDefined.has(c));
if (clsMissing.length) fail('类名选择器未定义: ' + clsMissing.join(', '));
else pass(`${clsUsed.size} 个类选择器全部命中`);

// ---------- 3. 动态生成的 id（data-tab -> panel-xxx）----------
const tabs = [...html.matchAll(/data-tab="([^"]+)"/g)].map(m => m[1]);
const panelMissing = tabs.filter(t => !ids.has('panel-' + t));
if (panelMissing.length) fail('tab 缺少对应面板: ' + panelMissing.join(', '));
else pass(`${tabs.length} 个 tab 都有对应面板 (${tabs.join(', ')})`);

// ---------- 4. 关键函数都被调用 ----------
const must = ['renderDataBar', 'renderSignal', 'runBacktest', 'renderRecords', 'loadData'];
must.forEach(f => {
  const defined = new RegExp('function\\s+' + f + '\\b').test(html);
  const called = new RegExp('\\b' + f + '\\s*\\(').test(html.replace('function ' + f + '(', ''));
  if (defined && called) pass(`${f} 已定义且被调用`);
  else fail(`${f} 定义=${defined} 调用=${called}`);
});

// ---------- 5. 外部资源 ----------
const ext = [...html.matchAll(/<(?:script|link)[^>]*(?:src|href)="([^"]+)"/g)].map(m => m[1]);
console.log('\n外部资源:', ext.length ? ext.join(', ') : '(无)');
ext.forEach(u => {
  if (/^https?:/.test(u)) fail('存在外部 CDN 依赖（应完全离线可用）: ' + u);
});
if (!ext.some(u => /^https?:/.test(u))) pass('无外部 CDN 依赖，可离线运行');
const local = ext.filter(u => !/^https?:/.test(u));
local.forEach(u => {
  if (fs.existsSync(u.replace(/^\.?\//, ''))) pass(`资源存在: ${u}`);
  else fail(`资源缺失: ${u}`);
});

// ---------- 6. CSS 变量与 class 引用 ----------
const cssVars = new Set([...html.matchAll(/--([a-z0-9-]+):/g)].map(m => m[1]));
const varUsed = new Set([...html.matchAll(/var\(--([a-z0-9-]+)\)/g)].map(m => m[1]));
const varMissing = [...varUsed].filter(v => !cssVars.has(v));
if (varMissing.length) fail('CSS 变量未定义: ' + varMissing.join(', '));
else pass(`${varUsed.size} 个 CSS 变量全部已定义`);

console.log('\n' + (ok ? '静态检查通过' : '静态检查失败'));
process.exit(ok ? 0 : 1);
