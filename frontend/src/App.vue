<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart, ScatterChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, CandlestickChart, LineChart, ScatterChart, DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, MarkPointComponent, TooltipComponent, CanvasRenderer])

const base = '/index-reversal/api/v1'
const page = ref('overview'), token = ref(sessionStorage.getItem('im_admin') || '')
const error = ref(''), busy = ref(false), overview = ref({}), indices = ref([]), runs = ref([])
const selectedRun = ref(null), trades = ref([]), equity = ref([]), orders = ref([]), skipped = ref([])
const dailyCandles = ref([]), weeklyCandles = ref([]), chartPeriod = ref('1w')
const compareIds = ref([]), comparison = ref([]), chartEl = ref(null)
const signals = ref([]), config = ref({}), jobs = ref([]), market = ref('')
const selectedIndex = ref(null), candles = ref([]), indexSignals = ref([]), detailChartEl = ref(null)
const pcInstruments = ref([]), pcRuns = ref([]), selectedPcRun = ref(null), pcSeries = ref([]), pcMonthly = ref([]), pcTrades = ref([]), pcEquity = ref([])
const pcChartEl = ref(null), pcEquityChartEl = ref(null)
let chart = null, detailChart = null, pcChart = null, pcEquityChart = null, pollTimer = null
const form = ref({ index_id: '', strategy: 'ALL', signal_mode: 'ENGULFING', signal_period: '1w', entry_timing: 'NEXT_OPEN', stop_buffer_percent: 1, start_date: '2020-11-13', end_date: '2026-11-12', initial_capital: 100000, risk_ratio: 0.01, max_position_ratio: 0.2, max_stop_ratio: 0.08, fee_ratio: 0.0003, slippage_ratio: 0.0005, take_profit_r: 2 })
const pcForm = ref({ index_id: '', scenario_name: '', reference_method: 'SMA', ma_period: 36, trend_fit_lag_years: 1, start_date: '2005-01-01', end_date: '2026-11-25', initial_capital: 1000000, buy_tiers: [{ deviation_percent: -10, target_weight_percent: 50 }, { deviation_percent: -20, target_weight_percent: 80 }, { deviation_percent: -30, target_weight_percent: 100 }], sell_tiers: [{ deviation_percent: 20, target_weight_percent: 50 }, { deviation_percent: 40, target_weight_percent: 0 }], fee_ratio: 0.0003, slippage_ratio: 0.0005 })
const macroForm = ref({ index_id: '', start_date: '2016-01-01', end_date: '2026-11-27', initial_capital: 1000000, allow_unverified_history: true })
const macroIndicators = ref([]), macroRuns = ref([]), macroRun = ref(null), macroTrades = ref([]), macroEquity = ref([])
const macroChartEl = ref(null)
let macroChart = null
async function loadMacro() {
  const [indicators, history] = await Promise.all([request('/macro/indicators'), request('/macro/backtests')])
  macroIndicators.value = indicators; macroRuns.value = history
  if (!indices.value.length) await load()
  if (!macroForm.value.index_id && indices.value.length) macroForm.value.index_id = indices.value.find(x => x.index_code === '000300')?.id || indices.value[0].id
}
async function macroSync() {
  if (!auth()) return
  busy.value = true; error.value = ''
  try {
    await request('/macro/sync', { method: 'POST', body: JSON.stringify({ start_date: macroForm.value.start_date, end_date: macroForm.value.end_date, market: 'CN-A', calendar_index_id: Number(macroForm.value.index_id) }) })
    await request('/macro/indicators/recalculate', { method: 'POST' })
    await loadMacro()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function macroRecalculate() {
  if (!auth()) return
  busy.value = true; error.value = ''
  try {
    await request('/macro/indicators/recalculate', { method: 'POST' })
    await loadMacro()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function macroBacktest() {
  if (!auth()) return
  busy.value = true; error.value = ''
  try {
    const result = await request('/macro/backtests', { method: 'POST', body: JSON.stringify({ ...macroForm.value, index_id: Number(macroForm.value.index_id) }) })
    await showMacroRun(result.id)
    await loadMacro()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function showMacroRun(id) {
  busy.value = true; error.value = ''
  try {
    const run = macroRuns.value.find(x => x.id === id) || (await request('/macro/backtests')).find(x => x.id === id)
    macroRun.value = run
    ;[macroEquity.value, macroTrades.value] = await Promise.all([
      request(`/macro/backtests/${id}/equity`), request(`/macro/backtests/${id}/trades`)
    ])
    page.value = 'macro_result'
    await nextTick()
    macroChart?.dispose()
    if (macroChartEl.value && macroEquity.value.length) {
      macroChart = echarts.init(macroChartEl.value)
      macroChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['CAP/GDP策略', '指数买入持有', '目标仓位'] },
        grid: { left: 70, right: 70, top: 45, bottom: 55 },
        xAxis: { type: 'category', data: macroEquity.value.map(r => r.date) },
        yAxis: [{ type: 'value', scale: true }, { type: 'value', min: 0, max: 1 }],
        dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 5 }],
        series: [
          { name: 'CAP/GDP策略', type: 'line', showSymbol: false, data: macroEquity.value.map(r => r.nav) },
          { name: '指数买入持有', type: 'line', showSymbol: false, data: macroEquity.value.map(r => r.benchmark_nav) },
          { name: '目标仓位', type: 'line', yAxisIndex: 1, showSymbol: false, data: macroEquity.value.map(r => r.target_weight) }
        ]
      })
    }
  } catch (e) { error.value = e.message } finally { busy.value = false }
}

const strategies = { A: 'A：2R 全部止盈', B: 'B：2R 减半 + 移动止损', C: 'C：全程移动止损', D: 'D：失败快退 + 2R减25% + 周收盘趋势退出' }
const summary = computed(() => selectedRun.value?.summary || {})
const selectedRunIndex = computed(() => indices.value.find(item => item.id === selectedRun.value?.index_id))
const signalName = run => run?.signal_mode === 'BREAKOUT_PULLBACK' ? '日线突破回踩' : run?.signal_period === '1d' ? '日线吞没' : '周线吞没'
const priceCenterReferenceName = run => run?.parameters?.reference_method === 'FIXED_LOG_TREND' ? '固定对数趋势线' : `MA${run?.parameters?.ma_period || 36}`
const priceCenterFitDescription = run => {
  const fit = run?.summary?.reference_fit
  if (!fit) return ''
  return `拟合 ${fit.fit_start_date} 至 ${fit.fit_end_date} · 留空${fit.fit_lag_years}年 · 年化趋势 ${(fit.annualized_growth_rate * 100).toFixed(2)}%`
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(token.value ? { 'X-Admin-Token': token.value } : {}) }
  const response = await fetch(base + path, { ...options, headers: { ...headers, ...(options.headers || {}) } })
  const raw = await response.text()
  let body
  try { body = raw ? JSON.parse(raw) : null } catch { body = { detail: raw || response.statusText } }
  if (!response.ok) {
    const detail = body?.detail
    const message = Array.isArray(detail)
      ? detail.map(item => `${item.loc?.slice(-1)[0] || '参数'}：${item.msg || JSON.stringify(item)}`).join('；')
      : typeof detail === 'object' && detail !== null ? JSON.stringify(detail) : detail
    throw new Error(message || response.statusText)
  }
  return body
}
function auth() { if (!token.value) token.value = prompt('输入管理 Token') || ''; if (token.value) sessionStorage.setItem('im_admin', token.value); return Boolean(token.value) }
async function load() {
  const [o, i, s, c, j] = await Promise.all([request('/overview'), request('/indices?size=200'), request('/signals?size=100'), request('/config'), request('/jobs')])
  overview.value = o; indices.value = i.items; signals.value = s.items; config.value = c; jobs.value = j
}
async function loadRuns() { runs.value = await request('/backtest/runs') }
async function loadPriceCenter() {
  ;[pcInstruments.value, pcRuns.value] = await Promise.all([request('/price-center/instruments'), request('/price-center/runs')])
  if (!pcForm.value.index_id && pcInstruments.value.length) pcForm.value.index_id = pcInstruments.value[0].index_id
}
async function nav(name) {
  page.value = name; error.value = ''
  try { if (['overview', 'indices', 'signals', 'config', 'jobs', 'backtest'].includes(name)) await load(); if (name === 'runs') { await load(); await loadRuns() }; if (name === 'price_center') await loadPriceCenter(); if (name === 'macro') await loadMacro() } catch (e) { error.value = e.message }
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
    const keys = form.value.strategy === 'ALL' ? ['A', 'B', 'C', 'D'] : [form.value.strategy], created = []
    const { stop_buffer_percent, ...values } = form.value
    const stop_buffer_ratio = Number(stop_buffer_percent || 0) / 100
    const signal_period = form.value.signal_mode === 'BREAKOUT_PULLBACK' ? '1d' : form.value.signal_period
    for (const strategy of keys) created.push(await request('/backtest/runs', { method: 'POST', body: JSON.stringify({ ...values, signal_period, stop_buffer_ratio, strategy, index_id: Number(form.value.index_id) }) }))
    if (created.length === 1) await showRun(created[0].id)
    else { compareIds.value = created.map(x => x.id); await loadRuns(); page.value = 'runs' }
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function syncPriceCenter(indexId) {
  if (!auth()) return
  busy.value = true; error.value = ''
  try { await request(`/price-center/instruments/${indexId}/sync`, { method: 'POST' }); await loadPriceCenter() } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function submitPriceCenter() {
  if (!auth()) return
  busy.value = true; error.value = ''
  try {
    const { buy_tiers, sell_tiers, ...values } = pcForm.value
    const payload = { ...values, index_id: Number(values.index_id), buy_tiers: buy_tiers.map(item => ({ deviation: item.deviation_percent / 100, target_weight: item.target_weight_percent / 100 })), sell_tiers: sell_tiers.map(item => ({ deviation: item.deviation_percent / 100, target_weight: item.target_weight_percent / 100 })) }
    const created = await request('/price-center/runs', { method: 'POST', body: JSON.stringify(payload) })
    await showPriceCenterRun(created.id)
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
function addPriceCenterTier() {
  const last = pcForm.value.buy_tiers.at(-1) || { deviation_percent: 0, target_weight_percent: 0 }
  pcForm.value.buy_tiers.push({ deviation_percent: last.deviation_percent - 10, target_weight_percent: Math.min(last.target_weight_percent + 20, 100) })
}
function removePriceCenterTier(index) {
  if (pcForm.value.buy_tiers.length > 1) pcForm.value.buy_tiers.splice(index, 1)
}
function addPriceCenterSellTier() {
  const last = pcForm.value.sell_tiers.at(-1) || { deviation_percent: 0, target_weight_percent: 100 }
  pcForm.value.sell_tiers.push({ deviation_percent: last.deviation_percent + 10, target_weight_percent: Math.max(last.target_weight_percent - 20, 0) })
}
function removePriceCenterSellTier(index) {
  if (pcForm.value.sell_tiers.length > 1) pcForm.value.sell_tiers.splice(index, 1)
}
async function showPriceCenterRun(id) {
  clearTimeout(pollTimer); busy.value = true; error.value = ''
  try {
    selectedPcRun.value = await request(`/price-center/runs/${id}`); page.value = 'price_center_result'
    if (['QUEUED', 'RUNNING'].includes(selectedPcRun.value.status)) { pollTimer = setTimeout(() => showPriceCenterRun(id), 1200); return }
    if (selectedPcRun.value.status === 'FAILED') { error.value = selectedPcRun.value.error_message || '价格中枢回测失败'; return }
    ;[pcSeries.value, pcMonthly.value, pcTrades.value, pcEquity.value] = await Promise.all([request(`/price-center/runs/${id}/series`), request(`/price-center/runs/${id}/monthly`), request(`/price-center/runs/${id}/trades`), request(`/price-center/runs/${id}/equity`)])
    await nextTick(); renderPriceCenterCharts()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
function renderPriceCenterCharts() {
  if (pcChartEl.value) {
    pcChart?.dispose(); pcChart = echarts.init(pcChartEl.value)
    const dates = pcSeries.value.map(x => x.month_end)
    const indexSeriesName = selectedPcRun.value.summary.signal_evaluation_frequency === 'DAILY_CLOSE' ? '指数日收盘' : '指数月末收盘'
    const referenceName = priceCenterReferenceName(selectedPcRun.value)
    const p = selectedPcRun.value.parameters
    const legacyThresholds = [p.full_buy, p.heavy_buy, p.first_buy]
    const sellThresholds = p.sell_tiers?.map(item => item.deviation) || [p.reduce_at, p.exit_at]
    const thresholdLines = [...new Set([...(p.buy_tiers?.map(item => item.deviation) || legacyThresholds), ...sellThresholds].filter(value => value != null))]
    const tradeByMonth = new Map(pcTrades.value.map(x => [x.signal_month, x]))
    const buys = pcMonthly.value.filter(x => tradeByMonth.get(x.month_end)?.side === 'BUY').map(x => [x.month_end, x.index_close])
    const sells = pcMonthly.value.filter(x => tradeByMonth.get(x.month_end)?.side === 'SELL').map(x => [x.month_end, x.index_close])
    pcChart.setOption({
      tooltip: { trigger: 'axis' }, legend: { data: [indexSeriesName, referenceName, '偏离度', '买入', '卖出'] },
      grid: [{ left: 70, right: 35, top: 48, height: '52%' }, { left: 70, right: 35, top: '72%', height: '18%' }],
      xAxis: [{ type: 'category', data: dates, axisLabel: { hideOverlap: true } }, { type: 'category', gridIndex: 1, data: dates, axisLabel: { hideOverlap: true } }],
      yAxis: [{ scale: true, name: '指数点位' }, { gridIndex: 1, name: '偏离度', axisLabel: { formatter: v => `${(v * 100).toFixed(0)}%` } }],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], bottom: 0 }],
      series: [
        { name: indexSeriesName, type: 'line', data: pcSeries.value.map(x => x.index_close), showSymbol: false },
        { name: referenceName, type: 'line', data: pcSeries.value.map(x => x.center_value ?? x.ma_value), showSymbol: false },
        { name: '买入', type: 'scatter', data: buys, symbol: 'triangle', symbolSize: 16, itemStyle: { color: '#0f9d78' } },
        { name: '卖出', type: 'scatter', data: sells, symbol: 'triangle', symbolRotate: 180, symbolSize: 16, itemStyle: { color: '#d9515d' } },
        { name: '偏离度', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: pcSeries.value.map(x => x.deviation), showSymbol: false, markLine: { silent: true, data: thresholdLines.map(yAxis => ({ yAxis })) } },
      ],
    })
  }
  if (pcEquityChartEl.value) {
    pcEquityChart?.dispose(); pcEquityChart = echarts.init(pcEquityChartEl.value)
    const dates = pcEquity.value.map(x => x.trade_date)
    pcEquityChart.setOption({ tooltip: { trigger: 'axis' }, legend: { data: ['中枢策略', 'ETF长期持有', '权益仓位'] }, grid: { left: 70, right: 70, top: 45, bottom: 50 }, xAxis: { type: 'category', data: dates, axisLabel: { hideOverlap: true } }, yAxis: [{ scale: true, name: '净值' }, { min: 0, max: 1, name: '仓位', axisLabel: { formatter: v => `${(v * 100).toFixed(0)}%` } }], dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 0 }], series: [{ name: '中枢策略', type: 'line', data: pcEquity.value.map(x => x.net_value), showSymbol: false }, { name: 'ETF长期持有', type: 'line', data: pcEquity.value.map(x => x.benchmark_net_value), showSymbol: false }, { name: '权益仓位', type: 'line', yAxisIndex: 1, data: pcEquity.value.map(x => x.equity_ratio), showSymbol: false, lineStyle: { type: 'dashed' } }] })
  }
}
async function showRun(id) {
  clearTimeout(pollTimer); busy.value = true; error.value = ''
  try {
    selectedRun.value = await request(`/backtest/runs/${id}`); page.value = 'result'
    if (['QUEUED', 'RUNNING'].includes(selectedRun.value.status)) { pollTimer = setTimeout(() => showRun(id), 1000); return }
    if (selectedRun.value.status === 'FAILED') { error.value = selectedRun.value.error_message || '回测失败'; return }
    chartPeriod.value = selectedRun.value.signal_period || '1w'
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
  const reasonNames = { SIGNAL_CLOSE: '信号K收盘价模拟买入', SIGNAL_NEXT_OPEN: '信号后下一交易日开盘买入', SIGNAL_INVALIDATED_CLOSE: '收盘跌破信号K低点', WEEKLY_TREND_EXIT: '周收盘跌破前三周低点', STOP_GAP: '止损跳空', STOP_LOSS: '初始止损', TRAILING_STOP_GAP: '移动止损跳空', TRAILING_STOP: '移动止损', TAKE_PROFIT: '固定止盈', TAKE_PROFIT_GAP: '止盈跳空', TAKE_2R_HALF: '2R减仓', TAKE_2R_HALF_GAP: '2R跳空减仓', TAKE_2R_QUARTER: '2R减仓25%', TAKE_2R_QUARTER_GAP: '2R跳空减仓25%', END_OF_RANGE: '回测区间结束' }
  const skipReasonNames = { STOP_DISTANCE_EXCEEDED: '止损距离超过上限', POSITION_ALREADY_OPEN: '已有持仓', INVALID_STOP: '止损价无效', INSUFFICIENT_CASH_OR_LOT: '资金或最小手数不足' }
  const tooltip = params => {
    const list = Array.isArray(params) ? params : [params]
    const date = list[0]?.axisValue || list[0]?.value?.[0] || ''
    const lines = [`<strong>${date}</strong>`]
    for (const item of list) {
      const order = item.data?.order
      const skippedItem = item.data?.skipped
      if (order) lines.push(`${item.marker}${item.seriesName}：${order.signal_period === '1d' ? '日线' : '周线'}信号 #${order.signal_id}（${order.signal_date || '-'}）<br/>成交日 ${order.trade_date}，成交价 ${order.fill_price.toFixed(4)}，数量 ${order.quantity}<br/>费用 ${order.fee.toFixed(2)}，原因 ${reasonNames[order.reason] || order.reason}`)
      else if (skippedItem) {
        const stopDetail = skippedItem.stop_ratio == null ? '' : `<br/>止损距离 ${(skippedItem.stop_ratio * 100).toFixed(2)}%，上限 ${(skippedItem.max_stop_ratio * 100).toFixed(2)}%`
        lines.push(`${item.marker}跳过：${skippedItem.signal_period === '1d' ? '日线' : '周线'}信号 #${skippedItem.signal_id}（${skippedItem.signal_date || '-'}）<br/>计划入场日 ${skippedItem.trade_date}，原因 ${skipReasonNames[skippedItem.reason] || skippedItem.reason}${stopDetail}`)
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
onBeforeUnmount(() => { clearTimeout(pollTimer); chart?.dispose(); detailChart?.dispose(); pcChart?.dispose(); pcEquityChart?.dispose() })
</script>

<template>
  <div class="layout">
    <aside><h2>📈 指数反转监控</h2><p class="hint">量价形态 · 日/周线研究</p><button v-for="item in [['overview','监控总览'],['indices','指数管理'],['signals','历史信号'],['config','规则配置'],['jobs','任务记录'],['backtest','交易策略回测'],['runs','回测任务与结果'],['price_center','长期价格中枢'],['macro','CAP/GDP宏观估值']]" :key="item[0]" :class="{active: page === item[0] || (item[0] === 'indices' && page === 'detail') || (item[0] === 'runs' && page === 'result') || (item[0] === 'price_center' && page === 'price_center_result')}" @click="nav(item[0])">{{ item[1] }}</button></aside>
    <main>
      <header><h1>{{ ({ overview: '监控总览', indices: '指数管理', detail: selectedIndex?.index_name || 'K线详情', signals: '历史信号', config: '规则配置', jobs: '任务记录', backtest: '交易策略回测', runs: '回测任务', result: '回测结果分析', price_center: '长期价格中枢策略', price_center_result: '价格中枢回测结果', macro: '总市值/GDP策略', macro_result: '宏观仓位回测结果' })[page] }}</h1><span class="hint">{{ busy ? '正在加载…' : '仅用于市场研究，不构成交易建议' }}</span></header>
      <div v-if="error" class="error">{{ error }}</div>

      <section v-if="page === 'macro'">
        <h3>宏观估值指标 · 数据同步 / 指标计算 / 回测分离</h3>
        <p class="hint">独立获取沪深交易所总市值及GDP并写入本项目数据库。历史GDP未验证实际公布时点，回测属于探索性研究，执行价格是指数理论价格，不代表ETF实盘收益。</p>
        <div class="form wide">
          <div class="two"><label>交易指数<select v-model.number="macroForm.index_id"><option v-for="item in indices" :key="item.id" :value="item.id">{{ item.index_name }}（{{ item.index_code }}）</option></select></label><label>初始资金<input v-model.number="macroForm.initial_capital" type="number" /></label></div>
          <div class="two"><label>开始<input v-model="macroForm.start_date" type="date" /></label><label>结束<input v-model="macroForm.end_date" type="date" /></label></div>
          <label><input v-model="macroForm.allow_unverified_history" type="checkbox" />允许未经历史时点审计的数据进行探索性回测</label>
          <div class="toolbar"><button @click="macroSync" :disabled="busy">① 同步原始数据</button><button @click="macroRecalculate" :disabled="busy">② 重新计算指标</button><button class="primary" @click="macroBacktest" :disabled="busy">③ 创建策略回测</button></div>
        </div>
        <h3>最近指标（{{ macroIndicators.length }}条）</h3>
        <div class="table-wrap"><table><thead><tr><th>日期</th><th>总市值/GDP</th><th>建议权益仓位</th><th>历史口径</th></tr></thead><tbody>
          <tr v-for="row in macroIndicators.slice(-30).reverse()" :key="row.date"><td>{{ row.date }}</td><td>{{ (row.x * 100).toFixed(2) }}%</td><td>{{ (row.target_weight * 100).toFixed(1) }}%</td><td>{{ row.provenance }}</td></tr>
        </tbody></table></div>
        <h3>历史回测</h3>
        <div class="table-wrap"><table><thead><tr><th>ID</th><th>时间</th><th>年化</th><th>最大回撤</th><th>数据来源</th><th>操作</th></tr></thead><tbody>
          <tr v-for="r in macroRuns" :key="r.id"><td>{{ r.id }}</td><td>{{ r.start_date }}～{{ r.end_date }}</td><td>{{ (r.summary.cagr*100).toFixed(2) }}%</td><td>{{ (r.summary.max_drawdown*100).toFixed(2) }}%</td><td>{{ r.provenance }}</td><td><button @click="showMacroRun(r.id)">查看</button></td></tr>
        </tbody></table></div>
      </section>
      <section v-if="page === 'macro_result'">
        <button @click="nav('macro')">← 返回宏观策略</button>
        <p class="hint">指数理论回测；历史数据是否具备时点可知性尚待核验。</p>
        <div class="stats compact"><article><strong>{{ ((macroRun?.summary?.cagr || 0)*100).toFixed(2) }}%</strong>年化收益</article><article><strong>{{ ((macroRun?.summary?.max_drawdown || 0)*100).toFixed(2) }}%</strong>最大回撤</article><article><strong>{{ ((macroRun?.summary?.benchmark_cagr || 0)*100).toFixed(2) }}%</strong>买入持有年化</article><article><strong>{{ macroRun?.summary?.trade_count || 0 }}</strong>交易次数</article></div>
        <div ref="macroChartEl" class="chart"></div>
        <h3>逐笔成交</h3><div class="table-wrap"><table><thead><tr><th>信号日</th><th>成交日</th><th>X</th><th>方向</th><th>目标仓位</th><th>价格</th><th>数量</th><th>费用</th></tr></thead><tbody>
          <tr v-for="(t,i) in macroTrades" :key="i"><td>{{ t.signal_date }}</td><td>{{ t.trade_date }}</td><td>{{ t.x.toFixed(4) }}</td><td>{{ t.side }}</td><td>{{ (t.target_weight*100).toFixed(1) }}%</td><td>{{ t.price.toFixed(2) }}</td><td>{{ t.quantity.toFixed(2) }}</td><td>{{ t.fee.toFixed(2) }}</td></tr>
        </tbody></table></div>
      </section>
      <section v-if="page === 'overview'"><div class="stats"><article><strong>{{ overview.index_count ?? '-' }}</strong>指数数量</article><article><strong>{{ overview.enabled_count ?? '-' }}</strong>启用监控</article><article><strong>{{ overview.failed_count ?? '-' }}</strong>数据源异常</article><article><strong>{{ overview.recent?.length ?? 0 }}</strong>近期信号</article></div><h3>已启用理论指数</h3><div class="table-wrap"><table><thead><tr><th>指数</th><th>代码</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in indices.filter(x => x.enabled)" :key="item.id"><td>{{ item.index_name }}</td><td>{{ item.index_code }}</td><td><span class="chip">{{ item.data_status }}</span></td><td><button @click="form.index_id = item.id; page = 'backtest'">回测</button></td></tr></tbody></table></div></section>

      <section v-if="page === 'indices'"><div class="stats compact"><article><strong>{{ indices.length }}</strong>已配置指数</article><article><strong>{{ indices.filter(x => x.enabled).length }}</strong>正在同步</article><article><strong>{{ indices.filter(x => x.data_status === 'ACTIVE').length }}</strong>数据正常</article><article><strong>{{ indices.filter(x => x.data_status === 'SOURCE_FAILED').length }}</strong>数据源异常</article></div><div class="toolbar section-toolbar"><select v-model="market"><option value="">全部市场</option><option value="CN">A股</option><option value="HK">港股</option></select><button @click="runAdmin('/jobs/probe-sources')">探测全部数据源</button><button @click="runAdmin('/jobs/backfill', { days: 730 })">已启用指数补采</button><button @click="runAdmin('/jobs/scan', { days: 730 })">已启用指数扫描</button><button @click="runAdmin('/jobs/deliver-alerts')">发送待发通知</button></div><div class="table-wrap"><table><thead><tr><th>指数</th><th>代码</th><th>市场</th><th>数据源</th><th>同步状态</th><th>日线/周线/信号</th><th>最后数据日</th><th>监控</th><th>异常</th><th>操作</th></tr></thead><tbody><tr v-for="item in indices.filter(x => !market || x.market === market)" :key="item.id"><td>{{ item.index_name }}</td><td>{{ item.index_code }}</td><td>{{ item.market }}</td><td>{{ item.provider }}</td><td><span class="chip" :class="{failed: item.data_status === 'SOURCE_FAILED'}">{{ item.data_status }}</span></td><td>{{ item.daily_count }} / {{ item.weekly_count }} / {{ item.signal_count }}</td><td>{{ item.last_success_date || '-' }}</td><td>{{ item.enabled ? '已启用' : '未启用' }}</td><td class="error-cell">{{ item.last_error || '-' }}</td><td><button @click="showIndex(item)">K线</button><button @click="runAdmin(`/indices/${item.id}/probe`)">探测</button><button @click="runAdmin('/jobs/backfill', { index_ids: [item.id], days: 1825 })">补采5年</button><button @click="runAdmin('/jobs/scan', { index_ids: [item.id], days: 1825 })">扫描</button><button @click="setEnabled(item)">{{ item.enabled ? '停用' : '启用' }}</button></td></tr></tbody></table></div></section>

      <section v-if="page === 'detail'"><button @click="nav('indices')">← 返回指数管理</button><div ref="detailChartEl" class="chart"></div><h3>历史反转标记</h3><div class="table-wrap"><table><thead><tr><th>周次</th><th>吞没</th><th>阴线</th><th>量能</th><th>状态</th></tr></thead><tbody><tr v-for="signal in indexSignals" :key="signal.id"><td>{{ signal.week_start }}</td><td>{{ signal.engulfed_count }}</td><td>{{ signal.bearish_count }}</td><td>{{ signal.volume_ratio ?? signal.pace_ratio ?? '无数据' }}</td><td>{{ signal.status }}</td></tr></tbody></table></div></section>

      <section v-if="page === 'signals'"><div class="table-wrap"><table><thead><tr><th>指数</th><th>周次</th><th>吞没根数</th><th>阴线</th><th>突破</th><th>量能</th><th>状态</th></tr></thead><tbody><tr v-for="signal in signals" :key="signal.id"><td>{{ signal.index_name }}</td><td>{{ signal.week_start }}</td><td>{{ signal.engulfed_count }}</td><td>{{ signal.bearish_count }}</td><td>{{ signal.breakout_high ? '是' : '否' }}</td><td>{{ signal.volume_level }}</td><td>{{ signal.status }}</td></tr></tbody></table></div></section>

      <section v-if="page === 'config'"><div class="form"><label v-for="item in [['min_engulfed_count','最少吞没线数'],['min_bearish_count','至少阴线数'],['max_lookback_weeks','最大扫描周数'],['volume_lookback_weeks','量比参考周数'],['volume_warm_ratio','温和放量阈值'],['volume_strong_ratio','强放量阈值']]" :key="item[0]">{{ item[1] }}<input v-model.number="config[item[0]]" type="number" step="0.1" /></label><label><input v-model="config.enable_forming_alert" type="checkbox" />周中预警</label><label><input v-model="config.enable_confirmed_alert" type="checkbox" />收盘确认</label><button class="primary" @click="saveConfig">保存规则</button><p class="hint">当前配置版本：{{ config.config_version }}。修改后版本递增，请重新扫描验证。</p></div></section>

      <section v-if="page === 'jobs'"><div class="toolbar"><button @click="load">刷新任务</button></div><div class="table-wrap"><table><thead><tr><th>类型</th><th>开始时间</th><th>结束时间</th><th>状态</th><th>处理</th><th>成功</th><th>失败</th><th>异常</th></tr></thead><tbody><tr v-for="job in jobs" :key="job.run_key"><td>{{ job.job_type }}</td><td>{{ job.started_at }}</td><td>{{ job.finished_at || '-' }}</td><td>{{ job.status }}</td><td>{{ job.processed_count }}</td><td>{{ job.success_count }}</td><td>{{ job.failure_count }}</td><td>{{ job.error_summary || '-' }}</td></tr></tbody></table></div></section>

      <section v-if="page === 'price_center'">
        <div class="form wide">
          <h3>长期价格中枢低位布局</h3><p class="hint">中枢只使用截至上一个完整月的指数月线；每日收盘判断。可配置1到10档，偏离度须逐档降低，目标仓位须逐档提高。</p>
          <div class="two"><label>指数 / ETF<select v-model="pcForm.index_id"><option v-for="item in pcInstruments" :key="item.index_id" :value="item.index_id">{{ item.index_name }} → {{ item.etf_name }}（{{ item.etf_code }}）</option></select></label><label>参考线<select v-model="pcForm.reference_method"><option value="SMA">月线滚动均线</option><option value="FIXED_LOG_TREND">固定对数趋势线</option></select></label></div>
          <div class="two"><label v-if="pcForm.reference_method === 'SMA'">中枢周期<select v-model.number="pcForm.ma_period"><option v-for="period in [12,24,36,60,120]" :key="period" :value="period">MA{{ period }}</option></select></label><label v-else>拟合前留空<select v-model.number="pcForm.trend_fit_lag_years"><option :value="1">测试开始前 1 年</option><option :value="2">测试开始前 2 年</option></select></label></div>
          <p v-if="pcForm.reference_method === 'FIXED_LOG_TREND'" class="hint">从指数最早月线拟合至测试期前留空的截止月；至少需要 60 个拟合月。拟合斜率和截距在测试期冻结，非正斜率会明确报错，不会自动切回均线。</p>
          <label>方案名称<input v-model="pcForm.scenario_name" type="text" placeholder="例如：五档均衡" /></label>
          <div class="two"><label>开始日期<input v-model="pcForm.start_date" type="date" /></label><label>结束日期<input v-model="pcForm.end_date" type="date" /></label></div>
          <label>初始资金<input v-model.number="pcForm.initial_capital" type="number" min="1" /></label>
          <h3>买入档位</h3>
          <template v-for="(tier, index) in pcForm.buy_tiers" :key="index">
            <div class="two"><label>第{{ index + 1 }}档偏离度（%）<input v-model.number="tier.deviation_percent" type="number" step="1" min="-100" max="0" /></label><label>目标仓位（%）<input v-model.number="tier.target_weight_percent" type="number" step="5" min="1" max="100" /></label></div>
            <button v-if="pcForm.buy_tiers.length > 1" type="button" @click="removePriceCenterTier(index)">删除第{{ index + 1 }}档</button>
          </template>
          <button v-if="pcForm.buy_tiers.length < 10" type="button" @click="addPriceCenterTier">＋ 添加一档</button>
          <h3>卖出档位</h3><p class="hint">偏离度须逐档提高，目标剩余仓位须逐档降低，最后一档必须为0%。</p>
          <template v-for="(tier, index) in pcForm.sell_tiers" :key="`sell-${index}`">
            <div class="two"><label>第{{ index + 1 }}档偏离度（%）<input v-model.number="tier.deviation_percent" type="number" step="1" min="-100" max="100" /></label><label>目标剩余仓位（%）<input v-model.number="tier.target_weight_percent" type="number" step="5" min="0" max="99" /></label></div>
            <button v-if="pcForm.sell_tiers.length > 1" type="button" @click="removePriceCenterSellTier(index)">删除卖出第{{ index + 1 }}档</button>
          </template>
          <button v-if="pcForm.sell_tiers.length < 10" type="button" @click="addPriceCenterSellTier">＋ 添加卖出档</button>
          <div class="two"><label>手续费率<input v-model.number="pcForm.fee_ratio" type="number" step="0.0001" min="0" /></label><label>滑点率<input v-model.number="pcForm.slippage_ratio" type="number" step="0.0001" min="0" /></label></div>
          <button class="primary" :disabled="busy" @click="submitPriceCenter">{{ busy ? '处理中…' : '开始价格中枢回测' }}</button>
        </div>
        <h3>ETF数据状态</h3><div class="table-wrap"><table><thead><tr><th>指数</th><th>ETF</th><th>行情</th><th>公司行为</th><th>最后日期</th><th>异常</th><th></th></tr></thead><tbody><tr v-for="item in pcInstruments" :key="item.index_id"><td>{{ item.index_name }}</td><td>{{ item.etf_name }}（{{ item.etf_code }}）</td><td>{{ item.data_status }}</td><td>{{ item.corporate_action_status }}</td><td>{{ item.last_success_date || '-' }}</td><td class="error-cell">{{ item.last_error || '-' }}</td><td><button :disabled="busy" @click="syncPriceCenter(item.index_id)">同步ETF</button></td></tr></tbody></table></div>
        <h3>历史任务</h3><div class="table-wrap"><table><thead><tr><th>ID</th><th>方案</th><th>指数/ETF</th><th>买/卖档</th><th>参考线</th><th>区间</th><th>状态</th><th>收益</th><th>基准</th><th></th></tr></thead><tbody><tr v-for="run in pcRuns" :key="run.id"><td>#{{ run.id }}</td><td>{{ run.parameters.scenario_name || '-' }}</td><td>{{ run.index_name }} / {{ run.etf_code }}</td><td>{{ run.parameters.buy_tiers?.length || 3 }} / {{ run.parameters.sell_tiers?.length || 2 }}</td><td>{{ priceCenterReferenceName(run) }}</td><td>{{ run.start_date }} ~ {{ run.end_date }}</td><td>{{ run.status }}</td><td>{{ run.summary ? (run.summary.total_return * 100).toFixed(2) + '%' : '-' }}</td><td>{{ run.summary ? (run.summary.benchmark_total_return * 100).toFixed(2) + '%' : '-' }}</td><td><button @click="showPriceCenterRun(run.id)">查看</button></td></tr></tbody></table></div>
      </section>

      <section v-if="page === 'price_center_result'">
        <button @click="nav('price_center')">← 返回价格中枢</button>
        <p v-if="selectedPcRun && ['QUEUED','RUNNING'].includes(selectedPcRun.status)" class="notice">任务状态：{{ selectedPcRun.status }}，正在同步ETF并计算…</p>
        <template v-if="selectedPcRun?.status === 'SUCCESS'">
          <div class="meta">{{ selectedPcRun.parameters.scenario_name ? selectedPcRun.parameters.scenario_name + ' · ' : '' }}{{ selectedPcRun.index_name }} → {{ selectedPcRun.etf_name }}（{{ selectedPcRun.etf_code }}） · 买{{ selectedPcRun.parameters.buy_tiers?.length || 3 }}档/卖{{ selectedPcRun.parameters.sell_tiers?.length || 2 }}档 · {{ priceCenterReferenceName(selectedPcRun) }} · {{ priceCenterFitDescription(selectedPcRun) }} · {{ selectedPcRun.summary.signal_evaluation_frequency === 'DAILY_CLOSE' ? '每日收盘判断' : '月末判断（历史版本）' }} · 共同起点 {{ selectedPcRun.summary.comparison_start_date }} · 公司行为 {{ selectedPcRun.summary.corporate_action_status }} · 现金收益假设0%</div>
          <div class="stats"><article><strong>{{ (selectedPcRun.summary.total_return * 100).toFixed(2) }}%</strong>策略累计收益</article><article><strong>{{ (selectedPcRun.summary.annualized_return * 100).toFixed(2) }}%</strong>策略年化收益</article><article><strong>{{ (selectedPcRun.summary.benchmark_total_return * 100).toFixed(2) }}%</strong>ETF累计收益</article><article><strong>{{ (selectedPcRun.summary.benchmark_annualized_return * 100).toFixed(2) }}%</strong>ETF年化收益</article><article><strong>{{ (selectedPcRun.summary.max_drawdown * 100).toFixed(2) }}%</strong>策略最大回撤</article><article><strong>{{ selectedPcRun.summary.calmar?.toFixed(2) ?? '-' }}</strong>Calmar</article></div>
          <div ref="pcChartEl" class="equity-chart"></div><div ref="pcEquityChartEl" class="equity-chart"></div>
          <div class="stats compact"><article><strong>{{ (selectedPcRun.summary.average_equity_ratio * 100).toFixed(1) }}%</strong>平均权益仓位</article><article><strong>{{ selectedPcRun.summary.max_equity_ratio == null ? '-' : (selectedPcRun.summary.max_equity_ratio * 100).toFixed(1) + '%' }}</strong>最高权益仓位</article><article><strong>{{ selectedPcRun.summary.full_position_days ?? '-' }}</strong>满仓交易日</article><article><strong>{{ selectedPcRun.summary.trade_count }}</strong>交易次数</article><article><strong>{{ (selectedPcRun.summary.average_cash_ratio * 100).toFixed(1) }}%</strong>平均现金比例</article><article><strong>{{ selectedPcRun.summary.max_drawdown_duration_days }}</strong>最大回撤持续天数</article></div>
          <h3>年度收益</h3><div class="table-wrap"><table><thead><tr><th>年度</th><th>中枢策略</th><th>ETF长期持有</th></tr></thead><tbody><tr v-for="entry in Object.entries(selectedPcRun.summary.yearly_returns)" :key="entry[0]"><td>{{ entry[0] }}</td><td>{{ (entry[1] * 100).toFixed(2) }}%</td><td>{{ ((selectedPcRun.summary.benchmark_yearly_returns[entry[0]] || 0) * 100).toFixed(2) }}%</td></tr></tbody></table></div>
          <h3>交易明细</h3><div class="table-wrap"><table><thead><tr><th>信号日</th><th>指数/参考线</th><th>偏离</th><th>状态</th><th>成交日</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th><th>费用</th><th>成交后现金/持仓</th><th>原因</th></tr></thead><tbody><tr v-for="trade in pcTrades" :key="trade.id"><td>{{ trade.signal_month }}</td><td>{{ trade.index_close.toFixed(2) }} / {{ trade.ma_value.toFixed(2) }}</td><td>{{ (trade.deviation * 100).toFixed(2) }}%</td><td>{{ trade.old_state }} → {{ trade.target_state }}</td><td>{{ trade.trade_date }}</td><td>{{ trade.side }}</td><td>{{ trade.fill_price.toFixed(4) }}</td><td>{{ trade.quantity }}</td><td>{{ trade.notional.toFixed(2) }}</td><td>{{ trade.fee.toFixed(2) }}</td><td>{{ trade.cash_after.toFixed(2) }} / {{ trade.shares_after }}</td><td>{{ trade.reason }}</td></tr></tbody></table></div>
          <h3>触发决策记录</h3><div class="table-wrap"><table><thead><tr><th>判断日</th><th>指数收盘</th><th>参考线</th><th>偏离度</th><th>状态</th><th>原因</th><th>订单</th></tr></thead><tbody><tr v-for="row in pcMonthly" :key="row.month_end"><td>{{ row.month_end }}</td><td>{{ row.index_close.toFixed(2) }}</td><td>{{ row.ma_value.toFixed(2) }}</td><td>{{ (row.deviation * 100).toFixed(2) }}%</td><td>{{ row.old_state }} → {{ row.target_state }} / {{ row.actual_state }}</td><td>{{ row.reason }}</td><td>{{ row.order_status }}</td></tr></tbody></table></div>
        </template>
      </section>

      <section v-if="page === 'backtest'" class="form wide"><h3>理论指数回测</h3><p class="hint">突破回踩会先等待底部放量突破，再等窄幅整理守住突破位，确认后下一交易日买入；用于减少追高和交易次数。策略 D 用于失败快退、盈利趋势慢退。</p><label>指数<select v-model="form.index_id"><option v-for="item in indices.filter(x => x.enabled)" :key="item.id" :value="item.id">{{ item.index_name }}（{{ item.index_code }}）</option></select></label><div class="two"><label>信号类型<select v-model="form.signal_mode"><option value="ENGULFING">吞没形态</option><option value="BREAKOUT_PULLBACK">日线放量突破后回踩</option></select></label><label>吞没周期<select v-model="form.signal_period" :disabled="form.signal_mode === 'BREAKOUT_PULLBACK'"><option value="1w">周线吞没</option><option value="1d">日线吞没</option></select></label></div><div class="two"><label>策略<select v-model="form.strategy"><option value="ALL">A / B / C / D 四套策略对比（推荐）</option><option v-for="(name, key) in strategies" :key="key" :value="key">{{ name }}</option></select></label><label>入场时机<select v-model="form.entry_timing"><option value="NEXT_OPEN">确认后下一交易日开盘（推荐）</option><option value="SIGNAL_CLOSE">确认日收盘价模拟</option></select></label></div><div class="two"><label>初始止损缓冲（%）<input v-model.number="form.stop_buffer_percent" type="number" step="0.5" min="0" max="50" /><span class="hint">突破回踩使用突破位/回踩低点中较低者，再向下增加缓冲</span></label><label>开始日期<input v-model="form.start_date" type="date" /></label></div><div class="two"><label>结束日期<input v-model="form.end_date" type="date" /></label><label>初始资金<input v-model.number="form.initial_capital" type="number" min="1" /></label></div><div class="two"><label>单笔风险<input v-model.number="form.risk_ratio" type="number" step="0.001" min="0.001" max="1" /></label><label>最大止损（超出跳过）<input v-model.number="form.max_stop_ratio" type="number" step="0.01" min="0.01" max="1" /></label></div><div class="two"><label>最大仓位<input v-model.number="form.max_position_ratio" type="number" step="0.01" min="0.01" max="1" /></label><label>手续费率<input v-model.number="form.fee_ratio" type="number" step="0.0001" min="0" /></label></div><label>滑点率<input v-model.number="form.slippage_ratio" type="number" step="0.0001" min="0" /></label><button class="primary" :disabled="busy" @click="submit">{{ busy ? '提交中…' : '提交回测任务' }}</button></section>

      <section v-if="page === 'runs'"><div class="toolbar"><button :disabled="!compareIds.length" @click="compareSelected">对比已选任务（{{ compareIds.length }}）</button><button @click="loadRuns">刷新状态</button></div><div class="table-wrap"><table><thead><tr><th>选择</th><th>ID</th><th>指数</th><th>信号类型</th><th>策略</th><th>区间</th><th>状态</th><th>收益</th><th></th></tr></thead><tbody><tr v-for="run in runs" :key="run.id"><td><input v-model="compareIds" type="checkbox" :value="run.id" /></td><td>{{ run.id }}</td><td>{{ indices.find(x => x.id === run.index_id)?.index_name || run.index_id }}</td><td>{{ signalName(run) }}</td><td>{{ run.strategy }}</td><td>{{ run.start_date }} ~ {{ run.end_date }}</td><td><span class="chip">{{ run.status }}</span></td><td>{{ run.summary ? (run.summary.total_return * 100).toFixed(2) + '%' : '-' }}</td><td><button @click="showRun(run.id)">查看</button></td></tr></tbody></table></div><div v-if="comparison.length"><h3>策略对比</h3><div class="table-wrap"><table><thead><tr><th>任务</th><th>信号类型</th><th>策略</th><th>年化</th><th>最大回撤</th><th>Calmar</th><th>胜率</th><th>交易数</th></tr></thead><tbody><tr v-for="run in comparison" :key="run.id"><td>#{{ run.id }}</td><td>{{ signalName(run) }}</td><td>{{ run.strategy }}</td><td>{{ run.summary ? (run.summary.annualized_return * 100).toFixed(2) + '%' : '-' }}</td><td>{{ run.summary ? (run.summary.max_drawdown * 100).toFixed(2) + '%' : '-' }}</td><td>{{ run.summary?.calmar?.toFixed(2) ?? '-' }}</td><td>{{ run.summary ? (run.summary.win_rate * 100).toFixed(1) + '%' : '-' }}</td><td>{{ run.summary?.trade_count ?? '-' }}</td></tr></tbody></table></div></div></section>

      <section v-if="page === 'result'"><button @click="page = 'runs'">← 返回任务</button><p v-if="selectedRun && ['QUEUED','RUNNING'].includes(selectedRun.status)" class="notice">任务状态：{{ selectedRun.status }}，正在自动刷新…</p><template v-if="selectedRun?.status === 'SUCCESS'"><div class="meta">回测对象：{{ selectedRunIndex?.index_name || `指数 #${selectedRun.index_id}` }}（{{ selectedRunIndex?.index_code || '-' }}） · {{ signalName(selectedRun) }} · {{ selectedRun.parameters?.entry_timing === 'SIGNAL_CLOSE' ? '确认日收盘价模拟买入' : '确认后下一交易日开盘买入' }} · 止损缓冲 {{ ((selectedRun.parameters?.stop_buffer_ratio || 0) * 100).toFixed(2) }}% · 策略 {{ selectedRun.strategy }} · 数据版本 {{ selectedRun.data_version }} · 信号算法 {{ selectedRun.signal_algorithm_version }}</div><div class="stats"><article><strong>{{ ((summary.total_return || 0) * 100).toFixed(2) }}%</strong>策略收益</article><article><strong>{{ ((summary.annualized_return || 0) * 100).toFixed(2) }}%</strong>年化收益</article><article><strong>{{ ((summary.max_drawdown || 0) * 100).toFixed(2) }}%</strong>最大回撤</article><article><strong>{{ summary.calmar?.toFixed(2) ?? '-' }}</strong>Calmar</article></div><h3>策略净值与指数 K 线</h3><div class="toolbar"><button :class="{ primary: chartPeriod === '1w' }" @click="setChartPeriod('1w')">周 K</button><button :class="{ primary: chartPeriod === '1d' }" @click="setChartPeriod('1d')">日 K</button><span class="hint">默认展示信号周期；可切换周期检查成交与止损</span></div><div ref="chartEl" class="equity-chart"></div><h3>交易明细</h3><div class="table-wrap"><table><thead><tr><th>信号</th><th>信号日期</th><th>买入日期</th><th>买入价</th><th>数量</th><th>初始止损</th><th>卖出日期</th><th>卖出价</th><th>费用</th><th>净盈亏</th><th>退出原因</th></tr></thead><tbody><tr v-for="trade in trades" :key="trade.id"><td>{{ trade.signal_id }}</td><td>{{ trade.signal_date || '-' }}</td><td>{{ trade.entry_date }}</td><td>{{ trade.entry_price }}</td><td>{{ trade.quantity }}</td><td>{{ trade.initial_stop }}</td><td>{{ trade.exit_date || '-' }}</td><td>{{ trade.exit_price || '-' }}</td><td>{{ trade.total_fee.toFixed(2) }}</td><td :class="trade.net_pnl >= 0 ? 'positive' : 'negative'">{{ trade.net_pnl?.toFixed(2) ?? '-' }}</td><td>{{ trade.exit_reason || '持仓中' }}</td></tr></tbody></table></div></template></section>
    </main>
  </div>
</template>
