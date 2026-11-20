import http from 'k6/http';
import exec from 'k6/execution';
import { check, fail } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const mode = __ENV.MODE || 'mixed';
const rate = Number(__ENV.RATE || 2);
const duration = __ENV.DURATION || '30s';
const vus = Number(__ENV.VUS || 100);
const base = __ENV.BASE_URL || 'http://api:8080';
if (!['smoke', 'mixed', 'heavy'].includes(mode)) throw new Error('MODE: smoke|mixed|heavy');
if (!Number.isInteger(rate) || rate < 1) throw new Error('RATE must be a positive integer');
if (!/^\d+s$/.test(duration)) throw new Error('DURATION must be seconds, e.g. 30s');

// Exactly one business HTTP request per iteration. Login is only in setup().
const latency = new Trend('business_duration', true);
const errors = new Rate('business_errors');
const completed = new Counter('business_completed');
const starts = new Trend('business_start_ms');
const ends = new Trend('business_end_ms');
const names = ['categories', 'list', 'filtered_list', 'card', 'create', 'comment', 'status', 'summary'];
const weights = [5, 30, 15, 25, 8, 8, 7, 2];

export const options = {
  scenarios: mode === 'smoke' ? {
    smoke: { executor: 'shared-iterations', vus: 1, iterations: 8, maxDuration: '60s' },
  } : {
    [mode]: {
      executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration,
      preAllocatedVUs: vus, maxVUs: vus, gracefulStop: '30s',
    },
  },
  thresholds: mode === 'smoke' ? { business_errors: ['rate==0'] } : {
    business_duration: ['p(95)<500'], business_errors: ['rate<0.01'],
  },
  summaryTrendStats: ['med', 'p(95)', 'max', 'min'],
  systemTags: ['status', 'method', 'name', 'scenario', 'expected_response'],
};

export function setup() {
  const response = http.post(`${base}/api/login`, JSON.stringify({
    username: 'demo', password: __ENV.APP_PASSWORD || 'demo',
  }), { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } });
  if (response.status !== 200) fail(`Login failed: ${response.status}: ${response.body}`);
  const cookies = {};
  for (const name of Object.keys(response.cookies)) cookies[name] = response.cookies[name][0].value;
  if (!cookies.session) fail('Login returned no session cookie');
  return { cookies };
}

function choose(i) {
  if (mode === 'heavy') return 'summary';
  if (mode === 'smoke') return names[i];
  // A permutation of 0..99: exact weights in each 100 started iterations.
  const slot = (i * 37) % 100;
  let limit = 0;
  for (let n = 0; n < names.length; n++) {
    limit += weights[n];
    if (slot < limit) return names[n];
  }
}

export default function (data) {
  const i = exec.scenario.iterationInTest;
  const operation = choose(i);
  const tag = { operation };
  let path, method = 'GET', body = null, expected = 200;
  switch (operation) {
    case 'categories': path = '/api/categories'; break;
    case 'list': path = '/api/tickets?page=1&size=20'; break;
    case 'filtered_list': path = '/api/tickets?page=1&size=20&status=new'; break;
    case 'card': path = `/api/tickets/${1 + (i % 50000)}`; break;
    case 'summary': path = '/api/summary'; break;
    case 'create':
      method = 'POST'; path = '/api/tickets'; expected = 201;
      body = { title: `nikita_zozulenko ${i}`, body: 'Нагрузочное испытание', category_id: 1 + (i % 10) };
      break;
    case 'comment':
      method = 'POST'; path = `/api/tickets/${1 + 3 * (i % 16666)}/comments`; expected = 201;
      body = { body: `nikita_zozulenko ответ ${i}` }; break;
    case 'status':
      method = 'PATCH'; path = `/api/tickets/${3 + 3 * (i % 16666)}/status`;
      body = { status: 'in_progress' }; break;
  }
  starts.add(Date.now());
  const response = http.request(method, base + path, body === null ? null : JSON.stringify(body), {
    cookies: data.cookies, headers: { 'Content-Type': 'application/json' },
    tags: { name: operation, ...tag }, timeout: '30s',
    responseCallback: http.expectedStatuses(expected, ...(operation === 'status' || operation === 'comment' ? [409] : [])),
  });
  let json = null;
  try { json = response.json(); } catch (_) { /* Count non-JSON responses as errors. */ }
  const expectedRefusal = response.status === 409 && (
    (operation === 'status' && json && json.error === 'invalid_transition') ||
    (operation === 'comment' && json && json.error === 'ticket_closed')
  );
  const ok = (response.status === expected && json !== null && !json.error) || expectedRefusal;
  latency.add(response.timings.duration, tag);
  errors.add(!ok, tag);
  completed.add(1, tag);
  ends.add(Date.now());
  check(response, { 'expected business response': () => ok }, tag);
  if (!ok || mode === 'smoke') console.log(`${operation}: HTTP ${response.status}${ok ? ' OK' : ` ERROR ${response.body}`}`);
}

export function handleSummary(data) {
  const values = (name) => data.metrics[name] ? data.metrics[name].values : {};
  const timing = values('business_duration');
  const count = values('business_completed').count || 0;
  const dropped = values('dropped_iterations').count || 0;
  const elapsed = Math.max(mode === 'smoke' ? 0 : parseInt(duration),
    ((values('business_end_ms').max || 0) - (values('business_start_ms').min || 0)) / 1000);
  const errorRate = values('business_errors').rate || 0;
  const pass = count > 0 && errorRate < (mode === 'smoke' ? 0.000001 : 0.01) && (mode === 'smoke' || timing['p(95)'] < 500);
  const result = {
    mode, configured_rps: mode === 'smoke' ? null : rate, duration, vus,
    completed: count, dropped_iterations: dropped, elapsed_business_s: elapsed,
    actual_rps: elapsed > 0 ? count / elapsed : 0,
    median_ms: timing.med, p95_ms: timing['p(95)'], max_ms: timing.max,
    error_rate: errorRate, threshold_pass: pass,
    weights: Object.fromEntries(names.map((n, i) => [n, weights[i]])),
    raw_summary: data,
  };
  const f = (n) => Number(n || 0).toFixed(2);
  const text = `\nnikita_zozulenko | ${mode}\n` +
    `Completed: ${count}; dropped_iterations: ${dropped}; actual RPS: ${f(result.actual_rps)}\n` +
    `p50: ${f(timing.med)} ms; p95: ${f(timing['p(95)'])} ms; max: ${f(timing.max)} ms\n` +
    `Errors: ${f(errorRate * 100)}%; thresholds: ${pass ? 'PASS' : 'FAIL'}\n`;
  const output = { stdout: text };
  if (__ENV.RESULT) output[__ENV.RESULT] = JSON.stringify(result, null, 2);
  return output;
}
