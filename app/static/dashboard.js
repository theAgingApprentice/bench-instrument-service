'use strict';

const POLL_INTERVAL_MS = 10000;

// Map instrument keys to their DOM element IDs
const INSTRUMENT_MAP = {
  oscilloscope:     { ip: 'osc-ip', identity: 'osc-identity', status: 'osc-status', card: 'card-oscilloscope' },
  signal_generator: { ip: 'sig-ip', identity: 'sig-identity', status: 'sig-status', card: 'card-signal_generator' },
  multimeter:       { ip: 'mm-ip',  identity: 'mm-identity',  status: 'mm-status',  card: 'card-multimeter' },
  power_supply:     { ip: 'psu-ip', identity: 'psu-identity', status: 'psu-status', card: 'card-power_supply' },
};

function $(id) { return document.getElementById(id); }

function formatUptime(seconds) {
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function formatTimeRemaining(expiresAt) {
  const diff = Math.max(0, Math.floor((new Date(expiresAt) - Date.now()) / 1000));
  if (diff === 0) return 'expired';
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatTimestamp(iso) {
  return new Date(iso).toLocaleTimeString();
}

function setOverallStatus(status) {
  const el = $('overall-status');
  el.textContent = status;
  el.className = `badge badge--${status === 'ok' ? 'ok' : status === 'degraded' ? 'degraded' : 'error'}`;
}

function updateInstruments(instruments) {
  for (const [key, ids] of Object.entries(INSTRUMENT_MAP)) {
    const data = instruments[key];
    if (!data) continue;

    const reachable = data.reachable;
    const card = $(ids.card);
    card.classList.toggle('card--reachable',   reachable);
    card.classList.toggle('card--unreachable', !reachable);

    const dot = card.querySelector('.status-dot');
    dot.className = `status-dot ${reachable ? 'dot--ok' : 'dot--error'}`;

    $(ids.ip).textContent       = data.ip || '—';
    $(ids.identity).textContent = data.identity || '—';
    $(ids.status).textContent   = reachable ? 'Reachable' : 'Unreachable';
  }
}

function updateSession(session) {
  const noneEl   = $('session-none');
  const activeEl = $('session-active');

  if (!session) {
    noneEl.classList.remove('hidden');
    activeEl.classList.add('hidden');
    return;
  }

  noneEl.classList.add('hidden');
  activeEl.classList.remove('hidden');
  $('sess-client').textContent    = session.client_id;
  $('sess-token').textContent     = session.session_id;
  $('sess-expires').textContent   = formatTimestamp(session.expires_at);
  $('sess-remaining').textContent = formatTimeRemaining(session.expires_at);
}

async function poll() {
  try {
    const resp = await fetch('health/full');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    setOverallStatus(data.status);
    $('uptime').textContent = `uptime: ${formatUptime(data.uptime_seconds)}`;
    $('last-updated').textContent = `last updated: ${new Date().toLocaleTimeString()}`;

    updateInstruments(data.instruments);
    updateSession(data.session);
  } catch (err) {
    $('overall-status').textContent = 'unreachable';
    $('overall-status').className = 'badge badge--error';
    $('last-updated').textContent = `last updated: ${new Date().toLocaleTimeString()} (error)`;
    console.error('BIS poll error:', err);
  }
}

// Run immediately then on interval
poll();
setInterval(poll, POLL_INTERVAL_MS);
