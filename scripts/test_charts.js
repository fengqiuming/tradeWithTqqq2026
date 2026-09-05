/**
 * 图表渲染逻辑测试（node）
 *
 * 用法：node scripts/test_charts.js [index.html] [data/market.json]
 *
 * 覆盖：时间刻度自适应粒度、动作配色、信号标记、十字准线、悬停配置注册。
 * 这些是纯函数，不需要浏览器即可验证。
 */
const fs = require('fs');

const html = fs.readFileSync(process.argv[2] || 'index.html', 'utf8');
const DATA = JSON.parse(fs.readFileSync(process.argv[3] || 'data/market.json', 'utf8'));

// 抽取图表相关函数（actionColor → mountChart 之前）
const s = html.indexOf('const CHARTS = {}');
const e = html.indexOf('function mountChart');
if (s < 0 || e < 0) { console.error('抽取失败：找不到图表函数段'); process.exit(1); }
const code = html.slice(s, e);

const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtN = (v, d = 2) => v == null || !isFinite(v) ? '—' : v.toFixed(d);

const M = new Function('esc', 'fmtN', code + '; return {actionColor,actionTag,pickTicks,svgLine,CHARTS};')(esc, fmtN);

let ok = true;
const check = (name, cond, extra) => {
  console.log((cond ? '  ✓ ' : '  ✗ ') + name + (extra ? '  → ' + extra : ''));
  if (!cond) ok = false;
};

console.log('=== 1. 动作配色 ===');
const C = M.actionColor;
check('买入类为红', C('熊转牛买入') === '#c0392b' && C('回调加仓') === '#c0392b', C('熊转牛买入'));
check('牛转熊清仓为绿', C('牛转熊清仓') === '#0f6e56', C('牛转熊清仓'));
check('止损清仓为琥珀（与买卖区分）',
  C('止损清仓') === '#8a5a00' && C('止损清仓') !== C('牛转熊清仓'), C('止损清仓'));
check('标签中带颜色', /style="color:#c0392b/.test(M.actionTag('回调加仓')), M.actionTag('回调加仓'));

console.log('\n=== 2. 时间刻度自适应 ===');
const dates = DATA.dates;
const w250 = dates.slice(-250);
const t250 = M.pickTicks(w250, 16);
check('250 日窗口按「年-月」标注',
  t250.length > 0 && t250.every(t => /^\d{4}-\d{2}$/.test(t.label)),
  t250.map(t => t.label).slice(0, 4).join(' '));
check('250 日窗口每个月都标出（不隔月）', t250.length >= 12, t250.length + ' 个');
check('月份标签互不重复', new Set(t250.map(t => t.label)).size === t250.length);
check('刻度索引递增',
  t250.every((t, i) => i === 0 || t.i > t250[i - 1].i));

const tFull = M.pickTicks(dates, 10);
check('16 年窗口不按月（否则上百个标签）', tFull.length <= 12, tFull.length + ' 个');
check('16 年窗口标签为年份或年-月',
  tFull.every(t => /^\d{4}(-\d{2})?$/.test(t.label)),
  tFull.map(t => t.label).join(' '));

console.log('\n=== 3. 信号标记渲染 ===');
const n = dates.length;
const q = DATA.qqq;
const mk = [
  { date: dates[n - 200], color: C('熊转牛买入'), label: '熊转牛买入' },
  { date: dates[n - 150], color: C('牛转熊清仓'), label: '牛转熊清仓' },
  { date: dates[n - 100], color: C('止损清仓'), label: '止损清仓' },
];
const svg = M.svgLine([{ name: 'QQQ', values: q.slice(-250), color: '#1c1c1a' }],
  dates.slice(-250), { id: 't1', height: 250, maxTicks: 12, markers: mk });

const circles = [...svg.matchAll(/<circle cx="([\d.]+)" cy="([\d.]+)" r="4.5" fill="(#[0-9a-f]{6})"/gi)];
check('渲染出 3 个标记点', circles.length === 3, circles.length + ' 个');
check('标记颜色对应动作',
  circles.map(c => c[3]).join(',') === [C('熊转牛买入'), C('牛转熊清仓'), C('止损清仓')].join(','),
  circles.map(c => c[3]).join(' '));
check('标记坐标在画布内',
  circles.every(c => +c[1] >= 56 && +c[1] <= 966 && +c[2] >= 14 && +c[2] <= 250));
check('窗口外的信号被过滤掉',
  M.svgLine([{ name: 'QQQ', values: q.slice(-250), color: '#000' }], dates.slice(-250),
    { markers: [{ date: '2001-01-02', color: '#000', label: 'x' }] }).indexOf('<circle') < 0);

console.log('\n=== 4. 十字准线与悬停配置 ===');
check('包含 data-cross 准线组', svg.includes('data-cross'));
check('准线默认隐藏', /data-cross[^>]*style="display:none"/.test(svg));
check('悬停配置已注册', !!M.CHARTS['t1'] && M.CHARTS['t1'].n === 250);
check('配置含日期与标记',
  Array.isArray(M.CHARTS['t1'].dates) && M.CHARTS['t1'].markers.length === 3);

console.log('\n=== 5. tooltip 数据完整性 ===');
const cfg = M.CHARTS['t1'];
const extras = [{ name: 'TQQQ', value: '12.34', color: '#1c1c1a' }];
const svg2 = M.svgLine([{ name: 'QQQ', values: q.slice(-250), color: '#1c1c1a' }],
  dates.slice(-250), { id: 't2', markers: mk, extra: () => extras });
check('extra 回调被存入配置', typeof M.CHARTS['t2'].extra === 'function');
check('extra 返回 TQQQ 行', M.CHARTS['t2'].extra(0)[0].name === 'TQQQ');
check('每条序列都有 name（tooltip 要用）',
  M.CHARTS['t2'].series.every(s => typeof s.name === 'string' && s.name.length > 0));

console.log('\n=== 6. 边界情况 ===');
check('空数据返回占位', M.svgLine([], [], {}).includes('empty'));
check('全 null 序列返回占位',
  M.svgLine([{ name: 'x', values: [null, null] }], ['2020-01-01', '2020-01-02'], {}).includes('empty'));
check('单点不崩', M.svgLine([{ name: 'x', values: [5] }], ['2020-01-01'], {}).includes('<svg'));

console.log('\n' + (ok ? '图表测试通过' : '图表测试失败'));
process.exit(ok ? 0 : 1);
