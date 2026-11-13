<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart, ScatterChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, MarkPointComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, CandlestickChart, LineChart, ScatterChart, DataZoomComponent, GridComponent, LegendComponent, MarkPointComponent, TooltipComponent, CanvasRenderer])

const base = '/index-reversal/api/v1'
const page = ref('overview'), token = ref(sessionStorage.getItem('im_admin') || '')
const error = ref(''), busy = ref(false), overview = ref({}), indices = ref([]), runs = ref([])
const selectedRun = ref(null), trades = ref([]), equity = ref([]), orders = ref([]), skipped = ref([])
const dailyCandles = ref([]), weeklyCandles = ref([]), chartPeriod = ref('1w')
const compareIds = ref([]), comparison = ref([]), chartEl = ref(null)
const signals = ref([]), config = ref({}), jobs = ref([]), market = ref('')
const selectedIndex = ref(null), candles = ref([]), indexSignals = ref([]), detailChartEl = ref(null)
let chart = null, detailChart = null, pollTimer = null
const form = ref({ index_id: '', strategy: 'ALL', start_date: '2024-11-13', end_date: '2026-11-12', initial_capital: 100000, risk_ratio: 0.01, max_position_ratio: 0.2, max_stop_ratio: 0.08, fee_ratio: 0.0003, slippage_ratio: 0.0005, take_profit_r: 2 })
const strategies = { A: 'A：2R 全部止盈', B: 'B：2R 减半 + 移动止损', C: 'C：全程移动止损' }
const summary = computed(() => selectedRun.value?.summary || {})
const selectedRunIndex = computed(() => indices.value.find(item => item.id === selectedRun.value?.index_id))

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(token.value ? { 'X-Admin-Token': token.value } : {}) }
  const response = await fetch(base + path, { ...options, headers: { ...headers, ...(options.headers || {}) } })
  const raw = await response.text()
  let body
  try { body = raw ? JSON.parse(raw) : null } catch { body = { detail: raw || response.statusText } }
  if (!response.ok) throw new Error(body?.detail || response.statusText)
  return body
}
function auth() { if (!token.value) token.value = prompt('输入管理 Token') || ''; if (token.value) sessionStorage.setItem('im_admin', token.value); return Boolean(token.value) }
async function load() {
  const [o, i, s, c, j] = await Promise.all([request('/overview'), request('/indices?size=200'), request('/signals?size=100'), request('/config'), request('/jobs')])
  overview.value = o; indices.value = i.items; signals.value = s.items; config.value = c; jobs.value = j
}
async function loadRuns() { runs.value = await request('/backtest/runs') }
async function nav(name) {
  page.value = name; error.value = ''
  try { if (['overview', 'indices', 'signals', 'config', 'jobs', 'backtest'].includes(name)) await load(); if (name === 'runs') { await load(); await loadRuns() } } catch (e) { error.value = e.message }
}
async function runAdmin(path, payload = {}) {
  if (!auth()) return
  busy.value = true; error.value = ''
  try { const result = await request(path, { method: 'POST', body: JSON.stringify(payload) }); alert(JSON.stringify(result, null, 2).slice(0, 1200)); await load() } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function setEnabled(item) {
  if (!auth()) return
  try { await request(`/indices/${item.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !item.enabled }) }); await load() } catch (e) { error.value = e.message }
}
async function saveConfig() {
  if (!auth()) return
  const keys = ['min_engulfed_count', 'min_bearish_count', 'max_lookback_weeks', 'volume_lookback_weeks', 'volume_warm_ratio', 'volume_strong_ratio', 'enable_forming_alert', 'enable_confirmed_alert']
  try { await request('/config', { method: 'PUT', body: JSON.stringify(Object.fromEntries(keys.map(key => [key, config.value[key]]))) }); await load(); alert('规则已保存，配置版本已增加') } catch (e) { error.value = e.message }
}
async function showIndex(item) {
  selectedIndex.value = item; page.value = 'detail'; busy.value = true; error.value = ''
  try { [candles.value, indexSignals.value] = await Promise.all([request(`/indices/${item.id}/candles?period=1w`), request(`/indices/${item.id}/signals`)]); await nextTick(); renderDetailChart() } catch (e) { error.value = e.message } finally { busy.value = false }
}
function renderDetailChart() {
  if (!detailChartEl.value) return
  detailChart?.dispose(); detailChart = echarts.init(detailChartEl.value)
  const lines = candles.value
  const marks = indexSignals.value.filter(x => !['INVALIDATED', 'RETRACTED'].includes(x.status)).map(signal => ({ coord: [signal.week_start, Number(lines.find(row => row.week_start === signal.week_start)?.close_price || 0)], value: `吞${signal.engulfed_count}` })).filter(x => x.coord[1] > 0)
  detailChart.setOption({ tooltip: { trigger: 'axis' }, legend: { data: ['周K', '成交量'] }, grid: [{ left: 55, right: 25, top: 45, height: '56%' }, { left: 55, right: 25, top: '76%', height: '13%' }], xAxis: [{ type: 'category', data: lines.map(x => x.week_start), axisLabel: { hideOverlap: true } }, { type: 'category', gridIndex: 1, data: lines.map(x => x.week_start), axisLabel: { show: false } }], yAxis: [{ scale: true }, { gridIndex: 1, scale: true }], dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], bottom: 0 }], series: [{ name: '周K', type: 'candlestick', data: lines.map(x => [Number(x.open_price), Number(x.close_price), Number(x.low_price), Number(x.high_price)]), itemStyle: { color: '#e95454', color0: '#18a782', borderColor: '#e95454', borderColor0: '#18a782' }, markPoint: { symbol: 'pin', symbolSize: 32, data: marks } }, { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: lines.map(x => x.volume == null ? null : Number(x.volume)), itemStyle: { color: '#8299ba' } }] })
}
async function submit() {
  if (!auth()) return
  busy.value = true; error.value = ''
  try {
    const keys = form.value.strategy === 'ALL' ? ['A', 'B', 'C'] : [form.value.strategy], created = []
    for (const strategy of keys) created.push(await request('/backtest/runs', { method: 'POST', body: JSON.stringify({ ...form.value, strategy, index_id: Number(form.value.index_id) }) }))
    if (created.length === 1) await showRun(created[0].id)
    else { compareIds.value = created.map(x => x.id); await loadRuns(); page.value = 'runs' }
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function showRun(id) {
  clearTimeout(pollTimer); busy.value = true; error.value = ''
  try {
    selectedRun.value = await request(`/backtest/runs/${id}`); page.value = 'result'
    if (['QUEUED', 'RUNNING'].includes(selectedRun.value.status)) { pollTimer = setTimeout(() => showRun(id), 1000); return }
    if (selectedRun.value.status === 'FAILED') { error.value = selectedRun.value.error_message || '回测失败'; return }
    chartPeriod.value = '1w'
    ;[trades.value, orders.value, skipped.value, equity.value, dailyCandles.value, weeklyCandles.value] = await Promise.all([request(`/backtest/runs/${id}/trades`), request(`/backtest/runs/${id}/orders`), request(`/backtest/runs/${id}/skipped`), request(`/backtest/runs/${id}/equity`), request(`/backtest/runs/${id}/candles?period=1d`), request(`/backtest/runs/${id}/candles?period=1w`)])
    await nextTick(); renderChart()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function setChartPeriod(period) {
  chartPeriod.value = period
  await nextTick()
  renderChart()
}
function renderChart() {
  if (!chartEl.value || !equity.value.length) return
  chart?.dispose(); chart = echarts.init(chartEl.value)

  const lines = chartPeriod.value === '1w' ? weeklyCandles.value : dailyCandles.value
  const candleName = chartPeriod.value === '1w' ? '指数周K' : '指数日K'
  const dates = lines.map(row => row.trade_date)
  const candleByDate = new Map(lines.map(row => [row.trade_date, row]))
  const equityByDate = new Map(equity.value.map(row => [row.trade_date, row]))
  const chartDateForTradeDate = tradeDate => lines.find(row => row.first_trade_date <= tradeDate && tradeDate <= row.last_trade_date)?.trade_date
  const point = order => ({ value: [chartDateForTradeDate(order.trade_date), order.fill_price], order })
  const visibleOrders = orders.value.filter(order => chartDateForTradeDate(order.trade_date))
  const buys = visibleOrders.filter(order => order.side === 'BUY').map(point)
  const partials = visibleOrders.filter(order => order.order_type === 'PARTIAL_TAKE_PROFIT').map(point)
  const sells = visibleOrders.filter(order => order.side === 'SELL' && order.order_type !== 'PARTIAL_TAKE_PROFIT').map(point)
  const skippedPoints = skipped.value.filter(item => chartDateForTradeDate(item.trade_date)).map(item => {
    const chartDate = chartDateForTradeDate(item.trade_date)
    const candle = candleByDate.get(chartDate)
    return { value: [chartDate, item.planned_entry_price || candle?.high_price], skipped: item }
  })
  const reasonNames = { SIGNAL_NEXT_OPEN: '信号后下一交易日开盘买入', STOP_GAP: '止损跳空', STOP_LOSS: '初始止损', TRAILING_STOP_GAP: '移动止损跳空', TRAILING_STOP: '移动止损', TAKE_PROFIT: '固定止盈', TAKE_PROFIT_GAP: '止盈跳空', TAKE_2R_HALF: '2R减仓', TAKE_2R_HALF_GAP: '2R跳空减仓', END_OF_RANGE: '回测区间结束' }
  const skipReasonNames = { STOP_DISTANCE_EXCEEDED: '止损距离超过上限', POSITION_ALREADY_OPEN: '已有持仓', INVALID_STOP: '止损价无效', INSUFFICIENT_CASH_OR_LOT: '资金或最小手数不足' }
  const tooltip = params => {
    const list = Array.isArray(params) ? params : [params]
    const date = list[0]?.axisValue || list[0]?.value?.[0] || ''
    const lines = [`<strong>${date}</strong>`]
    for (const item of list) {
      const order = item.data?.order
      const skippedItem = item.data?.skipped
      if (order) lines.push(`${item.marker}${item.seriesName}：信号 #${order.signal_id}（周线 ${order.signal_week || '-'}）<br/>成交日 ${order.trade_date}，成交价 ${order.fill_price.toFixed(4)}，数量 ${order.quantity}<br/>费用 ${order.fee.toFixed(2)}，原因 ${reasonNames[order.reason] || order.reason}`)
      else if (skippedItem) {
        const stopDetail = skippedItem.stop_ratio == null ? '' : `<br/>止损距离 ${(skippedItem.stop_ratio * 100).toFixed(2)}%，上限 ${(skippedItem.max_stop_ratio * 100).toFixed(2)}%`
        lines.push(`${item.marker}跳过：信号 #${skippedItem.signal_id}（周线 ${skippedItem.signal_week || '-'}）<br/>计划入场日 ${skippedItem.trade_date}，原因 ${skipReasonNames[skippedItem.reason] || skippedItem.reason}${stopDetail}`)
      }
      else if (item.seriesName === candleName) {
        const candle = candleByDate.get(date)
        if (candle) lines.push(`${item.marker}${candleName}：开 ${candle.open_price.toFixed(2)}　收 ${candle.close_price.toFixed(2)}<br/>低 ${candle.low_price.toFixed(2)}　高 ${candle.high_price.toFixed(2)}`)
      }
      else if (typeof item.value === 'number') lines.push(`${item.marker}${item.seriesName}：${item.value.toFixed(6)}`)
    }
    return lines.join('<br/>')
  }

  chart.setOption({
    tooltip: { trigger: 'axis', formatter: tooltip },
    legend: { data: [candleName, '策略净值', '买入', '部分卖出', '卖出', '跳过'] },
    grid: { left: 72, right: 76, top: 50, bottom: 48 },
    xAxis: { type: 'category', data: dates, boundaryGap: true, axisLabel: { hideOverlap: true } },
    yAxis: [
      { type: 'value', scale: true, name: '指数点位', nameTextStyle: { color: '#73839a' }, axisLabel: { color: '#65758b' }, splitLine: { lineStyle: { color: '#e8edf4' } } },
      { type: 'value', scale: true, name: '策略净值', nameTextStyle: { color: '#3f6ed4' }, axisLabel: { color: '#3f6ed4', formatter: value => Number(value).toFixed(3) }, splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }],
    series: [
      { name: candleName, type: 'candlestick', yAxisIndex: 0, data: lines.map(row => [row.open_price, row.close_price, row.low_price, row.high_price]), itemStyle: { color: '#e25d66', color0: '#22a879', borderColor: '#e25d66', borderColor0: '#22a879' } },
      { name: '策略净值', type: 'line', yAxisIndex: 1, showSymbol: false, connectNulls: true, data: lines.map(row => equityByDate.get(row.last_trade_date)?.net_value ?? null), lineStyle: { width: 2.4, color: '#3f6ed4' }, emphasis: { lineStyle: { width: 3 } } },
      { name: '买入', type: 'scatter', data: buys, symbol: 'triangle', symbolSize: 15, z: 10, itemStyle: { color: '#0f9d78', borderColor: '#fff', borderWidth: 2 }, label: { show: true, formatter: '买', position: 'top', color: '#08775b', fontWeight: 700 } },
      { name: '部分卖出', type: 'scatter', data: partials, symbol: 'triangle', symbolRotate: 180, symbolSize: 15, z: 10, itemStyle: { color: '#e59a2f', borderColor: '#fff', borderWidth: 2 }, label: { show: true, formatter: '减', position: 'bottom', color: '#a96508', fontWeight: 700 } },
      { name: '卖出', type: 'scatter', data: sells, symbol: 'triangle', symbolRotate: 180, symbolSize: 15, z: 10, itemStyle: { color: '#d9515d', borderColor: '#fff', borderWidth: 2 }, label: { show: true, formatter: '卖', position: 'bottom', color: '#a82f39', fontWeight: 700 } },
      { name: '跳过', type: 'scatter', data: skippedPoints, symbol: 'diamond', symbolSize: 16, z: 11, itemStyle: { color: '#77869a', borderColor: '#fff', borderWidth: 2 }, label: { show: true, formatter: '跳', position: 'top', color: '#536174', fontWeight: 700 } },
    ],
  })
}
async function compareSelected() { if (compareIds.value.length) comparison.value = await request('/backtest/compare?' + compareIds.value.map(id => `run_ids=${id}`).join('&')) }
onMounted(async () => { try { await load(); if (indices.value.length) form.value.index_id = indices.value[0].id } catch (e) { error.value = e.message } })
onBeforeUnmount(() => { clearTimeout(pollTimer); chart?.dispose(); detailChart?.dispose() })
</script>

<template>
  <div class="layout">
    <aside><h2>📈 指数反转监控</h2><p class="hint">量价形态 · 周线研究</p><button v-for="item in [['overview','监控总览'],['indices','指数管理'],['signals','历史信号'],['config','规则配置'],['jobs','任务记录'],['backtest','交易策略回测'],['runs','回测任务与结果']]" :key="item[0]" :class="{active: page === item[0] || (item[0] === 'indices' && page === 'detail') || (item[0] === 'runs' && page === 'result')}" @click="nav(item[0])">{{ item[1] }}</button></aside>
    <main>
      <header><h1>{{ ({ overview: '监控总览', indices: '指数管理', detail: selectedIndex?.index_name || 'K线详情', signals: '历史信号', config: '规则配置', jobs: '任务记录', backtest: '交易策略回测', runs: '回测任务', result: '回测结果分析' })[page] }}</h1><span class="hint">{{ busy ? '正在加载…' : '仅用于市场研究，不构成交易建议' }}</span></header>
      <div v-if="error" class="error">{{ error }}</div>

      <section v-if="page === 'overview'"><div class="stats"><article><strong>{{ overview.index_count ?? '-' }}</strong>指数数量</article><article><strong>{{ overview.enabled_count ?? '-' }}</strong>启用监控</article><article><strong>{{ overview.failed_count ?? '-' }}</strong>数据源异常</article><article><strong>{{ overview.recent?.length ?? 0 }}</strong>近期信号</article></div><h3>已启用理论指数</h3><div class="table-wrap"><table><thead><tr><th>指数</th><th>代码</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in indices.filter(x => x.enabled)" :key="item.id"><td>{{ item.index_name }}</td><td>{{ item.index_code }}</td><td><span class="chip">{{ item.data_status }}</span></td><td><button @click="form.index_id = item.id; page = 'backtest'">回测</button></td></tr></tbody></table></div></section>

      <section v-if="page === 'indices'"><div class="stats compact"><article><strong>{{ indices.length }}</strong>已配置指数</article><article><strong>{{ indices.filter(x => x.enabled).length }}</strong>正在同步</article><article><strong>{{ indices.filter(x => x.data_status === 'ACTIVE').length }}</strong>数据正常</article><article><strong>{{ indices.filter(x => x.data_status === 'SOURCE_FAILED').length }}</strong>数据源异常</article></div><div class="toolbar section-toolbar"><select v-model="market"><option value="">全部市场</option><option value="CN">A股</option><option value="HK">港股</option></select><button @click="runAdmin('/jobs/probe-sources')">探测全部数据源</button><button @click="runAdmin('/jobs/backfill', { days: 730 })">已启用指数补采</button><button @click="runAdmin('/jobs/scan', { days: 730 })">已启用指数扫描</button><button @click="runAdmin('/jobs/deliver-alerts')">发送待发通知</button></div><div class="table-wrap"><table><thead><tr><th>指数</th><th>代码</th><th>市场</th><th>数据源</th><th>同步状态</th><th>日线/周线/信号</th><th>最后数据日</th><th>监控</th><th>异常</th><th>操作</th></tr></thead><tbody><tr v-for="item in indices.filter(x => !market || x.market === market)" :key="item.id"><td>{{ item.index_name }}</td><td>{{ item.index_code }}</td><td>{{ item.market }}</td><td>{{ item.provider }}</td><td><span class="chip" :class="{failed: item.data_status === 'SOURCE_FAILED'}">{{ item.data_status }}</span></td><td>{{ item.daily_count }} / {{ item.weekly_count }} / {{ item.signal_count }}</td><td>{{ item.last_success_date || '-' }}</td><td>{{ item.enabled ? '已启用' : '未启用' }}</td><td class="error-cell">{{ item.last_error || '-' }}</td><td><button @click="showIndex(item)">K线</button><button @click="runAdmin(`/indices/${item.id}/probe`)">探测</button><button @click="runAdmin('/jobs/backfill', { index_ids: [item.id], days: 1825 })">补采5年</button><button @click="runAdmin('/jobs/scan', { index_ids: [item.id], days: 1825 })">扫描</button><button @click="setEnabled(item)">{{ item.enabled ? '停用' : '启用' }}</button></td></tr></tbody></table></div></section>

      <section v-if="page === 'detail'"><button @click="nav('indices')">← 返回指数管理</button><div ref="detailChartEl" class="chart"></div><h3>历史反转标记</h3><div class="table-wrap"><table><thead><tr><th>周次</th><th>吞没</th><th>阴线</th><th>量能</th><th>状态</th></tr></thead><tbody><tr v-for="signal in indexSignals" :key="signal.id"><td>{{ signal.week_start }}</td><td>{{ signal.engulfed_count }}</td><td>{{ signal.bearish_count }}</td><td>{{ signal.volume_ratio ?? signal.pace_ratio ?? '无数据' }}</td><td>{{ signal.status }}</td></tr></tbody></table></div></section>

      <section v-if="page === 'signals'"><div class="table-wrap"><table><thead><tr><th>指数</th><th>周次</th><th>吞没根数</th><th>阴线</th><th>突破</th><th>量能</th><th>状态</th></tr></thead><tbody><tr v-for="signal in signals" :key="signal.id"><td>{{ signal.index_name }}</td><td>{{ signal.week_start }}</td><td>{{ signal.engulfed_count }}</td><td>{{ signal.bearish_count }}</td><td>{{ signal.breakout_high ? '是' : '否' }}</td><td>{{ signal.volume_level }}</td><td>{{ signal.status }}</td></tr></tbody></table></div></section>

      <section v-if="page === 'config'"><div class="form"><label v-for="item in [['min_engulfed_count','最少吞没线数'],['min_bearish_count','至少阴线数'],['max_lookback_weeks','最大扫描周数'],['volume_lookback_weeks','量比参考周数'],['volume_warm_ratio','温和放量阈值'],['volume_strong_ratio','强放量阈值']]" :key="item[0]">{{ item[1] }}<input v-model.number="config[item[0]]" type="number" step="0.1" /></label><label><input v-model="config.enable_forming_alert" type="checkbox" />周中预警</label><label><input v-model="config.enable_confirmed_alert" type="checkbox" />收盘确认</label><button class="primary" @click="saveConfig">保存规则</button><p class="hint">当前配置版本：{{ config.config_version }}。修改后版本递增，请重新扫描验证。</p></div></section>

      <section v-if="page === 'jobs'"><div class="toolbar"><button @click="load">刷新任务</button></div><div class="table-wrap"><table><thead><tr><th>类型</th><th>开始时间</th><th>结束时间</th><th>状态</th><th>处理</th><th>成功</th><th>失败</th><th>异常</th></tr></thead><tbody><tr v-for="job in jobs" :key="job.run_key"><td>{{ job.job_type }}</td><td>{{ job.started_at }}</td><td>{{ job.finished_at || '-' }}</td><td>{{ job.status }}</td><td>{{ job.processed_count }}</td><td>{{ job.success_count }}</td><td>{{ job.failure_count }}</td><td>{{ job.error_summary || '-' }}</td></tr></tbody></table></div></section>

      <section v-if="page === 'backtest'" class="form wide"><h3>理论指数回测</h3><p class="hint">使用指数日线验证策略有效性，结果统一标记为 INDEX_THEORETICAL，不代表 ETF 可成交收益。</p><label>指数<select v-model="form.index_id"><option v-for="item in indices.filter(x => x.enabled)" :key="item.id" :value="item.id">{{ item.index_name }}（{{ item.index_code }}）</option></select></label><label>策略<select v-model="form.strategy"><option value="ALL">A / B / C 三套策略对比（推荐）</option><option v-for="(name, key) in strategies" :key="key" :value="key">{{ name }}</option></select></label><div class="two"><label>开始日期<input v-model="form.start_date" type="date" /></label><label>结束日期<input v-model="form.end_date" type="date" /></label></div><div class="two"><label>初始资金<input v-model.number="form.initial_capital" type="number" min="1" /></label><label>单笔风险<input v-model.number="form.risk_ratio" type="number" step="0.001" min="0.001" max="1" /></label></div><div class="two"><label>最大止损（超出跳过）<input v-model.number="form.max_stop_ratio" type="number" step="0.01" min="0.01" max="1" /></label><label>最大仓位<input v-model.number="form.max_position_ratio" type="number" step="0.01" min="0.01" max="1" /></label></div><div class="two"><label>手续费率<input v-model.number="form.fee_ratio" type="number" step="0.0001" min="0" /></label><label>滑点率<input v-model.number="form.slippage_ratio" type="number" step="0.0001" min="0" /></label></div><button class="primary" :disabled="busy" @click="submit">{{ busy ? '提交中…' : '提交回测任务' }}</button></section>

      <section v-if="page === 'runs'"><div class="toolbar"><button :disabled="!compareIds.length" @click="compareSelected">对比已选任务（{{ compareIds.length }}）</button><button @click="loadRuns">刷新状态</button></div><div class="table-wrap"><table><thead><tr><th>选择</th><th>ID</th><th>指数</th><th>策略</th><th>区间</th><th>状态</th><th>收益</th><th></th></tr></thead><tbody><tr v-for="run in runs" :key="run.id"><td><input v-model="compareIds" type="checkbox" :value="run.id" /></td><td>{{ run.id }}</td><td>{{ indices.find(x => x.id === run.index_id)?.index_name || run.index_id }}</td><td>{{ run.strategy }}</td><td>{{ run.start_date }} ~ {{ run.end_date }}</td><td><span class="chip">{{ run.status }}</span></td><td>{{ run.summary ? (run.summary.total_return * 100).toFixed(2) + '%' : '-' }}</td><td><button @click="showRun(run.id)">查看</button></td></tr></tbody></table></div><div v-if="comparison.length"><h3>策略对比</h3><div class="table-wrap"><table><thead><tr><th>任务</th><th>策略</th><th>年化</th><th>最大回撤</th><th>Calmar</th><th>胜率</th><th>交易数</th></tr></thead><tbody><tr v-for="run in comparison" :key="run.id"><td>#{{ run.id }}</td><td>{{ run.strategy }}</td><td>{{ run.summary ? (run.summary.annualized_return * 100).toFixed(2) + '%' : '-' }}</td><td>{{ run.summary ? (run.summary.max_drawdown * 100).toFixed(2) + '%' : '-' }}</td><td>{{ run.summary?.calmar?.toFixed(2) ?? '-' }}</td><td>{{ run.summary ? (run.summary.win_rate * 100).toFixed(1) + '%' : '-' }}</td><td>{{ run.summary?.trade_count ?? '-' }}</td></tr></tbody></table></div></div></section>

      <section v-if="page === 'result'"><button @click="page = 'runs'">← 返回任务</button><p v-if="selectedRun && ['QUEUED','RUNNING'].includes(selectedRun.status)" class="notice">任务状态：{{ selectedRun.status }}，正在自动刷新…</p><template v-if="selectedRun?.status === 'SUCCESS'"><div class="meta">回测对象：{{ selectedRunIndex?.index_name || `指数 #${selectedRun.index_id}` }}（{{ selectedRunIndex?.index_code || '-' }}） · 模式：INDEX_THEORETICAL · 策略 {{ selectedRun.strategy }} · 数据版本 {{ selectedRun.data_version }} · 信号算法 {{ selectedRun.signal_algorithm_version }}</div><div class="stats"><article><strong>{{ ((summary.total_return || 0) * 100).toFixed(2) }}%</strong>策略收益</article><article><strong>{{ ((summary.annualized_return || 0) * 100).toFixed(2) }}%</strong>年化收益</article><article><strong>{{ ((summary.max_drawdown || 0) * 100).toFixed(2) }}%</strong>最大回撤</article><article><strong>{{ summary.calmar?.toFixed(2) ?? '-' }}</strong>Calmar</article></div><h3>策略净值与指数 K 线</h3><div class="toolbar"><button :class="{ primary: chartPeriod === '1w' }" @click="setChartPeriod('1w')">周 K（信号视图）</button><button :class="{ primary: chartPeriod === '1d' }" @click="setChartPeriod('1d')">日 K（执行视图）</button><span class="hint">周 K 核对信号形态，日 K 检查实际成交与止损</span></div><div ref="chartEl" class="equity-chart"></div><h3>交易明细</h3><div class="table-wrap"><table><thead><tr><th>信号</th><th>买入日期</th><th>买入价</th><th>数量</th><th>初始止损</th><th>卖出日期</th><th>卖出价</th><th>费用</th><th>净盈亏</th><th>退出原因</th></tr></thead><tbody><tr v-for="trade in trades" :key="trade.id"><td>{{ trade.signal_id }}</td><td>{{ trade.entry_date }}</td><td>{{ trade.entry_price }}</td><td>{{ trade.quantity }}</td><td>{{ trade.initial_stop }}</td><td>{{ trade.exit_date || '-' }}</td><td>{{ trade.exit_price || '-' }}</td><td>{{ trade.total_fee.toFixed(2) }}</td><td :class="trade.net_pnl >= 0 ? 'positive' : 'negative'">{{ trade.net_pnl?.toFixed(2) ?? '-' }}</td><td>{{ trade.exit_reason || '持仓中' }}</td></tr></tbody></table></div></template></section>
    </main>
  </div>
</template>
