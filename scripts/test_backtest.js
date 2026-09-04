const fs = require('fs');
const html = fs.readFileSync(process.argv[2] || 'index.html', 'utf8');

// 抽取纯计算部分（ma200 → 图表段之前）
const s = html.indexOf('function ma200');
const e = html.indexOf('function svgLine');
const code = html.slice(s, e);

const DATA = JSON.parse(fs.readFileSync(process.argv[3] || 'data/market.json', 'utf8'));
const fmtN = (v, d = 2) => v == null ? '—' : v.toFixed(d);
const fmtPct = (v, d = 1) => v == null ? '—' : (v * 100).toFixed(d) + '%';
const fmtPctS = (v, d = 1) => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%';
const dayDiff = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);

const M = new Function('DATA', 'fmtN', 'fmtPct', 'fmtPctS', 'dayDiff',
  code + '; return {ma200,xirr,twrAndDD,backtest,runHold};'
)(DATA, fmtN, fmtPct, fmtPctS, dayDiff);

console.log('数据:', DATA.meta.qqq.bars, '根  ', DATA.dates[0], '->', DATA.dates[DATA.dates.length - 1]);
console.log('降级:', DATA.meta.degraded);
console.log('');

const P = { bullTh: 4, bearTh: 3, dipPct: 1, stopPct: 40, monthly: 1000, reentry: 'strict', startIdx: 0 };
const bt = M.backtest(P);
const hq = M.runHold(DATA.qqq, P);
const ht = M.runHold(DATA.tqqq, P);

console.log('=== 策略 ===');
console.log('  区间      ', bt.start, '->', bt.end, '(' + bt.years.toFixed(1) + ' 年)');
console.log('  累计投入  ', Math.round(bt.invested));
console.log('  期末总值  ', Math.round(bt.finalValue));
console.log('  IRR 年化  ', (bt.irr * 100).toFixed(2) + '%');
console.log('  最大回撤  ', (bt.maxDD * 100).toFixed(1) + '%');
console.log('  最长水下  ', bt.longestYears.toFixed(2) + ' 年');
console.log('  交易次数  ', bt.trades.length);
console.log('=== 基准 ===');
console.log('  定投 QQQ   IRR', (hq.irr * 100).toFixed(2) + '%  终值', Math.round(hq.finalValue), ' 回撤', (hq.maxDD * 100).toFixed(1) + '%');
console.log('  定投 TQQQ  IRR', (ht.irr * 100).toFixed(2) + '%  终值', Math.round(ht.finalValue), ' 回撤', (ht.maxDD * 100).toFixed(1) + '%');

console.log('\n=== 前 6 笔交易 ===');
bt.trades.slice(0, 6).forEach(t =>
  console.log('  ', t.date, t.act.padEnd(12), 'px=' + t.px.toFixed(2), 'sh=' + t.shares.toFixed(1), '$' + Math.round(t.amt), '|', t.note));

// 参数敏感性
console.log('\n=== 止损参数敏感性 ===');
[20, 30, 40, 50, 60].forEach(sp => {
  const r = M.backtest(Object.assign({}, P, { stopPct: sp }));
  console.log('  止损 ' + String(sp).padStart(2) + '%  IRR ' + (r.irr * 100).toFixed(2) +
    '%  回撤 ' + (r.maxDD * 100).toFixed(1) + '%  交易 ' + r.trades.length + ' 次');
});

const months = new Set(bt.dates.map(d => d.slice(0, 7))).size - 1;
const A = [
  ['有交易发生', bt.trades.length > 0],
  ['期末为正', bt.finalValue > 0],
  ['IRR 可解', bt.irr != null && isFinite(bt.irr)],
  ['IRR 合理(-95%~500%)', bt.irr > -0.95 && bt.irr < 5],
  ['回撤在 [-100%,0]', bt.maxDD <= 0 && bt.maxDD >= -1],
  ['投入 ≈ 月供×月份数', Math.abs(bt.invested - 1000 * months) < 2000],
  ['净值恒非负', bt.equity.every(v => v >= 0)],
  ['股数非负', bt.trades.every(t => t.shares >= 0)],
  ['日期单调递增', bt.dates.every((d, i) => i === 0 || d > bt.dates[i - 1])],
  ['基准 QQQ IRR 可解', hq.irr != null && isFinite(hq.irr)],
  ['基准 TQQQ IRR 可解', ht.irr != null && isFinite(ht.irr)],
];
console.log('\n=== 断言 ===');
let ok = true;
A.forEach(([n, r]) => { console.log((r ? '  ✓ ' : '  ✗ ') + n); if (!r) ok = false; });
console.log(ok ? '\n冒烟测试通过' : '\n冒烟测试失败');
process.exit(ok ? 0 : 1);
