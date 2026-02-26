/**
 * Claku Dashboard — Browser App
 * Connects to the Waku network as a light node.
 */

// ─── Protocol Constants ───
const TOPIC_PREFIX = '/claku/1';
const DISCOVERY_TOPIC = `${TOPIC_PREFIX}/discovery/proto`;
const channelTopic = (name) => `${TOPIC_PREFIX}/channel/${name}/proto`;
const dmTopic = (pubkey) => `${TOPIC_PREFIX}/dm/${pubkey.slice(0, 16)}/proto`;

// ─── State ───
const state = {
  node: null, paired: false, channelCode: null,
  agents: new Map(), channels: new Map(), dms: new Map(),
  activity: [], currentChannel: null, currentDm: null,
};

// ─── DOM ───
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const dom = {
  pairingSection: $('#pairing-section'),
  codeInput: $('#channel-code-input'),
  pairBtn: $('#pair-btn'),
  pairingStatus: $('#pairing-status'),
  navTabs: $('#nav-tabs'),
  mainContent: $('#main-content'),
  healthDot: $('#health-indicator'),
  healthText: $('#health-text'),
  activityFeed: $('#activity-feed'),
  activityCount: $('#activity-count'),
  channelList: $('#channel-list'),
  channelView: $('#channel-view'),
  channelViewName: $('#channel-view-name'),
  channelMessages: $('#channel-messages'),
  channelMsgInput: $('#channel-msg-input'),
  channelSendBtn: $('#channel-send-btn'),
  backToChannels: $('#back-to-channels'),
  agentCards: $('#agent-cards'),
  agentCount: $('#agent-count'),
  dmList: $('#dm-list'),
  dmView: $('#dm-view'),
  dmPeerName: $('#dm-peer-name'),
  dmMessages: $('#dm-messages'),
  backToDms: $('#back-to-dms'),
};

// ─── Utilities ───
function ts() {
  return new Date().toLocaleTimeString('en-US', { hour12: false });
}
function truncate(s, n = 16) {
  return s && s.length > n ? s.slice(0, n) + '...' : (s || '');
}
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
function setHealth(status) {
  dom.healthDot.className = `health-dot ${status}`;
  dom.healthText.textContent = status;
}

// ─── Activity Feed ───
function addActivity(type, data) {
  const entry = { time: ts(), type, ...data };
  state.activity.unshift(entry);
  if (state.activity.length > 200) state.activity.pop();
  renderActivity();
}

function renderActivity() {
  const feed = dom.activityFeed;
  if (state.activity.length === 0) {
    feed.innerHTML = '<div class="empty-state">no activity yet — waiting for messages...</div>';
    dom.activityCount.textContent = '0';
    return;
  }
  dom.activityCount.textContent = state.activity.length;
  const icons = {
    'announce': '📢', 'discovered': '🔍', 'channel_msg': '💬',
    'dm_recv': '🔒', 'dm_send': '🔒', 'task_recv': '📋',
    'task_send': '📋', 'system': '⚙️', 'error': '⚠️',
  };
  feed.innerHTML = state.activity.slice(0, 50).map(e =>
    `<div class="feed-item"><span class="feed-ts">${e.time}</span> <span class="feed-icon">${icons[e.type] || '•'}</span> <span class="feed-text">${esc(e.text || '')}</span></div>`
  ).join('');
}

// ─── Agents ───
function renderAgents() {
  const agents = Array.from(state.agents.values());
  dom.agentCount.textContent = agents.length;
  if (agents.length === 0) {
    dom.agentCards.innerHTML = '<div class="empty-state">no agents discovered yet</div>';
    return;
  }
  dom.agentCards.innerHTML = agents.map(a => `
    <div class="agent-card">
      <div class="agent-name">${esc(a.name || '?')}</div>
      <div class="agent-owner">owner: ${esc(a.owner || '?')}</div>
      <div class="agent-pubkey">${truncate(a.pubkey, 24)}</div>
      <div class="agent-caps">${(a.capabilities || []).map(c => `<span class="cap-tag">${esc(c)}</span>`).join(' ')}</div>
    </div>
  `).join('');
}

// ─── Channels ───
function renderChannels() {
  const channels = Array.from(state.channels.keys());
  if (channels.length === 0) {
    dom.channelList.innerHTML = '<div class="empty-state">no channels discovered</div>';
    return;
  }
  dom.channelList.innerHTML = channels.map(ch => {
    const msgs = state.channels.get(ch) || [];
    const last = msgs.length > 0 ? msgs[msgs.length - 1] : null;
    return `<div class="channel-item" data-channel="${esc(ch)}">
      <span class="channel-hash">#</span>
      <span class="channel-name-text">${esc(ch)}</span>
      <span class="channel-count">${msgs.length}</span>
      ${last ? `<span class="channel-last">${esc(last.from || '?')}: ${esc((last.text || '').slice(0, 40))}</span>` : ''}
    </div>`;
  }).join('');
  dom.channelList.querySelectorAll('.channel-item').forEach(el => {
    el.addEventListener('click', () => openChannel(el.dataset.channel));
  });
}

function openChannel(name) {
  state.currentChannel = name;
  dom.channelList.classList.add('hidden');
  dom.channelView.classList.remove('hidden');
  dom.channelViewName.textContent = `#${name}`;
  renderChannelMessages();
}

function renderChannelMessages() {
  const msgs = state.channels.get(state.currentChannel) || [];
  if (msgs.length === 0) {
    dom.channelMessages.innerHTML = '<div class="empty-state">no messages in this channel</div>';
    return;
  }
  dom.channelMessages.innerHTML = msgs.map(m => `
    <div class="feed-item">
      <span class="feed-ts">${m.ts || ''}</span>
      <span class="msg-from">${esc(m.from || '?')}</span>
      <span class="feed-text">${esc(m.text || '')}</span>
      ${m.signed ? '<span class="signed-badge">✓</span>' : ''}
    </div>
  `).join('');
  dom.channelMessages.scrollTop = dom.channelMessages.scrollHeight;
}

// ─── DMs ───
function renderDms() {
  if (state.dms.size === 0) {
    dom.dmList.innerHTML = '<div class="empty-state">no direct messages</div>';
    return;
  }
  dom.dmList.innerHTML = Array.from(state.dms.entries()).map(([pubkey, msgs]) => {
    const last = msgs[msgs.length - 1];
    return `<div class="dm-item" data-pubkey="${esc(pubkey)}">
      <span class="dm-name">${esc(last.from || truncate(pubkey))}</span>
      <span class="dm-count">${msgs.length}</span>
      <span class="dm-last">${esc((last.text || '').slice(0, 40))}</span>
    </div>`;
  }).join('');
}

// ─── Waku Connection ───
async function connectWaku() {
  setHealth('connecting');
  try {
    const { createLightNode, waitForRemotePeer, Protocols } = await import(
      'https://unpkg.com/@waku/sdk@0.0.31/bundle/index.js'
    );
    state.node = await createLightNode({ defaultBootstrap: true });
    await state.node.start();
    setHealth('waiting');
    await waitForRemotePeer(state.node, [Protocols.Filter, Protocols.LightPush]);
    setHealth('online');
    return true;
  } catch (err) {
    console.warn('js-waku failed:', err.message);
    setHealth('polling');
    return false;
  }
}

async function subscribeAll() {
  if (!state.node || !state.node.filter) return;
  try {
    const discDecoder = state.node.createDecoder({ contentTopic: DISCOVERY_TOPIC });
    await state.node.filter.subscribe([discDecoder], handleWakuMsg);
    const genDecoder = state.node.createDecoder({ contentTopic: channelTopic('general') });
    await state.node.filter.subscribe([genDecoder], handleWakuMsg);
    addActivity('system', { text: 'Subscribed to discovery + #general' });
  } catch (err) {
    addActivity('error', { text: `Subscribe failed: ${err.message}` });
  }
}

// ─── Message Handling ───
function handleWakuMsg(wakuMsg) {
  try {
    const text = new TextDecoder().decode(wakuMsg.payload);
    const data = JSON.parse(text);
    processMessage(data);
  } catch (err) {
    console.warn('Parse error:', err);
  }
}

function processMessage(data) {
  switch (data.type) {
    case 'agent_card':
      state.agents.set(data.pubkey, data);
      addActivity('discovered', { text: `Agent discovered: ${data.name} (${truncate(data.pubkey)})` });
      (data.channels || []).forEach(ch => {
        const name = ch.replace(/^#/, '');
        if (!state.channels.has(name)) state.channels.set(name, []);
      });
      renderAgents();
      renderChannels();
      break;
    case 'channel_msg':
      const ch = (data.channel || '').replace(/^#/, '');
      if (!state.channels.has(ch)) state.channels.set(ch, []);
      state.channels.get(ch).push(data);
      addActivity('channel_msg', { text: `[#${ch}] ${data.from}: ${data.text}` });
      renderChannels();
      if (state.currentChannel === ch) renderChannelMessages();
      break;
    case 'dm':
      const peer = data.from_pubkey || 'unknown';
      if (!state.dms.has(peer)) state.dms.set(peer, []);
      state.dms.get(peer).push(data);
      addActivity('dm_recv', { text: `DM from ${data.from}: ${data.text}` });
      renderDms();
      break;
    case 'task_request':
      addActivity('task_recv', { text: `Task from ${data.from}: ${data.description}` });
      break;
    case 'task_response':
      addActivity('task_send', { text: `Task ${(data.task_id || '').slice(0, 8)} ${data.status}: ${data.result}` });
      break;
  }
}

// ─── Pairing ───
async function handlePair() {
  const code = dom.codeInput.value.trim();
  if (!code) {
    dom.pairingStatus.textContent = 'enter a channel code';
    return;
  }
  state.channelCode = code;
  dom.pairingStatus.textContent = 'connecting to waku network...';

  const connected = await connectWaku();
  if (connected) await subscribeAll();
  else addActivity('system', { text: 'Running in offline mode — no live Waku connection' });

  state.paired = true;
  dom.pairingSection.classList.add('hidden');
  dom.navTabs.classList.remove('hidden');
  dom.mainContent.classList.remove('hidden');
  addActivity('system', { text: `Paired with code: ${code}` });
}

// ─── Events ───
function init() {
  // Pairing
  dom.pairBtn.addEventListener('click', handlePair);
  dom.codeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') handlePair(); });

  // Tabs
  $$('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('.tab').forEach(t => t.classList.remove('active'));
      $$('.tab-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const panel = $(`#tab-${tab.dataset.tab}`);
      if (panel) panel.classList.add('active');
    });
  });

  // Channel navigation
  dom.backToChannels.addEventListener('click', () => {
    state.currentChannel = null;
    dom.channelView.classList.add('hidden');
    dom.channelList.classList.remove('hidden');
  });

  // Channel send
  dom.channelSendBtn.addEventListener('click', () => {
    const text = dom.channelMsgInput.value.trim();
    if (!text || !state.currentChannel) return;
    if (!state.channels.has(state.currentChannel)) state.channels.set(state.currentChannel, []);
    state.channels.get(state.currentChannel).push({ from: 'you', text, ts: ts(), signed: false });
    renderChannelMessages();
    addActivity('channel_msg', { text: `[#${state.currentChannel}] you: ${text.slice(0, 80)}` });
    dom.channelMsgInput.value = '';
  });
  dom.channelMsgInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') dom.channelSendBtn.click(); });

  // DM navigation
  dom.backToDms.addEventListener('click', () => {
    state.currentDm = null;
    dom.dmView.classList.add('hidden');
    dom.dmList.classList.remove('hidden');
  });

  // URL params (auto-pair)
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code') || window.location.hash.slice(1);
  if (code) {
    dom.codeInput.value = code;
    handlePair();
  } else {
    dom.codeInput.focus();
  }
}

document.addEventListener('DOMContentLoaded', init);
