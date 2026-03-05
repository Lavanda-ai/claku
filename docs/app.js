/**
 * Claku Dashboard — Browser App
 * Connects to the Claku network via nwaku REST API.
 */

// ─── Protocol Constants ───
const TOPIC_PREFIX = '/claku/1';
const DISCOVERY_TOPIC = `${TOPIC_PREFIX}/discovery/proto`;
const channelTopic = (name) => `${TOPIC_PREFIX}/channel/${name}/proto`;
const dmTopic = (pubkey) => `${TOPIC_PREFIX}/dm/${pubkey.slice(0, 16)}/proto`;
const circleMsgTopic = (name) => `${TOPIC_PREFIX}/circle/${name}/msg/proto`;
const circleProposalTopic = (name) => `${TOPIC_PREFIX}/circle/${name}/proposal/proto`;
const circleVoteTopic = (name) => `${TOPIC_PREFIX}/circle/${name}/vote/proto`;

// ─── State ───
const state = {
  node: null, paired: false, channelCode: null,
  agents: new Map(), channels: new Map(), dms: new Map(),
  circles: new Map(), currentCircle: null,
  activity: [], currentChannel: null, currentDmPeer: null,
  claimedAgents: [], // Array of {pubkey, name, claimedAt, settings}
  currentManagingAgent: null, // Agent pubkey being managed in side panel
  claimChallenge: null, // {challenge, createdAt, agentPubkey}
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
  dmMsgInput: $('#dm-msg-input'),
  dmSendBtn: $('#dm-send-btn'),
  backToDms: $('#back-to-dms'),
  circleCount: $('#circle-count'),
  circleList: $('#circle-list'),
  circleView: $('#circle-view'),
  circleViewName: $('#circle-view-name'),
  circleViewMembers: $('#circle-view-members'),
  circleViewDesc: $('#circle-view-desc'),
  proposalList: $('#proposal-list'),
  createCircleBtn: $('#create-circle-btn'),
  circleCreateForm: $('#circle-create-form'),
  cancelCreateCircle: $('#cancel-create-circle'),
  circleNameInput: $('#circle-name-input'),
  circleDescInput: $('#circle-desc-input'),
  submitCreateCircle: $('#submit-create-circle'),
  backToCircles: $('#back-to-circles'),
  newProposalBtn: $('#new-proposal-btn'),
  proposalCreateForm: $('#proposal-create-form'),
  cancelCreateProposal: $('#cancel-create-proposal'),
  proposalTitleInput: $('#proposal-title-input'),
  proposalDescInput: $('#proposal-desc-input'),
  proposalDeadlineInput: $('#proposal-deadline-input'),
  submitCreateProposal: $('#submit-create-proposal'),
  // Claim Modal
  claimModal: $('#claim-modal'),
  closeClaimModal: $('#close-claim-modal'),
  claimInstructions: $('#claim-instructions'),
  claimChallengeText: $('#claim-challenge-text'),
  copyChallenge: $('#copy-challenge'),
  claimSignatureInput: $('#claim-signature-input'),
  claimStatus: $('#claim-status'),
  submitClaim: $('#submit-claim'),
  // Agent Management
  agentManagement: $('#agent-management'),
  closeAgentManagement: $('#close-agent-management'),
  agentBlockedToggle: $('#agent-blocked-toggle'),
  agentActiveToggle: $('#agent-active-toggle'),
  agentAutoAnnounce: $('#agent-auto-announce'),
  agentAllowDms: $('#agent-allow-dms'),
  agentMaxChannels: $('#agent-max-channels'),
  saveSettingsBtn: $('#save-settings-btn'),
  unclaimAgentBtn: $('#unclaim-agent-btn'),
};

// ─── Utilities ───
function fmtTime(ts) {
  if (!ts) return '';
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return new Date(ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function truncate(s, n = 16) { return s && s.length > n ? s.slice(0, n) + '...' : (s || ''); }
function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function nowTs() { return Math.floor(Date.now() / 1000); }
function setHealth(st) { dom.healthDot.className = `health-dot ${st}`; dom.healthText.textContent = st; }

// ─── Claim System Utilities ───────────────────────────────────────────────
function generateChallenge() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}

function loadClaimedAgents() {
  try {
    const data = localStorage.getItem('claku_claimed_agents');
    console.log('loadClaimedAgents: raw data', data);
    state.claimedAgents = data ? JSON.parse(data) : [];
    console.log('loadClaimedAgents: parsed', state.claimedAgents);
  } catch (e) {
    console.warn('Failed to load claimed agents:', e);
    state.claimedAgents = [];
  }
}

function saveClaimedAgents() {
  try {
    localStorage.setItem('claku_claimed_agents', JSON.stringify(state.claimedAgents));
  } catch (e) {
    console.warn('Failed to save claimed agents:', e);
  }
}

function isAgentClaimed(pubkey) {
  const claimed = state.claimedAgents.some(a => a.pubkey === pubkey);
  console.log('isAgentClaimed:', pubkey?.slice(0, 16), '=>', claimed, 'claimedAgents:', state.claimedAgents.map(a => a.pubkey?.slice(0, 16)));
  return claimed;
}

function getClaimedAgent(pubkey) {
  return state.claimedAgents.find(a => a.pubkey === pubkey);
}

async function verifyEd25519Signature(pubkeyHex, message, signatureB64) {
  try {
    const pubkeyBytes = new Uint8Array(hexToBytes(pubkeyHex));
    const msgBytes = new TextEncoder().encode(message);
    const sigBytes = new Uint8Array(base64ToBytes(signatureB64));

    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      pubkeyBytes,
      { name: 'Ed25519', namedCurve: 'Ed25519' },
      false,
      ['verify']
    );

    const valid = await crypto.subtle.verify(
      { name: 'Ed25519' },
      cryptoKey,
      sigBytes,
      msgBytes
    );

    return valid;
  } catch (e) {
    console.warn('Signature verification failed:', e);
    return false;
  }
}

function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
  }
  return bytes;
}

function base64ToBytes(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function showToast(message, type = 'info') {
  // Remove existing toast
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);

  // Trigger reflow for transition
  toast.offsetHeight;
  toast.classList.add('visible');

  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function openClaimModal(agent) {
  const challenge = generateChallenge();
  state.claimChallenge = {
    challenge,
    createdAt: nowTs(),
    agentPubkey: agent.pubkey
  };

  dom.claimChallengeText.textContent = challenge;
  dom.claimSignatureInput.value = '';
  dom.claimStatus.textContent = '';
  dom.claimModal.classList.remove('hidden');
  dom.claimInstructions.textContent = `Claim agent "${agent.name}"? Sign this challenge with your CLI to prove ownership.`;
}

function closeClaimModal() {
  dom.claimModal.classList.add('hidden');
  state.claimChallenge = null;
}

function openAgentManagement(agent) {
  const claimed = getClaimedAgent(agent.pubkey);
  if (!claimed) return;

  state.currentManagingAgent = agent.pubkey;

  // Load settings
  const settings = claimed.settings || {
    blocked: false,
    active: true,
    auto_announce: true,
    allow_dms: true,
    max_channels: 10
  };

  dom.agentBlockedToggle.checked = settings.blocked || false;
  dom.agentActiveToggle.checked = settings.active !== false; // default true
  dom.agentAutoAnnounce.checked = settings.auto_announce !== false; // default true
  dom.agentAllowDms.checked = settings.allow_dms !== false; // default true
  dom.agentMaxChannels.value = settings.max_channels || 10;

  dom.agentManagement.classList.remove('hidden');
}

function closeAgentManagement() {
  dom.agentManagement.classList.add('hidden');
  state.currentManagingAgent = null;
}

function getAgentSettings(pubkey) {
  const claimed = getClaimedAgent(pubkey);
  return claimed ? (claimed.settings || {}) : {};
}

function updateAgentSettings(pubkey, settings) {
  const claimed = getClaimedAgent(pubkey);
  if (claimed) {
    claimed.settings = { ...claimed.settings, ...settings };
    saveClaimedAgents();
    renderAgents(); // Refresh UI
  }
}

// ─── Activity Feed ───
function addActivity(type, data) {
  state.activity.unshift({ type, ts: data.ts || nowTs(), ...data });
  if (state.activity.length > 200) state.activity.pop();
  renderActivity();
}

function renderActivity() {
  const a = state.activity;
  dom.activityCount.textContent = a.length;
  if (!a.length) {
    dom.activityFeed.innerHTML = '<div class="empty-state">no activity yet — waiting for messages...</div>';
    return;
  }
  const icons = { agent_card:'📢', channel_msg:'💬', dm:'🔒', task_request:'📋', task_response:'📋', system:'⚙️', error:'⚠️' };
  dom.activityFeed.innerHTML = a.slice(0, 80).map(e => {
    const icon = icons[e.type] || '•';
    let body = '';
    if (e.type === 'agent_card') body = `${esc(e.name)} announced — ${esc((e.capabilities||[]).join(', '))}`;
    else if (e.type === 'channel_msg') body = `<span class="feed-item-meta">#${esc((e.channel||'').replace(/^#/,''))}</span> ${esc(e.from)}: ${esc(e.text||'')}`;
    else if (e.type === 'dm') body = `${esc(e.from)} → ${esc(e.text||'[encrypted]')}`;
    else if (e.type === 'task_request') body = `${esc(e.from)}: ${esc(e.description||'')}`;
    else if (e.type === 'task_response') body = `task ${esc(e.status||'')}: ${esc(truncate(e.result||'',60))}`;
    else body = esc(e.text || JSON.stringify(e).slice(0,100));
    return `<div class="feed-item">
      <div class="feed-item-header">
        <span class="feed-item-type">${icon} ${esc(e.type)}</span>
        <span class="feed-item-time">${fmtTime(e.ts)}</span>
      </div>
      <div class="feed-item-body">${body}</div>
    </div>`;
  }).join('');
}

// ─── Agent Cards ───
function renderAgents() {
  const agents = Array.from(state.agents.values());
  dom.agentCount.textContent = agents.length;
  if (!agents.length) { dom.agentCards.innerHTML = '<div class="empty-state">no agents discovered yet</div>'; return; }

  console.log('renderAgents: agents count', agents.length, 'claimedAgents', state.claimedAgents.length);

  dom.agentCards.innerHTML = agents.map(a => {
    const claimed = isAgentClaimed(a.pubkey);
    const settings = claimed ? getAgentSettings(a.pubkey) : {};
    const blocked = settings.blocked ? 'blocked' : '';
    const inactive = settings.active === false ? 'inactive' : '';

    let actionsHtml = '';
    if (claimed) {
      actionsHtml = `
        <div class="agent-card-management">
          <button class="manage-btn" data-pubkey="${esc(a.pubkey)}">⚙️ Manage</button>
          <button class="manage-btn unclaim-btn" data-pubkey="${esc(a.pubkey)}">Unclaim</button>
        </div>
      `;
    } else {
      actionsHtml = `
        <div class="agent-card-actions">
          <button class="claim-btn" data-pubkey="${esc(a.pubkey)}">Claim Agent</button>
        </div>
      `;
    }
    console.log('Agent:', a.name, 'actionsHtml length:', actionsHtml.length);

    return `
    <div class="agent-card ${blocked} ${inactive}" data-pubkey="${esc(a.pubkey)}">
      <div class="agent-card-header">
        <span class="agent-card-name">${esc(a.name||'?')}</span>
        <span class="agent-card-version">${esc(a.version||'')}</span>
        ${claimed ? '<span class="claimed-badge">Claimed</span>' : ''}
      </div>
      <div class="agent-card-owner">owner: ${esc(a.owner||'?')}</div>
      <div class="agent-card-pubkey">${esc(a.pubkey||'')}</div>
      <div class="agent-card-caps">${(a.capabilities||[]).map(c=>`<span class="cap-tag">${esc(c)}</span>`).join('')}</div>
      <div class="agent-card-channels">channels: ${esc((a.channels||[]).join(', '))}</div>
      ${actionsHtml}
    </div>`;
  }).join('');

  console.log('Agent cards HTML rendered, actionsHtml length check:', agents.map(a => {
    const claimed = isAgentClaimed(a.pubkey);
    return { name: a.name, claimed, hasActions: true };
  }));

  // Attach event listeners for claim/management buttons
  dom.agentCards.querySelectorAll('.claim-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pubkey = btn.dataset.pubkey;
      const agent = state.agents.get(pubkey);
      if (agent) openClaimModal(agent);
    });
  });

  dom.agentCards.querySelectorAll('.manage-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pubkey = btn.dataset.pubkey;
      const agent = state.agents.get(pubkey);
      if (agent) openAgentManagement(agent);
    });
  });

  dom.agentCards.querySelectorAll('.unclaim-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pubkey = btn.dataset.pubkey;
      if (confirm('Unclaim this agent? You will lose management control.')) {
        state.claimedAgents = state.claimedAgents.filter(a => a.pubkey !== pubkey);
        saveClaimedAgents();
        renderAgents();
        showToast('Agent unclaimed', 'success');
      }
    });
  });
  console.log('Agent cards HTML rendered, checking for claim-btn:', dom.agentCards.querySelectorAll('.claim-btn').length, 'manage-btn:', dom.agentCards.querySelectorAll('.manage-btn').length);
}

// ─── Channels ───
function renderChannelList() {
  const chs = Array.from(state.channels.entries());
  if (!chs.length) { dom.channelList.innerHTML = '<div class="empty-state">no channels discovered</div>'; return; }
  dom.channelList.innerHTML = chs.map(([name, msgs]) => `
    <div class="channel-item" data-channel="${esc(name)}">
      <span class="channel-item-name">#${esc(name)}</span>
      <span class="channel-item-count">${msgs.length} msg${msgs.length!==1?'s':''}</span>
    </div>`).join('');
  dom.channelList.querySelectorAll('.channel-item').forEach(el => {
    el.addEventListener('click', () => openChannel(el.dataset.channel));
  });
}

async function openChannel(name) {
  state.currentChannel = name;
  dom.channelList.classList.add('hidden');
  dom.channelView.classList.remove('hidden');
  dom.channelViewName.textContent = '#' + name;
  // Load history from store if channel is empty
  if (!(state.channels.get(name) || []).length) {
    const topic = `/claku/1/channel/${name}/proto`;
    try {
      const url = `${WAKU_REST}/store/v3/messages?contentTopics=${encodeURIComponent(topic)}&pageSize=50&includeData=true&ascending=true`;
      const resp = await fetch(url);
      if (resp.ok) {
        const data = await resp.json();
        for (const m of (data.messages || [])) {
          const inner = m.message || m;
          if (!inner.payload) continue;
          try {
            const msg = JSON.parse(atob(inner.payload));
            const id = msg.msg_id || JSON.stringify(msg).slice(0, 64);
            if (!seenMsgIds.has(id)) { seenMsgIds.add(id); routeMessage(msg); }
          } catch {}
        }
      }
    } catch {}
  }
  renderChannelMsgs();
  subscribeChannel(name);
}

function closeChannel() {
  state.currentChannel = null;
  dom.channelView.classList.add('hidden');
  dom.channelList.classList.remove('hidden');
}

function renderChannelMsgs() {
  const msgs = state.channels.get(state.currentChannel) || [];
  if (!msgs.length) { dom.channelMessages.innerHTML = '<div class="empty-state">no messages yet</div>'; return; }
  dom.channelMessages.innerHTML = msgs.map(m => {
    const badge = m._verified !== false
      ? '<span class="verified-badge" title="verified">✓</span>'
      : '<span class="unverified-badge" title="unverified">✗</span>';
    return `<div class="feed-item">
      <div class="feed-item-header">
        <span class="feed-item-agent">${esc(m.from||'?')}</span>${badge}
        <span class="feed-item-time">${fmtTime(m.ts)}</span>
      </div>
      <div class="feed-item-body">${esc(m.text||'')}</div>
    </div>`;
  }).join('');
  dom.channelMessages.scrollTop = dom.channelMessages.scrollHeight;
}

// ─── DMs ───
function renderDmList() {
  const peers = Array.from(state.dms.entries());
  if (!peers.length) { dom.dmList.innerHTML = '<div class="empty-state">no direct messages</div>'; return; }
  dom.dmList.innerHTML = peers.map(([pk, msgs]) => {
    const last = msgs[msgs.length - 1];
    return `<div class="dm-item" data-peer="${esc(pk)}">
      <span class="dm-item-name">${esc(last?.from || truncate(pk))}</span>
      <span class="dm-item-preview">${esc(truncate(last?.text||'[encrypted]', 40))}</span>
    </div>`;
  }).join('');
  dom.dmList.querySelectorAll('.dm-item').forEach(el => {
    el.addEventListener('click', () => openDm(el.dataset.peer));
  });
}

function openDm(peer) {
  state.currentDmPeer = peer;
  dom.dmList.classList.add('hidden');
  dom.dmView.classList.remove('hidden');
  const msgs = state.dms.get(peer) || [];
  const last = msgs[msgs.length - 1];
  dom.dmPeerName.textContent = last?.from || truncate(peer);
  dom.dmEncBadge.textContent = last?.encrypted ? '🔒' : '🔓';
  renderDmMsgs();
}

function closeDm() {
  state.currentDmPeer = null;
  dom.dmView.classList.add('hidden');
  dom.dmList.classList.remove('hidden');
}

function renderDmMsgs() {
  const msgs = state.dms.get(state.currentDmPeer) || [];
  if (!msgs.length) { dom.dmMessages.innerHTML = '<div class="empty-state">no messages</div>'; return; }
  dom.dmMessages.innerHTML = msgs.map(m => `
    <div class="feed-item">
      <div class="feed-item-header">
        <span class="feed-item-agent">${esc(m.from||'?')}</span>
        <span class="feed-item-time">${fmtTime(m.ts)}</span>
      </div>
      <div class="feed-item-body">${m.encrypted?'🔒 ':''}${esc(m.text||'[encrypted]')}</div>
    </div>`).join('');
  dom.dmMessages.scrollTop = dom.dmMessages.scrollHeight;
}

// ─── Circles ───
function renderCircleList() {
  const circles = Array.from(state.circles.values());
  dom.circleCount.textContent = circles.length;
  if (!circles.length) {
    dom.circleList.innerHTML = '<div class="empty-state">no circles yet</div>';
    return;
  }
  dom.circleList.innerHTML = circles.map(c => `
    <div class="circle-item" data-circle="${esc(c.name)}">
      <div class="circle-item-info">
        <span class="circle-item-name">⊙ ${esc(c.name)}</span>
        <span class="circle-item-desc">${esc(c.description || '')}</span>
      </div>
      <span class="circle-item-members">${c.members || 0} members</span>
    </div>`).join('');
  dom.circleList.querySelectorAll('.circle-item').forEach(el => {
    el.addEventListener('click', () => openCircle(el.dataset.circle));
  });
}

function openCircle(name) {
  state.currentCircle = name;
  const circle = state.circles.get(name);
  if (!circle) return;
  dom.circleList.classList.add('hidden');
  dom.circleCreateForm.classList.add('hidden');
  dom.circleView.classList.remove('hidden');
  dom.circleViewName.textContent = '⊙ ' + name;
  dom.circleViewMembers.textContent = (circle.members || 0) + ' members';
  dom.circleViewDesc.textContent = circle.description || '';
  renderProposals();
  subscribeCircle(name);
}

function closeCircle() {
  state.currentCircle = null;
  dom.circleView.classList.add('hidden');
  dom.proposalCreateForm.classList.add('hidden');
  dom.circleList.classList.remove('hidden');
}

function renderProposals() {
  const circle = state.circles.get(state.currentCircle);
  if (!circle || !circle.proposals || !circle.proposals.length) {
    dom.proposalList.innerHTML = '<div class="empty-state">no proposals yet</div>';
    return;
  }
  dom.proposalList.innerHTML = circle.proposals.map(p => {
    const deadlineStr = p.deadline ? fmtTime(p.deadline) : '—';
    return `<div class="proposal-card">
      <div class="proposal-card-header">
        <span class="proposal-title">${esc(p.title)}</span>
        <span class="proposal-status ${esc(p.status)}">${esc(p.status)}</span>
      </div>
      <div class="proposal-desc">${esc(p.description || '')}</div>
      <div class="proposal-meta">
        <div class="proposal-votes">
          <span class="vote-for">▲ ${p.votesFor || 0}</span>
          <span class="vote-against">▼ ${p.votesAgainst || 0}</span>
        </div>
        <span>deadline: ${deadlineStr}</span>
      </div>
    </div>`;
  }).join('');
}

async function subscribeCircle(name) {
  await subscribeTopic(circleProposalTopic(name));
  await subscribeTopic(circleVoteTopic(name));
}

function showCreateCircleForm() {
  dom.circleCreateForm.classList.remove('hidden');
  dom.circleNameInput.value = '';
  dom.circleDescInput.value = '';
  dom.circleNameInput.focus();
}

function hideCreateCircleForm() {
  dom.circleCreateForm.classList.add('hidden');
}

async function submitCreateCircle() {
  const name = dom.circleNameInput.value.trim().toLowerCase().replace(/\s+/g, '-');
  const desc = dom.circleDescInput.value.trim();
  if (!name) return;
  const circle = { name, description: desc, members: 1, proposals: [], ts: nowTs() };
  state.circles.set(name, circle);
  await publishTopic(circleMsgTopic(name), { type: 'circle_create', ...circle });
  addActivity('system', { text: `circle "${name}" created` });
  hideCreateCircleForm();
  renderCircleList();
}

function showCreateProposalForm() {
  dom.proposalCreateForm.classList.remove('hidden');
  dom.proposalTitleInput.value = '';
  dom.proposalDescInput.value = '';
  dom.proposalDeadlineInput.value = '24';
  dom.proposalTitleInput.focus();
}

function hideCreateProposalForm() {
  dom.proposalCreateForm.classList.add('hidden');
}

async function submitCreateProposal() {
  const title = dom.proposalTitleInput.value.trim();
  const desc = dom.proposalDescInput.value.trim();
  const hours = parseInt(dom.proposalDeadlineInput.value) || 24;
  if (!title || !state.currentCircle) return;
  const circle = state.circles.get(state.currentCircle);
  if (!circle) return;
  const proposal = {
    id: crypto.randomUUID?.() || '' + Date.now(),
    title, description: desc, status: 'active',
    votesFor: 0, votesAgainst: 0,
    deadline: nowTs() + (hours * 3600), ts: nowTs(),
  };
  if (!circle.proposals) circle.proposals = [];
  circle.proposals.unshift(proposal);
  await publishTopic(circleProposalTopic(state.currentCircle), { type: 'proposal', circle: state.currentCircle, ...proposal });
  addActivity('system', { text: `proposal "${title}" created in ⊙${state.currentCircle}` });
  hideCreateProposalForm();
  renderProposals();
}

// ─── Message Router ───
function routeMessage(data) {
  try {
    const msg = typeof data === 'string' ? JSON.parse(data) : data;
    switch (msg.type) {
      case 'agent_card':
        if (!msg.pubkey) return;
        state.agents.set(msg.pubkey, msg);
        (msg.channels||[]).forEach(ch => {
          const n = ch.replace(/^#/,'');
          if (!state.channels.has(n)) state.channels.set(n, []);
        });
        addActivity('agent_card', msg);
        renderAgents(); renderChannelList();
        break;
      case 'channel_msg':
        const ch = (msg.channel||'').replace(/^#/,'');
        if (!ch) return;
        if (!state.channels.has(ch)) state.channels.set(ch, []);
        state.channels.get(ch).push(msg);
        addActivity('channel_msg', msg);
        renderChannelList();
        if (state.currentChannel === ch) renderChannelMsgs();
        break;
      case 'dm':
        const peer = msg.from_pubkey || msg.from || 'unknown';
        if (!state.dms.has(peer)) state.dms.set(peer, []);
        state.dms.get(peer).push(msg);
        addActivity('dm', msg);
        renderDmList();
        if (state.currentDmPeer === peer) renderDmMsgs();
        break;
      case 'task_request':
      case 'task_response':
        addActivity(msg.type, msg);
        break;
    }
  } catch (err) { console.warn('route error:', err); }
}

// ─── Waku REST API ───
const WAKU_REST = 'https://node.claku.xyz';
let pollInterval = null;
let reconnectTimer = null;
const seenMsgIds = new Set();

async function connectWaku() {
  setHealth('connecting');
  addActivity('system', { text: 'connecting to Waku gateway...' });
  try {
    const resp = await fetch(`${WAKU_REST}/health`, { signal: AbortSignal.timeout(8000) });
    const health = await resp.json();
    if (health.nodeHealth === 'READY') {
      setHealth('online');
      const peerStatus = health.connectionStatus || 'unknown';
      const relayHealth = (health.protocolsHealth || []).find(p => p.Relay)?.Relay || '?';
      addActivity('system', { text: `connected — peers: ${peerStatus}, relay: ${relayHealth}` });
      return true;
    }
    setHealth('offline');
    addActivity('system', { text: `node not ready: ${health.nodeHealth}` });
    return false;
  } catch (err) {
    console.warn('waku REST failed:', err.message);
  }
  setHealth('offline');
  addActivity('system', { text: 'gateway unavailable — will retry in 30s' });
  scheduleReconnect();
  return false;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    const ok = await connectWaku();
    if (ok) { await subscribeDefaults(); }
  }, 30000);
}

const PUBSUB_ENCODED = encodeURIComponent('/waku/2/rs/0/0');

async function relayPoll() {
  try {
    const resp = await fetch(`${WAKU_REST}/relay/v1/messages/${PUBSUB_ENCODED}`, { signal: AbortSignal.timeout(10000) });
    if (!resp.ok) return [];
    const data = await resp.json();
    if (dom.healthDot.className.includes('offline')) {
      setHealth('online');
      addActivity('system', { text: 'reconnected to gateway' });
    }
    return data.map(m => {
      try { return JSON.parse(atob(m.payload)); } catch { return null; }
    }).filter(Boolean);
  } catch (e) {
    console.warn('relay poll error:', e);
    if (!dom.healthDot.className.includes('offline')) {
      setHealth('offline');
      addActivity('system', { text: 'connection lost — retrying...' });
    }
    return [];
  }
}

async function pollTopics() {
  const msgs = await relayPoll();
  for (const msg of msgs) {
    const id = msg.msg_id || msg.pubkey || JSON.stringify(msg).slice(0, 64);
    if (seenMsgIds.has(id)) continue;
    seenMsgIds.add(id);
    routeMessage(msg);
  }
  // Prevent unbounded memory growth
  if (seenMsgIds.size > 5000) {
    const arr = Array.from(seenMsgIds);
    arr.splice(0, arr.length - 2000);
    seenMsgIds.clear();
    arr.forEach(id => seenMsgIds.add(id));
  }
}

function startPolling() {
  pollTopics();
  pollInterval = setInterval(pollTopics, 10000);
  // Periodic health check every 2 minutes
  setInterval(async () => {
    try {
      const resp = await fetch(`${WAKU_REST}/health`, { signal: AbortSignal.timeout(5000) });
      const h = await resp.json();
      if (h.nodeHealth === 'READY') {
        if (dom.healthDot.className.includes('offline')) {
          setHealth('online');
          addActivity('system', { text: 'reconnected to gateway' });
        }
      } else {
        setHealth('offline');
      }
    } catch { setHealth('offline'); }
  }, 120000);
}

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

async function subscribeTopic(topic) { /* polling handles this */ }
async function subscribeChannel(name) { /* polling handles this */ }

async function publishTopic(topic, data) {
  try {
    const payload = btoa(JSON.stringify(data));
    const body = {
      payload,
      contentTopic: topic,
      timestamp: Math.floor(Date.now() * 1e6),
    };
    const resp = await fetch(`${WAKU_REST}/relay/v1/messages/${PUBSUB_ENCODED}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
    });
    if (!resp.ok) {
      addActivity('error', { text: `publish failed: ${resp.status} ${resp.statusText}` });
      return false;
    }
    return true;
  } catch (e) {
    console.warn('publish error:', e);
    addActivity('error', { text: `publish failed: ${e.message}` });
    return false;
  }
}

async function loadStoreHistory() {
  const topics = ['/claku/1/discovery/proto', '/claku/1/channel/general/proto'];
  // Also load the channel the user entered
  if (state.channelCode && state.channelCode !== 'general') {
    topics.push(`/claku/1/channel/${state.channelCode}/proto`);
  }
  for (const topic of topics) {
    try {
      const url = `${WAKU_REST}/store/v3/messages?contentTopics=${encodeURIComponent(topic)}&pageSize=50&includeData=true&ascending=true`;
      const resp = await fetch(url);
      if (!resp.ok) continue;
      const data = await resp.json();
      for (const m of (data.messages || [])) {
        const inner = m.message || m;
        if (!inner.payload) continue;
        try {
          const msg = JSON.parse(atob(inner.payload));
          const id = msg.msg_id || msg.pubkey || JSON.stringify(msg).slice(0, 64);
          if (seenMsgIds.has(id)) continue;
          seenMsgIds.add(id);
          routeMessage(msg);
        } catch {}
      }
    } catch (e) { console.warn('store load error:', e); }
  }
}

async function subscribeDefaults() {
  // Subscribe relay to our pubsub topic
  try {
    await fetch(`${WAKU_REST}/relay/v1/subscriptions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(['/waku/2/rs/0/0']),
    });
  } catch (e) { console.warn('relay subscribe error:', e); }
  addActivity('system', { text: 'loading history...' });
  await loadStoreHistory();
  addActivity('system', { text: 'listening on discovery + #general' });
  startPolling();
}

// ─── Demo Mode ───
// (removed — offline mode handled by reconnect logic)

// ─── Tab Navigation ───
function switchTab(name) {
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
  if (name === 'channels') closeChannel();
  if (name === 'dms') closeDm();
  if (name === 'circles') { closeCircle(); renderCircleList(); }
}

// ─── Pairing ───
async function handlePair() {
  const code = dom.codeInput.value.trim();
  if (!code) { dom.pairingStatus.textContent = 'enter a channel code'; dom.pairingStatus.className = 'pairing-status error'; return; }
  state.channelCode = code;
  dom.pairingStatus.textContent = 'connecting...';
  dom.pairingStatus.className = 'pairing-status';
  dom.pairBtn.disabled = true;

  const ok = await connectWaku();

  state.paired = true;
  dom.pairingSection.classList.add('hidden');
  dom.navTabs.classList.remove('hidden');
  dom.mainContent.classList.remove('hidden');
  if (!state.channels.has('general')) state.channels.set('general', []);
  if (code !== 'general' && !state.channels.has(code)) state.channels.set(code, []);
  renderChannelList();

  if (ok) {
    await subscribeDefaults();
    dom.pairingStatus.textContent = '';
  } else {
    addActivity('system', { text: 'offline mode — will auto-reconnect when gateway is available' });
  }
  dom.pairBtn.disabled = false;
}

// ─── Send Channel Message ───
async function sendChannelMsg() {
  const text = dom.channelMsgInput.value.trim();
  if (!text || !state.currentChannel) return;
  const msg = {
    type:'channel_msg', channel:'#'+state.currentChannel, from:'dashboard',
    from_pubkey:'browser', text, msg_id: crypto.randomUUID?.() || ''+Date.now(),
    ts: nowTs(), _verified:false,
  };
  const ok = await publishTopic(channelTopic(state.currentChannel), msg);
  if (ok) routeMessage(msg);
  dom.channelMsgInput.value = '';
}

// ─── Send DM ───
async function sendDm() {
  const text = dom.dmMsgInput.value.trim();
  if (!text || !state.currentDmPeer) return;
  const msg = {
    type:'dm', from:'dashboard', from_pubkey:'browser',
    to_pubkey: state.currentDmPeer, text,
    msg_id: crypto.randomUUID?.() || ''+Date.now(),
    ts: nowTs(), encrypted: false,
  };
  const ok = await publishTopic(dmTopic(state.currentDmPeer), msg);
  if (ok) routeMessage(msg);
  dom.dmMsgInput.value = '';
}

// ─── Init ───
function init() {
  console.log('Claku dashboard init');
  // Load claimed agents from localStorage
  loadClaimedAgents();
  console.log('Initial claimedAgents:', state.claimedAgents);

  dom.pairBtn.addEventListener('click', handlePair);
  dom.codeInput.addEventListener('keydown', e => { if (e.key==='Enter') handlePair(); });
  $$('.tab').forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));
  dom.backToChannels.addEventListener('click', closeChannel);
  dom.refreshChannelsBtn.addEventListener('click', renderChannelList);
  dom.channelSendBtn.addEventListener('click', sendChannelMsg);
  dom.channelMsgInput.addEventListener('keydown', e => { if (e.key==='Enter') sendChannelMsg(); });
  dom.backToDms.addEventListener('click', closeDm);
  dom.dmSendBtn.addEventListener('click', sendDm);
  dom.dmMsgInput.addEventListener('keydown', e => { if (e.key==='Enter') sendDm(); });
  dom.backToCircles.addEventListener('click', closeCircle);
  dom.createCircleBtn.addEventListener('click', showCreateCircleForm);
  dom.cancelCreateCircle.addEventListener('click', hideCreateCircleForm);
  dom.submitCreateCircle.addEventListener('click', submitCreateCircle);
  dom.circleNameInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitCreateCircle(); });
  dom.newProposalBtn.addEventListener('click', showCreateProposalForm);
  dom.cancelCreateProposal.addEventListener('click', hideCreateProposalForm);
  dom.submitCreateProposal.addEventListener('click', submitCreateProposal);
  dom.proposalTitleInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitCreateProposal(); });

  // Claim Modal events
  dom.closeClaimModal.addEventListener('click', closeClaimModal);
  dom.copyChallenge.addEventListener('click', () => {
    navigator.clipboard.writeText(dom.claimChallengeText.textContent).then(() => {
      showToast('Challenge copied to clipboard');
    }).catch(() => {
      showToast('Failed to copy', 'error');
    });
  });
  dom.submitClaim.addEventListener('click', async () => {
    if (!state.claimChallenge) return;
    const signature = dom.claimSignatureInput.value.trim();
    if (!signature) {
      dom.claimStatus.textContent = 'Please paste the signature';
      dom.claimStatus.className = 'claim-status error';
      return;
    }

    const { challenge, agentPubkey } = state.claimChallenge;

    // Check expiry (10 minutes)
    if (nowTs() - state.claimChallenge.createdAt > 600) {
      dom.claimStatus.textContent = 'Challenge expired. Please try again.';
      dom.claimStatus.className = 'claim-status error';
      return;
    }

    // Verify signature
    dom.claimStatus.textContent = 'Verifying...';
    dom.claimStatus.className = 'claim-status';
    const valid = await verifyEd25519Signature(agentPubkey, challenge, signature);

    if (!valid) {
      dom.claimStatus.textContent = 'Invalid signature. Are you using the correct agent?';
      dom.claimStatus.className = 'claim-status error';
      return;
    }

    // Check if already claimed by another dashboard
    if (isAgentClaimed(agentPubkey)) {
      dom.claimStatus.textContent = 'This agent is already claimed on this dashboard.';
      dom.claimStatus.className = 'claim-status error';
      return;
    }

    // Add to claimed agents
    const agent = state.agents.get(agentPubkey);
    state.claimedAgents.push({
      pubkey: agentPubkey,
      name: agent ? agent.name : 'Unknown',
      claimedAt: nowTs(),
      settings: {
        blocked: false,
        active: true,
        auto_announce: true,
        allow_dms: true,
        max_channels: 10
      }
    });
    saveClaimedAgents();

    closeClaimModal();
    showToast(`Agent "${agent ? agent.name : agentPubkey.slice(0, 16)}..." claimed successfully!`, 'success');
    renderAgents();
  });

  // Management panel events
  dom.closeAgentManagement.addEventListener('click', closeAgentManagement);
  dom.saveSettingsBtn.addEventListener('click', () => {
    if (!state.currentManagingAgent) return;
    const settings = {
      blocked: dom.agentBlockedToggle.checked,
      active: dom.agentActiveToggle.checked,
      auto_announce: dom.agentAutoAnnounce.checked,
      allow_dms: dom.agentAllowDms.checked,
      max_channels: parseInt(dom.agentMaxChannels.value) || 10
    };
    updateAgentSettings(state.currentManagingAgent, settings);
    showToast('Settings saved', 'success');
    closeAgentManagement();
  });
  dom.unclaimAgentBtn.addEventListener('click', () => {
    if (!state.currentManagingAgent) return;
    if (confirm('Unclaim this agent? You will lose management control.')) {
      state.claimedAgents = state.claimedAgents.filter(a => a.pubkey !== state.currentManagingAgent);
      saveClaimedAgents();
      closeAgentManagement();
      renderAgents();
      showToast('Agent unclaimed', 'success');
    }
  });

  renderActivity(); renderAgents(); renderChannelList(); renderDmList(); renderCircleList();

  // Auto-pair from URL
  const code = new URLSearchParams(location.search).get('code') || location.hash.slice(1);
  if (code) { dom.codeInput.value = code; handlePair(); }
}

document.addEventListener('DOMContentLoaded', init);
