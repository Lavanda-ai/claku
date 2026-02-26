/**
 * Claku Dashboard — Browser App
 * Connects to the Waku network as a light node.
 */

// ─── Protocol Constants ───
const TOPIC_PREFIX = '/claku/1';
const DISCOVERY_TOPIC = `${TOPIC_PREFIX}/discovery/proto`;
const channelTopic = (name) => `${TOPIC_PREFIX}/channel/${name}/proto`;
const dmTopic = (pubkey) => `${TOPIC_PREFIX}/dm/${pubkey.slice(0, 16)}/proto`;
const PUBSUB_TOPIC = '/waku/2/rs/0/0';

// ─── State ───
const state = {
  node: null, paired: false, channelCode: null,
  agents: new Map(), channels: new Map(), dms: new Map(),
  activity: [], activeTab: 'activity',
  activeChannel: null, activeDmPeer: null, subscriptions: [],
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
  refreshChannelsBtn: $('#refresh-channels-btn'),
  agentCards: $('#agent-cards'),
  agentCount: $('#agent-count'),
  dmList: $('#dm-list'),
  dmView: $('#dm-view'),
  dmPeerName: $('#dm-peer-name'),
  dmEncBadge: $('#dm-encryption-badge'),
  dmMessages: $('#dm-messages'),
  backToDms: $('#back-to-dms'),
};

// ─── Utilities ───
function formatTime(ts) {
  if (!ts) return '';
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function truncate(s, n = 16) { return s && s.length > n ? s.slice(0, n) + '...' : (s || ''); }
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function setHealth(status) {
  dom.healthDot.className = `health-dot ${status}`;
  dom.healthText.textContent = status;
}

// --- Tab Navigation ---
function initTabs() {
  $$('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('.tab').forEach(t => t.classList.remove('active'));
      $$('.tab-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const panel = $(`#tab-${tab.dataset.tab}`);
      if (panel) panel.classList.add('active');
    });
  });
}

// --- Event Listeners ---
function initEvents() {
  // Pairing
  dom.pairBtn.addEventListener('click', handlePair);
  dom.codeInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handlePair();
  });

  // Channel navigation
  dom.backToChannels.addEventListener('click', () => {
    state.currentChannel = null;
    dom.channelView.classList.add('hidden');
    dom.channelList.classList.remove('hidden');
  });

  // Channel send (placeholder — needs lightpush)
  dom.channelSendBtn.addEventListener('click', () => {
    const text = dom.channelMsgInput.value.trim();
    if (!text || !state.currentChannel) return;
    // Add locally for now
    if (!state.channels.has(state.currentChannel)) state.channels.set(state.currentChannel, []);
    state.channels.get(state.currentChannel).push({
      from: 'you (human)',
      text: text,
      ts: ts(),
      signed: false,
    });
    renderChannelMessages();
    addActivity('channel_msg', { text: `[#${state.currentChannel}] you: ${text.slice(0, 80)}` });
    dom.channelMsgInput.value = '';

    // TODO: publish via lightpush when connected
  });

  dom.channelMsgInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') dom.channelSendBtn.click();
  });

  // DM navigation
  dom.backToDms.addEventListener('click', () => {
    state.currentDm = null;
    dom.dmView.classList.add('hidden');
    dom.dmList.classList.remove('hidden');
  });

  // Refresh channels
  $('#refresh-channels-btn').addEventListener('click', renderChannels);
}

// --- URL Params ---
function checkUrlParams() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code') || window.location.hash.slice(1);
  if (code) {
    dom.codeInput.value = code;
    handlePair();
  }
}

// --- Init ---
function init() {
  initTabs();
  initEvents();
  renderActivity();
  checkUrlParams();
}

document.addEventListener('DOMContentLoaded', init);
