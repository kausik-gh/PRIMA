"""
frontend/threejs_graph.py

Two-graph system:
  Graph 1 — Full Network  (all nodes, behaviour-driven suspicion, fraud cluster pull)
  Graph 2 — Attack Replay (fraud nodes + sequential transaction replay)

ARCHITECTURE:
  * Every observed transaction → tickSuspicion() builds local scores from 0
  * suspicionScore > T1 (35) → early warning (yellow)
  * suspicionScore > T2 (70) → fraud (red, locally detected)
  * Backend is_fraud=1 also marks fraud (from triggered attacks)
  * Early warning HUD starts at 0, grows from observed behaviour
  * New account created every 10 s via POST /create_account
  * "New Account" popup fades out over 2.5 s
  * Fraud nodes gravitationally pulled into right-side cluster
  * Graph 2: nodes only initially, "VIEW TRANSACTION FLOW" replays sequentially
"""

import json
import hashlib
import streamlit.components.v1 as components


def _stable_pos(account_id: str, spread_x: float = 1400.0, spread_y: float = 900.0):
    h = hashlib.md5(str(account_id).encode()).hexdigest()
    x = spread_x * 0.08 + (int(h[0:4], 16) / 65535.0) * spread_x * 0.84
    y = spread_y * 0.08 + (int(h[4:8], 16) / 65535.0) * spread_y * 0.84
    return round(x, 1), round(y, 1)


def render_network_graph(
    accounts_df=None,
    fraud_ids=None,
    early_ids=None,
    banned_ids=None,
    suspicious_txs=None,
    attack_name=None,
    height=720,
    api_url="http://127.0.0.1:8088",
    trigger_siren: bool = False,
):
    fraud_ids      = [str(f) for f in (fraud_ids  or [])]
    early_ids      = [str(f) for f in (early_ids  or [])]
    banned_ids     = [str(f) for f in (banned_ids or [])]
    suspicious_txs = suspicious_txs or []

    nodes_data = []
    if accounts_df is not None:
        for _, row in accounts_df.iterrows():
            acc_id    = str(row["account_id"])
            is_active = row.get("is_active", True)
            # Banned nodes: render grey in place — never skip
            if not is_active or acc_id in banned_ids:
                x, y = _stable_pos(acc_id)
                nodes_data.append({"id": acc_id, "status": "banned", "x": x, "y": y})
                continue
            # early_ids ignored — early warning grows organically from JS only
            if acc_id in fraud_ids: status = "fraud"
            else:                   status = "normal"
            x, y = _stable_pos(acc_id)
            nodes_data.append({"id": acc_id, "status": status, "x": x, "y": y})

    sus_panel = [{
        "sender":   str(t.get("sender",   "?")),
        "receiver": str(t.get("receiver", "?")),
        "amount":   round(float(t.get("amount", 0)), 2),
        "channel":  str(t.get("channel",  "TXN")),
    } for t in suspicious_txs]

    attack_label     = (attack_name or "").upper()
    nodes_json       = json.dumps(nodes_data)
    fraud_json       = json.dumps(fraud_ids)
    early_json       = json.dumps(early_ids)
    banned_json      = json.dumps(banned_ids)
    sus_json         = json.dumps(sus_panel)
    trigger_siren_js = "true" if trigger_siren else "false"

    # --- Build HTML ---
    # We build it as a concatenation so we can safely inject Python JSON
    # without worrying about f-string / triple-quote collisions.
    html_head = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:100%;height:100%;overflow:hidden;background:#04080f;
  font-family:'Share Tech Mono',monospace;}

#wrap{position:relative;width:100%;height:640px;}
#mainCanvas{display:block;width:100%;height:640px;cursor:grab;
  image-rendering:crisp-edges;}
#mainCanvas:active{cursor:grabbing;}
#scanlines{position:absolute;inset:0;pointer-events:none;z-index:2;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,
  rgba(0,0,0,0.03) 2px,rgba(0,0,0,0.03) 4px);}
#flashOverlay{position:absolute;inset:0;background:rgba(255,0,0,0);
  pointer-events:none;z-index:6;}

#hud{position:absolute;top:10px;left:12px;pointer-events:none;z-index:4;}
#hudTitle{font-size:10px;font-weight:bold;letter-spacing:2.5px;color:#00ffcc;
  text-shadow:0 0 10px rgba(0,255,204,0.5);margin-bottom:8px;}
#hudTable{font-size:9px;line-height:2.1;color:#334466;
  text-transform:uppercase;letter-spacing:1px;}
#hudTable b{font-size:11px;letter-spacing:0;}
.hv-tps{color:#00ff99;}.hv-tx{color:#1a9fff;}.hv-acc{color:#1a9fff;}
.hv-fr{color:#ff2244;}.hv-ew{color:#ffaa00;}.hv-ban{color:#556677;}

#zoomBadge{position:absolute;bottom:80px;left:12px;font-size:8px;
  letter-spacing:1.5px;color:#334466;pointer-events:none;z-index:4;}
#apiSt{position:absolute;bottom:62px;left:12px;font-size:8px;
  letter-spacing:1.5px;color:#334466;pointer-events:none;z-index:4;}

#btnFlow{position:absolute;bottom:12px;left:12px;z-index:5;
  background:rgba(4,8,20,0.9);border:1px solid rgba(26,100,60,0.5);
  color:#00cc66;font-family:'Share Tech Mono',monospace;font-size:8px;
  letter-spacing:1.5px;padding:5px 12px;cursor:pointer;
  text-transform:uppercase;transition:all 0.2s;}
#btnFlow:hover{border-color:#00ff88;color:#00ff88;
  box-shadow:0 0 8px rgba(0,255,136,0.2);}
#btnFlow.active{border-color:#ff6600;color:#ff6600;
  box-shadow:0 0 8px rgba(255,102,0,0.3);}
#btnFlow:disabled{opacity:0.3;cursor:default;}

#attackBadge{display:none;position:absolute;top:12px;left:50%;
  transform:translateX(-50%);z-index:5;pointer-events:none;
  border:1px solid rgba(255,50,20,0.7);background:rgba(255,20,0,0.12);
  padding:7px 24px 5px 24px;text-align:center;}
#attackTitle{font-size:10px;font-weight:bold;letter-spacing:3px;
  color:#ff4422;text-transform:uppercase;animation:bp 1.4s infinite;}
#attackSub{font-size:8px;color:#882211;margin-top:3px;letter-spacing:1px;}
@keyframes bp{0%,100%{opacity:1}50%{opacity:0.4}}

#rPanel{position:absolute;top:10px;right:12px;width:240px;
  display:flex;flex-direction:column;gap:7px;pointer-events:none;z-index:4;}
.rbox{background:rgba(4,8,20,0.88);border:1px solid rgba(26,60,100,0.3);
  padding:8px 10px;}
.rtitle{font-size:8px;letter-spacing:2px;text-transform:uppercase;
  color:#1a3344;margin-bottom:5px;
  border-bottom:1px solid rgba(26,60,100,0.2);padding-bottom:3px;}
#txFeed{max-height:195px;overflow:hidden;}
.tx-row{display:flex;justify-content:space-between;font-size:9px;
  padding:2px 0;opacity:0;transition:opacity 0.3s;color:#223344;}
.tx-row.vis{opacity:1;}
.tx-row .ta{color:#1155cc;}
.tx-row.atk .ta{color:#ff3311;}
.tx-row.atk span:first-child{color:#ff5533;}
#susBox{display:none;border-color:rgba(255,40,10,0.35)!important;}
#susBox.on{display:block;}
.stitle{color:#ff3322!important;border-color:rgba(255,40,10,0.3)!important;}
#susFeed{max-height:185px;overflow-y:auto;}
#susFeed::-webkit-scrollbar{width:2px;}
#susFeed::-webkit-scrollbar-thumb{background:#ff2200;}
.srow{font-size:9px;padding:3px 0;
  border-bottom:1px solid rgba(255,30,0,0.1);}
.sacc{color:#ff4422;}.smeta{color:#661100;font-size:8px;}

#tip{position:absolute;display:none;background:rgba(4,8,24,0.95);
  border:1px solid rgba(60,100,180,0.4);padding:5px 10px;font-size:9px;
  color:#88aacc;pointer-events:none;line-height:1.9;z-index:10;
  white-space:nowrap;}

#legend{position:absolute;bottom:10px;right:12px;font-size:8.5px;
  color:#334466;pointer-events:none;z-index:4;
  display:flex;gap:14px;align-items:center;}
.leg{display:flex;align-items:center;gap:4px;}
.ldot{width:8px;height:8px;border-radius:50%;}

#divider{width:100%;height:1px;
  background:linear-gradient(90deg,transparent,#0d3355,transparent);}

#g2wrap{width:100%;background:#020610;position:relative;}
#g2hdr{padding:8px 16px 6px;display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;}
#g2label{font-size:9px;font-weight:bold;letter-spacing:2px;
  text-transform:uppercase;color:#ff3311;}
#g2stats{font-size:8px;color:#332211;letter-spacing:1px;}
#btnReplay{background:rgba(4,8,20,0.9);border:1px solid rgba(255,80,20,0.4);
  color:#ff6633;font-family:'Share Tech Mono',monospace;font-size:8px;
  letter-spacing:1.5px;padding:4px 14px;cursor:pointer;
  text-transform:uppercase;transition:all 0.2s;margin-left:auto;}
#btnReplay:hover:not(:disabled){border-color:#ff8844;color:#ff8844;
  box-shadow:0 0 8px rgba(255,120,0,0.25);}
#btnReplay.replaying{border-color:#ffaa00;color:#ffaa00;
  box-shadow:0 0 8px rgba(255,170,0,0.3);}
#btnReplay:disabled{opacity:0.25;cursor:default;}
#g2Canvas{display:block;width:100%;height:320px;image-rendering:crisp-edges;}
#noFraud{display:none;padding:50px;text-align:center;font-size:10px;
  letter-spacing:2px;text-transform:uppercase;color:#0d1a22;}
#replayStatus{font-size:8px;color:#443322;letter-spacing:1px;
  padding:0 16px 6px;min-height:14px;}
</style>
</head>
<body>
<div id="wrap">
  <canvas id="mainCanvas"></canvas>
  <div id="scanlines"></div>
  <div id="flashOverlay"></div>
  <div id="hud">
    <div id="hudTitle">&#9670; CROSS-CHANNEL MULE MONITOR</div>
    <div id="hudTable">
      TPS &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b class="hv-tps" id="hTps">&#8212;</b><br>
      TX COUNT &nbsp;&nbsp; <b class="hv-tx"  id="hTx">&#8212;</b><br>
      ACTIVE ACC &nbsp;<b class="hv-acc" id="hAcc">&#8212;</b><br>
      FRAUD &nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b class="hv-fr"  id="hFr">0</b><br>
      EARLY WARN &nbsp;<b class="hv-ew"  id="hEw">0</b><br>
      BANNED &nbsp;&nbsp;&nbsp;&nbsp; <b class="hv-ban" id="hBan">&#8212;</b>
    </div>
  </div>
  <div id="zoomBadge">ZOOM: <span id="zoomVal">1.00</span>x
    &nbsp;&#183;&nbsp; <span id="zoomLevel">NETWORK</span></div>
  <div id="apiSt">&#9679; CONNECTING...</div>
  <button id="btnFlow" disabled>SHOW TRANSACTION FLOW</button>
  <div id="attackBadge">
    <div id="attackTitle">&#9888; ATTACK DETECTED</div>
    <div id="attackSub"></div>
  </div>
  <div id="rPanel">
    <div class="rbox">
      <div class="rtitle">Live Transactions</div>
      <div id="txFeed"></div>
    </div>
    <div class="rbox" id="susBox">
      <div class="rtitle stitle">&#9888; Suspicious TX</div>
      <div id="susFeed"></div>
    </div>
  </div>
  <div id="tip"></div>
  <div id="legend">
    <div class="leg"><div class="ldot" style="background:#1a6fff"></div>Normal</div>
    <div class="leg"><div class="ldot" style="background:#ffaa00"></div>Early Warning</div>
    <div class="leg"><div class="ldot" style="background:#ff2244"></div>Fraud</div>
    <div class="leg"><div class="ldot" style="background:#00ff88"></div>New</div>
  </div>
</div>
<div id="divider"></div>
<div id="g2wrap">
  <div id="g2hdr">
    <span id="g2label">&#9888; ATTACK SUBGRAPH &#8212; FRAUD NETWORK</span>
    <span id="g2stats">No attack detected yet</span>
    <button id="btnReplay" disabled>&#9654; VIEW TRANSACTION FLOW</button>
  </div>
  <div id="replayStatus"></div>
  <canvas id="g2Canvas"></canvas>
  <div id="noFraud">No fraud detected yet &#8212; trigger an attack to see replay</div>
</div>
<script>
"""

    html_consts = (
        "const API           = " + json.dumps(api_url) + ";\n"
        "const NODES_INIT    = " + nodes_json + ";\n"
        "const FRAUD_IDS     = new Set(" + fraud_json + ");\n"
        "const EARLY_IDS     = new Set(" + early_json + ");\n"
        "const BANNED_IDS    = new Set(" + banned_json + ");\n"
        "const SUS_DATA      = " + sus_json + ";\n"
        "const TRIGGER_SIREN = " + trigger_siren_js + ";\n"
    )

    html_body = """
const NORMAL_EDGE_MAX  = 20;
const NORMAL_EDGE_LIFE = 3000;
const ATTACK_EDGE_MAX  = 15;
const ATTACK_EDGE_LIFE = 5000;
const SUSP_T1 = 35;
const SUSP_T2 = 70;

// ── Siren ─────────────────────────────────────────────────────────
let _audioCtx    = null;
let _sirenAt     = 0;   // timestamp of last siren — 15s cooldown

function playSiren(){
  var now = Date.now();
  if(now - _sirenAt < 15000) return;
  _sirenAt = now;
  try{
    if(!_audioCtx) _audioCtx = new(window.AudioContext||window.webkitAudioContext)();
    const dur=2.8, osc=_audioCtx.createOscillator(), g=_audioCtx.createGain();
    osc.connect(g); g.connect(_audioCtx.destination);
    osc.type='sawtooth';
    g.gain.setValueAtTime(0.07, _audioCtx.currentTime);
    g.gain.linearRampToValueAtTime(0, _audioCtx.currentTime+dur);
    for(let i=0;i<4;i++){
      osc.frequency.setValueAtTime(380+i*10, _audioCtx.currentTime+i*0.4);
      osc.frequency.linearRampToValueAtTime(900, _audioCtx.currentTime+i*0.4+0.2);
    }
    osc.start(); osc.stop(_audioCtx.currentTime+dur);
  }catch(e){}
}

var _flashAt = 0;
function flashRed(){
  var now = Date.now();
  if(now - _flashAt < 10000) return;
  _flashAt = now;
  const ov  = document.getElementById('flashOverlay');
  let start = null;
  (function frame(ts){
    if(!start) start=ts;
    const el = ts-start;
    const a  = el<200?0.45:el<1400?0.45*(1-(el-200)/1200):0;
    ov.style.background = 'rgba(255,0,0,'+a+')';
    if(el<1400) requestAnimationFrame(frame);
    else ov.style.background='rgba(255,0,0,0)';
  })(0);
  playSiren();
  document.getElementById('attackBadge').style.display='block';
}

// ═══════════════════════════════════════════════════════
// GRAPH 1
// ═══════════════════════════════════════════════════════
(function(){
  var wrap   = document.getElementById('wrap');
  var canvas = document.getElementById('mainCanvas');
  var dpr    = window.devicePixelRatio || 1;
  var W      = wrap.clientWidth || 1200;
  var H      = 640;
  canvas.width  = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';
  var ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  var WORLD_W = 1400, WORLD_H = 900;
  // Node positions are in world space. panX/panY/zoom map world→screen.
  // Initial view: fit the world into the canvas.
  var zoom = Math.min(W / WORLD_W, H / WORLD_H) * 0.90;
  var panX = (W - WORLD_W * zoom) / 2;
  var panY = (H - WORLD_H * zoom) / 2;

  var nodeMap  = {};
  var nodeList = [];

  function makeNode(id, status, wx, wy){
    return {
      id: id, status: status,
      wx: wx, wy: wy, sx: 0, sy: 0,
      pulse:          Math.random() * Math.PI * 2,
      suspicion:      0,
      outCount:       0,
      inCount:        0,
      receivers:      {},
      senders:        {},
      receiverCount:  0,
      senderCount:    0,
      createdAt:      Date.now(),
      newAccountPopup: 0,
    };
  }

  NODES_INIT.forEach(function(n){
    var node = makeNode(n.id, n.status, n.x, n.y);
    if(n.status === 'fraud')  node.suspicion = 100;
    // early warning starts at 0 — grows from observed transactions only
    // banned nodes: keep at position, no suspicion
    nodeMap[n.id] = node;
    nodeList.push(node);
  });

  var isDragging = false, lastMx = 0, lastMy = 0;
  var mouseScreenX = -9999, mouseScreenY = -9999;

  canvas.addEventListener('wheel', function(e){
    e.preventDefault();
    var factor  = e.deltaY < 0 ? 1.12 : 0.89;
    var newZoom = Math.max(0.25, Math.min(10, zoom * factor));
    var rect    = canvas.getBoundingClientRect();
    var mx      = e.clientX - rect.left;
    var my      = e.clientY - rect.top;
    panX = mx - (mx - panX) * (newZoom / zoom);
    panY = my - (my - panY) * (newZoom / zoom);
    zoom = newZoom;
    updateZoomBadge();
  }, {passive: false});

  canvas.addEventListener('mousedown', function(e){
    isDragging=true; lastMx=e.clientX; lastMy=e.clientY;
    canvas.style.cursor='grabbing';
  });
  window.addEventListener('mouseup', function(){ isDragging=false; canvas.style.cursor='grab'; });
  window.addEventListener('mousemove', function(e){
    if(isDragging){
      panX += e.clientX - lastMx;
      panY += e.clientY - lastMy;
      lastMx = e.clientX; lastMy = e.clientY;
    }
    var rect    = canvas.getBoundingClientRect();
    mouseScreenX  = e.clientX - rect.left;
    mouseScreenY  = e.clientY - rect.top;
  });

  function updateZoomBadge(){
    document.getElementById('zoomVal').textContent = zoom.toFixed(2);
    document.getElementById('zoomLevel').textContent =
      zoom < 0.5 ? 'OVERVIEW' : zoom < 1.5 ? 'NETWORK' :
      zoom < 4   ? 'DETAIL'   : 'CLOSE-UP';
  }
  updateZoomBadge();

  function zoomToFraudCluster(fraudNodes, duration){
    duration = duration || 1100;
    if(!fraudNodes || fraudNodes.length === 0) return;
    var wxs  = fraudNodes.map(function(n){ return n.wx; });
    var wys  = fraudNodes.map(function(n){ return n.wy; });
    var minX = Math.min.apply(null, wxs), maxX = Math.max.apply(null, wxs);
    var minY = Math.min.apply(null, wys), maxY = Math.max.apply(null, wys);
    var padX = Math.max(50, (maxX - minX) * 0.25);
    var padY = Math.max(50, (maxY - minY) * 0.25);
    var bw   = Math.max(1, maxX - minX) + padX * 2;
    var bh   = Math.max(1, maxY - minY) + padY * 2;
    var tZoom= Math.max(2.5, Math.min(7, Math.min(W/bw, H/bh)));
    var cx   = (minX + maxX) / 2;
    var cy   = (minY + maxY) / 2;
    var tPanX= W/2 - cx*tZoom;
    var tPanY= H/2 - cy*tZoom;
    var sZoom= zoom, sPanX = panX, sPanY = panY;
    var t0   = performance.now();
    function step(now){
      var progress = Math.min(1,(now-t0)/duration);
      var ease     = 1 - Math.pow(1-progress, 3);
      zoom = sZoom + (tZoom-sZoom)*ease;
      panX = sPanX + (tPanX-sPanX)*ease;
      panY = sPanY + (tPanY-sPanY)*ease;
      updateZoomBadge();
      if(progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function nodeColor(n){
    if(n.status === 'fraud')         return '#ff2244';
    if(n.status === 'early')         return '#ffaa00';
    if(n.status === 'banned')        return '#445566';
    if(n.newAccountPopup > 0)        return '#00ff88';
    return '#1a6fff';
  }

  function getNodeRadius(){
    return Math.max(4, Math.min(20, 6 * Math.sqrt(zoom)));
  }

  function computeScreenPositions(){
    nodeList.forEach(function(n){
      n.sx = n.wx * zoom + panX;
      n.sy = n.wy * zoom + panY;
    });
  }

  function applyCollision(r){
    var minDist  = r * 2 + 2;
    var minDist2 = minDist * minDist;
    var sorted   = nodeList.slice().sort(function(a,b){ return a.sx - b.sx; });
    for(var pass = 0; pass < 2; pass++){
      for(var i = 0; i < sorted.length; i++){
        var a = sorted[i];
        for(var j = i+1; j < sorted.length; j++){
          var b  = sorted[j];
          var dx = b.sx - a.sx;
          if(dx >= minDist) break;
          var dy = b.sy - a.sy;
          if(Math.abs(dy) >= minDist) continue;
          var d2 = dx*dx + dy*dy;
          if(d2 > 0 && d2 < minDist2){
            var dist = Math.sqrt(d2);
            var push = (minDist - dist) * 0.5;
            var ux = dx/dist, uy = dy/dist;
            a.sx -= ux*push; a.sy -= uy*push;
            b.sx += ux*push; b.sy += uy*push;
          }
        }
      }
    }
  }

  var attackPhase = false;  // true during/after attack — hides normal edges

  function updateFlowButton(){
    document.getElementById('btnFlow').disabled =
      !nodeList.some(function(n){ return n.status === 'fraud'; });
  }

  var edges = [];

  function drawEdges(r){
    var now       = Date.now();
    var baseAlpha = Math.min(0.65, zoom / 2);
    var lineW     = zoom > 2 ? 1.5 : 0.5;

    for(var i = edges.length-1; i >= 0; i--){
      var e    = edges[i];
      var life = e.life || NORMAL_EDGE_LIFE;
      var age  = now - e.createdAt;
      if(age > life){ edges.splice(i,1); continue; }

      // During attack: skip normal edges so focus stays on red ones
      if(attackPhase && !e.isSus) continue;

      var sn = nodeMap[e.senderId];
      var rn = nodeMap[e.receiverId];
      if(!sn || !rn) continue;
      if(sn.status === 'banned' || rn.status === 'banned') continue;

      var fade  = age > life-1200 ? 1-(age-(life-1200))/1200 : 1;
      var alpha = (e.isSus ? 0.88 : baseAlpha * 0.6) * fade;
      if(alpha < 0.02) continue;

      var lw = e.isSus ? lineW * 1.6 : lineW;

      // Glow pass
      ctx.save();
      ctx.globalAlpha = alpha * 0.28;
      ctx.shadowColor = e.isSus ? '#ff1100' : '#002299';
      ctx.shadowBlur  = 14;
      ctx.strokeStyle = e.isSus ? '#ff3311' : '#1a4488';
      ctx.lineWidth   = lw * 3.5;
      ctx.beginPath(); ctx.moveTo(sn.sx, sn.sy); ctx.lineTo(rn.sx, rn.sy); ctx.stroke();
      ctx.restore();

      // Core line
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = e.isSus ? '#ff3311' : '#1a4488';
      ctx.lineWidth   = lw;
      ctx.beginPath(); ctx.moveTo(sn.sx, sn.sy); ctx.lineTo(rn.sx, rn.sy); ctx.stroke();
      ctx.restore();

      // Moving particle — ALWAYS on, loops continuously
      if(!e.pt) e.pt = Math.random();
      var cycleDur = e.isSus ? 900 : 1600;
      e.pt = (e.pt + (1 / (cycleDur / 16))) % 1;  // ~60fps step
      var px = sn.sx + (rn.sx - sn.sx) * e.pt;
      var py = sn.sy + (rn.sy - sn.sy) * e.pt;
      var pr = Math.max(2.5, r * 0.48);
      ctx.save();
      ctx.globalAlpha = fade * (e.isSus ? 0.97 : 0.82);
      ctx.shadowColor = e.isSus ? '#ff7700' : '#4488ff';
      ctx.shadowBlur  = 10;
      ctx.beginPath(); ctx.arc(px, py, pr, 0, Math.PI*2);
      ctx.fillStyle = e.isSus ? '#ff6600' : '#4499ff';
      ctx.fill();
      ctx.restore();
    }
  }

  var hoveredNode = null;
  var tipEl = document.getElementById('tip');

  function drawNodes(r, t){
    nodeList.forEach(function(n){
      var cx = n.sx, cy = n.sy;
      if(cx < -r*4 || cx > W+r*4 || cy < -r*4 || cy > H+r*4) return;

      var col     = nodeColor(n);
      var isFraud = n.status === 'fraud';
      var isEarly = n.status === 'early';
      var pulse   = isFraud ? 1+0.28*Math.sin(t*4   + n.pulse) :
                    isEarly  ? 1+0.14*Math.sin(t*2.5 + n.pulse) : 1;
      var rp      = r * pulse;

      if(isFraud || isEarly || n.newAccountPopup > 0){
        ctx.save();
        ctx.globalAlpha = isFraud
          ? 0.18+0.12*Math.sin(t*3+n.pulse)
          : n.newAccountPopup > 0 ? 0.20 : 0.10;
        ctx.beginPath(); ctx.arc(cx, cy, rp*2.2, 0, Math.PI*2);
        ctx.fillStyle = col; ctx.fill();
        ctx.restore();
      }

      ctx.beginPath(); ctx.arc(cx, cy, rp, 0, Math.PI*2);
      ctx.fillStyle   = col+'cc'; ctx.fill();
      ctx.strokeStyle = col;
      ctx.lineWidth   = (isFraud||isEarly) ? 1.5 : 0.8;
      ctx.stroke();

      ctx.beginPath(); ctx.arc(cx, cy, rp*0.35, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(255,255,255,0.75)'; ctx.fill();

      if(n.suspicion > 0 && n.suspicion < SUSP_T2 && zoom > 1.5){
        var pct = n.suspicion / SUSP_T2;
        ctx.beginPath();
        ctx.arc(cx, cy, rp+3, -Math.PI/2, -Math.PI/2 + Math.PI*2*pct);
        ctx.strokeStyle = n.suspicion >= SUSP_T1 ? '#ffaa0066' : '#1a6fff44';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      if(zoom > 3 && r > 8){
        ctx.font         = (Math.min(10,r*0.75))+'px Share Tech Mono,monospace';
        ctx.fillStyle    = col;
        ctx.textAlign    = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(n.id.slice(-5), cx, cy+rp+2);
      }

      if(n === hoveredNode){
        ctx.beginPath(); ctx.arc(cx, cy, rp*1.5, 0, Math.PI*2);
        ctx.strokeStyle='#ffffff'; ctx.lineWidth=1.5; ctx.stroke();
      }

      if(n.newAccountPopup > 0){
        var alpha = Math.min(1, n.newAccountPopup / 800);
        ctx.save();
        ctx.globalAlpha  = alpha;
        ctx.font         = '9px Share Tech Mono,monospace';
        ctx.fillStyle    = '#00ff88';
        ctx.textAlign    = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText('NEW ACCOUNT', cx, cy - rp - 8);
        ctx.beginPath();
        ctx.arc(cx, cy, rp * 2.8, 0, Math.PI*2);
        ctx.strokeStyle = '#00ff8855';
        ctx.lineWidth   = 1;
        ctx.stroke();
        ctx.restore();
      }
    });
  }

  function findHoveredNode(r){
    var r2 = (r*1.6)*(r*1.6);
    for(var i = nodeList.length-1; i >= 0; i--){
      var n  = nodeList[i];
      var dx = mouseScreenX - n.sx;
      var dy = mouseScreenY - n.sy;
      if(dx*dx + dy*dy < r2) return n;
    }
    return null;
  }

  var t = 0, lastFrame = 0;
  function render(timestamp){
    requestAnimationFrame(render);
    var dt  = Math.min(0.05, (timestamp - lastFrame) / 1000);
    lastFrame = timestamp; t += dt;

    ctx.fillStyle = '#04080f';
    ctx.fillRect(0, 0, W, H);

    var r = getNodeRadius();
    computeScreenPositions();
    applyCollision(r);
    drawEdges(r);
    drawNodes(r, t);

    nodeList.forEach(function(n){
      if(n.newAccountPopup > 0) n.newAccountPopup -= dt * 1000;
    });

    hoveredNode = findHoveredNode(r);
    if(hoveredNode){
      var labels = {
        fraud:  '<span style="color:#ff3311">CONFIRMED FRAUD</span>',
        early:  '<span style="color:#ffaa00">EARLY WARNING</span>',
        normal: '<span style="color:#3366cc">Normal</span>',
        banned: '<span style="color:#445566">Banned</span>',
      };
      var sus = hoveredNode.suspicion > 0
        ? '<br>Suspicion: '+hoveredNode.suspicion.toFixed(0)+'/100' : '';
      tipEl.innerHTML  = 'ID: '+hoveredNode.id+'<br>'+(labels[hoveredNode.status]||'')+sus;
      tipEl.style.left = (hoveredNode.sx+14) + 'px';
      tipEl.style.top  = (hoveredNode.sy-10) + 'px';
      tipEl.style.display = 'block';
    } else {
      tipEl.style.display = 'none';
    }
  }
  requestAnimationFrame(render);

  if(TRIGGER_SIREN && FRAUD_IDS.size > 0){
    setTimeout(function(){
      var fraudNodes = nodeList.filter(function(n){ return FRAUD_IDS.has(n.id); });
      zoomToFraudCluster(fraudNodes);
      flashRed();
      updateFlowButton();
    }, 400);
  }

  if(!window._seenTxIds) window._seenTxIds = new Set();
  var seenTxIds = window._seenTxIds;

  function addTxRow(tx, isSus){
    var feed = document.getElementById('txFeed');
    var s    = tx.sender   ? tx.sender.toString().slice(-4)   : '????';
    var r    = tx.receiver ? tx.receiver.toString().slice(-4) : '????';
    var amt  = tx.amount   ? parseFloat(tx.amount).toFixed(0) : '0';
    var ch   = tx.channel  || 'TXN';
    var d    = document.createElement('div');
    d.className = 'tx-row' + (isSus ? ' atk' : '');
    d.innerHTML = '<span>'+ch+' '+s+'\u2192'+r+'</span><span class="ta">\u20b9'+amt+'</span>';
    feed.insertBefore(d, feed.firstChild);
    requestAnimationFrame(function(){ d.classList.add('vis'); });
    while(feed.children.length > 10) feed.removeChild(feed.lastChild);
  }

  if(SUS_DATA.length > 0){
    document.getElementById('susBox').classList.add('on');
    var f = document.getElementById('susFeed');
    SUS_DATA.forEach(function(tx){
      var d = document.createElement('div'); d.className='srow';
      d.innerHTML =
        '<div class="sacc">'+tx.sender.slice(-6)+' \u2192 '+tx.receiver.slice(-6)+'</div>'+
        '<div class="smeta">'+tx.channel+' \u00b7 \u20b9'+tx.amount.toFixed(2)+'</div>';
      f.appendChild(d);
    });
  }

  function updateNodeStatus(id, newStatus){
    var n = nodeMap[id];
    if(!n || n.status === newStatus) return;
    n.status = newStatus;
  }

  function syncEwHud(){
    var earlyNodes = [], fct = 0;
    nodeList.forEach(function(n){
      if(n.status === 'early') earlyNodes.push(n);
      if(n.status === 'fraud') fct++;
    });
    // Hard cap: max 8% of total nodes early-warning at once
    var maxEarly = Math.max(5, Math.ceil(nodeList.length * 0.08));
    if(earlyNodes.length > maxEarly){
      earlyNodes.sort(function(a,b){ return a.suspicion - b.suspicion; });
      earlyNodes.slice(0, earlyNodes.length - maxEarly).forEach(function(n){
        n.status = 'normal';
      });
      earlyNodes = earlyNodes.slice(earlyNodes.length - maxEarly);
    }
    document.getElementById('hEw').textContent = earlyNodes.length;
    document.getElementById('hFr').textContent = fct;
  }

  // Behaviour-driven suspicion — starts at 0, grows from transactions
  var AGE_THRESHOLD_MS = 30 * 24 * 3600 * 1000;
  var HIGH_VALUE_AMOUNT = 5000;

  var curFraud = new Set(FRAUD_IDS);

  function tickSuspicion(sn, rn, amount){
    if(!sn || !rn) return;

    if(!sn.receivers[rn.id]){ sn.receivers[rn.id]=true; sn.receiverCount++; }
    if(!rn.senders[sn.id])  { rn.senders[sn.id]=true;  rn.senderCount++;   }
    sn.outCount++;
    rn.inCount++;

    var now = Date.now();
    var ds = 0, dr = 0;

    // 1. New account + high-value transaction
    if((now - sn.createdAt) < AGE_THRESHOLD_MS && amount > HIGH_VALUE_AMOUNT) ds += 10;

    // 2. Too many outgoing (harder threshold)
    if(sn.outCount > 10) ds += 2;
    if(sn.outCount > 20) ds += 2;

    // 3. Fan-out (unique receivers)
    if(sn.receiverCount > 6)  ds += 5;
    if(sn.receiverCount > 12) ds += 5;

    // 4. Fan-in on receiver
    if(rn.senderCount > 6) dr += 4;
    if(rn.senderCount > 12) dr += 5;

    // 5. Pass-through
    if(rn.outCount > 3 && rn.inCount > 3) dr += 3;

    // 6. Velocity spike (only if already suspicious)
    if(sn.suspicion > 25 && amount > HIGH_VALUE_AMOUNT * 2.0) ds += 5;

    sn.suspicion = Math.min(SUSP_T2 - 1, sn.suspicion + ds);
    rn.suspicion = Math.min(SUSP_T2 - 1, rn.suspicion + dr);

    var changed = false;
    [sn, rn].forEach(function(n){
      if(curFraud.has(n.id)) return;
      if(n.suspicion >= SUSP_T1 && n.status === 'normal'){
        updateNodeStatus(n.id, 'early');
        changed = true;
      }
    });
    if(changed) syncEwHud();
  }

  // New account every 10 s
  function createNewAccount(){
    fetch(API+'/create_account', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
    })
    .then(function(res){ return res.ok ? res.json() : null; })
    .then(function(data){
      if(!data || !data.account_id) return;
      var id = String(data.account_id);
      if(nodeMap[id]) return;
      var wx = typeof data.x === 'number' ? data.x : Math.random() * WORLD_W;
      var wy = typeof data.y === 'number' ? data.y : Math.random() * WORLD_H;
      var node = makeNode(id, 'normal', wx, wy);
      node.newAccountPopup = 2500;
      node.createdAt = Date.now();
      nodeMap[id] = node;
      nodeList.push(node);
    })
    .catch(function(){});
  }
  setInterval(createNewAccount, 10000);

  // Suspicion decay — accounts that stop transacting lose score over time
  setInterval(function(){
    var changed = false;
    nodeList.forEach(function(n){
      if(n.status === 'fraud' || n.status === 'banned') return;
      if(n.suspicion <= 0) return;
      n.suspicion = Math.max(0, n.suspicion - 2);
      if(n.suspicion < SUSP_T1 && n.status === 'early'){
        n.status = 'normal';
        changed = true;
      }
    });
    if(changed) syncEwHud();
  }, 8000);

  var pollErr = 0;

  function pollMetrics(){
    fetch(API+'/metrics')
    .then(function(res){ return res.ok ? res.json() : null; })
    .then(function(m){
      if(!m) throw new Error();
      document.getElementById('hTps').textContent  = parseFloat(m.tps||0).toFixed(2);
      // hTx driven by local counter — not backend total
      document.getElementById('hAcc').textContent  = m.active_accounts || 0;
      document.getElementById('hBan').textContent  = m.banned_count    || 0;
      document.getElementById('apiSt').style.color = '#1a4422';
      document.getElementById('apiSt').textContent = 'LIVE';
      pollErr = 0;
    })
    .catch(function(){
      if(++pollErr >= 3){
        document.getElementById('apiSt').style.color='#441111';
        document.getElementById('apiSt').textContent='OFFLINE';
      }
    });
  }

  function pollSuspicionScores(){
    fetch(API+'/suspicion_scores')
    .then(function(res){ return res.ok ? res.json() : null; })
    .then(function(scores){
      if(!scores || typeof scores !== 'object' || Array.isArray(scores)) return;
      var entries = Object.keys(scores).map(function(k){
        var v = parseFloat(scores[k]);
        return isNaN(v) ? null : [k, v];
      }).filter(Boolean).sort(function(a,b){ return b[1]-a[1]; });
      var topN   = Math.ceil(entries.length * 0.08);
      var topIds = new Set(
        entries.slice(0, topN)
          .filter(function(e){ return e[1] >= 0.25; })
          .map(function(e){ return e[0]; })
      );
      var changed = false;
      nodeList.forEach(function(n){
        if(n.status === 'fraud' || n.status === 'banned') return;
        if(topIds.has(n.id) && n.status !== 'early'){
          n.suspicion = Math.max(n.suspicion, SUSP_T1 + 1);
          n.status = 'early';
          changed = true;
        }
      });
      if(changed) syncEwHud();
    })
    .catch(function(){});
  }

  if(typeof window._localTxCount === 'undefined') window._localTxCount = 0;

  function pollTransactions(){
    fetch(API+'/transactions')
    .then(function(res){ return res.ok ? res.json() : []; })
    .then(function(list){
      list.forEach(function(tx){
        var txId = tx.transaction_id ||
          (String(tx.sender)+String(tx.receiver)+String(tx.amount)+String(tx.timestamp));
        if(seenTxIds.has(txId)) return;
        seenTxIds.add(txId);
        if(seenTxIds.size > 3000){
          seenTxIds.delete(seenTxIds.values().next().value);
        }

        var s      = tx.sender   ? tx.sender.toString()   : null;
        var r      = tx.receiver ? tx.receiver.toString() : null;
        var isSus  = (s && curFraud.has(s)) || (r && curFraud.has(r)) || tx.is_attack === true;

        // During attack: skip normal (non-attack) transactions entirely
        if(attackPhase && !isSus) return;

        addTxRow(tx, isSus);

        // Increment local TX counter (starts at 0 on page load)
        window._localTxCount++;
        document.getElementById('hTx').textContent = window._localTxCount;

        if(!s || !r || !nodeMap[s] || !nodeMap[r] || s === r) return;

        var amount = parseFloat(tx.amount) || 0;

        // Only tick suspicion during normal (idle) phase
        if(!attackPhase) tickSuspicion(nodeMap[s], nodeMap[r], amount);

        if(attackPhase){
          if(!isSus) return;
          if(edges.length >= ATTACK_EDGE_MAX) return;
          edges.push({
            senderId: s, receiverId: r, isSus: true,
            createdAt: Date.now(), life: ATTACK_EDGE_LIFE,
          });
        } else {
          edges.push({
            senderId: s, receiverId: r, isSus: isSus,
            createdAt: Date.now(), life: NORMAL_EDGE_LIFE,
          });
          while(edges.length > NORMAL_EDGE_MAX) edges.shift();
        }
      });
    })
    .catch(function(){});
  }

  function pollAccounts(){
    fetch(API+'/accounts')
    .then(function(res){ return res.ok ? res.json() : []; })
    .then(function(list){
      var newFraud = new Set();
      list.forEach(function(acc){
        var id = acc.account_id ? acc.account_id.toString() : null;
        if(!id) return;
        if(acc.is_active === false){
          // Keep node visible as grey — do NOT remove from graph
          if(nodeMap[id] && nodeMap[id].status !== 'banned'){
            nodeMap[id].status = 'banned';
            syncEwHud();
          }
          return;
        }
        if(!nodeMap[id]){
          var wx = typeof acc.x === 'number' ? acc.x : Math.random()*WORLD_W;
          var wy = typeof acc.y === 'number' ? acc.y : Math.random()*WORLD_H;
          var node = makeNode(id, 'normal', wx, wy);
          nodeMap[id] = node;
          nodeList.push(node);
        }
        var isFraud = acc.is_fraud === 1 || acc.is_fraud === true;
        if(isFraud) newFraud.add(id);
      });

      var brandNew = [];
      newFraud.forEach(function(id){ if(!curFraud.has(id)) brandNew.push(id); });
      if(brandNew.length > 0){
        attackPhase = true;
        brandNew.forEach(function(id){
          updateNodeStatus(id, 'fraud');
          if(nodeMap[id]) nodeMap[id].suspicion = 100;
        });
        edges.length = 0;
        var fraudNodes = nodeList.filter(function(n){ return newFraud.has(n.id); });
        zoomToFraudCluster(fraudNodes);
        flashRed();   // one call — guarded by _flashAt cooldown
        updateFlowButton();
        syncEwHud();
      }
      // When all fraud nodes are now banned, reset attackPhase
      var anyFraud = nodeList.some(function(n){ return n.status === 'fraud'; });
      if(!anyFraud && attackPhase) attackPhase = false;
      curFraud = newFraud;
    })
    .catch(function(){});
  }

  pollMetrics();         setInterval(pollMetrics,         3000);
  pollTransactions();    setInterval(pollTransactions,    1500);
  pollAccounts();        setInterval(pollAccounts,        5000);
  pollSuspicionScores(); setInterval(pollSuspicionScores, 10000);

})();

// ═══════════════════════════════════════════════════════
// GRAPH 2 — ATTACK REPLAY SYSTEM
// ═══════════════════════════════════════════════════════
(function(){
  var g2wrap = document.getElementById('g2wrap');
  var g2c    = document.getElementById('g2Canvas');
  var dpr2   = window.devicePixelRatio || 1;
  var W2     = g2wrap.clientWidth || 1200;
  var H2     = 320;
  g2c.width        = Math.round(W2 * dpr2);
  g2c.height       = Math.round(H2 * dpr2);
  g2c.style.width  = W2 + 'px';
  g2c.style.height = H2 + 'px';
  var ctx2 = g2c.getContext('2d');
  ctx2.scale(dpr2, dpr2);

  var attackNodes   = [];
  var attackEdges   = [];
  var nodePos2      = {};
  var replayEdges   = [];
  var activeParticle = null;
  var replayIndex   = 0;
  var replayActive  = false;
  var replayTimer   = null;
  var hasAttack     = false;

  var btnReplay    = document.getElementById('btnReplay');
  var replayStatus = document.getElementById('replayStatus');
  var noFraudEl    = document.getElementById('noFraud');

  function computeLayout(){
    nodePos2 = {};
    var N = attackNodes.length;
    if(N === 0) return;

    var fraudNodes = attackNodes.filter(function(n){ return n.role === 'fraud'; });
    var susNodes   = attackNodes.filter(function(n){ return n.role !== 'fraud'; });

    var fCX = W2 * 0.32, fCY = H2 * 0.50;
    var fR  = Math.min(90, Math.max(40, fraudNodes.length * 18));
    fraudNodes.forEach(function(n, i){
      var a = (i / Math.max(1, fraudNodes.length)) * Math.PI * 2 - Math.PI / 2;
      nodePos2[n.id] = { x: fCX + Math.cos(a)*fR, y: fCY + Math.sin(a)*fR, isFraud: true };
    });

    var sCX = W2 * 0.68, sCY = H2 * 0.50;
    var sR  = Math.min(110, Math.max(50, susNodes.length * 18));
    susNodes.forEach(function(n, i){
      var a = (i / Math.max(1, susNodes.length)) * Math.PI * 2 - Math.PI / 2;
      nodePos2[n.id] = { x: sCX + Math.cos(a)*sR, y: sCY + Math.sin(a)*sR, isFraud: false };
    });
  }

  function startReplay(){
    if(replayActive || attackEdges.length === 0) return;
    replayEdges    = [];
    replayIndex    = 0;
    replayActive   = true;
    activeParticle = null;
    btnReplay.classList.add('replaying');
    btnReplay.textContent = 'REPLAYING...';
    btnReplay.disabled    = true;
    replayStatus.textContent = 'Replaying 0 / '+attackEdges.length+' transactions...';
    scheduleNext();
  }

  function scheduleNext(){
    if(replayIndex >= attackEdges.length){ finishReplay(); return; }
    var edge = attackEdges[replayIndex];
    var sPos = nodePos2[edge.source];
    var tPos = nodePos2[edge.target];

    if(!sPos || !tPos){
      replayIndex++;
      replayTimer = setTimeout(scheduleNext, 150);
      return;
    }

    var isFraudEdge =
      attackNodes.some(function(n){ return n.id===edge.source && n.role==='fraud'; }) &&
      attackNodes.some(function(n){ return n.id===edge.target && n.role==='fraud'; });
    var col = isFraudEdge ? '#ff1100' : '#ff6600';

    activeParticle = {
      sx: sPos.x, sy: sPos.y,
      ex: tPos.x, ey: tPos.y,
      progress: 0, color: col, edge: edge,
    };

    setTimeout(function(){
      activeParticle = null;
      replayEdges.push({source: edge.source, target: edge.target,
        amount: edge.amount, color: col});
      replayIndex++;
      replayStatus.textContent =
        'Transaction '+replayIndex+' / '+attackEdges.length+'  \u00b7  '+
        edge.source.slice(-4)+' \u2192 '+edge.target.slice(-4)+
        '  \u20b9'+parseFloat(edge.amount||0).toFixed(0);
      replayTimer = setTimeout(scheduleNext, 380);
    }, 650);
  }

  function finishReplay(){
    replayActive   = false;
    replayTimer    = null;
    activeParticle = null;
    btnReplay.classList.remove('replaying');
    btnReplay.textContent = 'REPLAY AGAIN';
    btnReplay.disabled    = false;
    replayStatus.textContent = 'Replay complete \u2014 '+attackEdges.length+' transactions shown.';
  }

  btnReplay.addEventListener('click', startReplay);

  function drawArrowEdge(x1, y1, x2, y2, col, alpha, lw){
    var dx  = x2-x1, dy = y2-y1;
    var len = Math.sqrt(dx*dx+dy*dy) || 1;
    var ux  = dx/len, uy = dy/len;
    var nr  = 14, er = 14;
    var sx  = x1+ux*nr, sy = y1+uy*nr;
    var ex  = x2-ux*er, ey = y2-uy*er;
    if((ex-sx)*(ex-sx)+(ey-sy)*(ey-sy) < 4) return;
    ctx2.save();
    ctx2.globalAlpha = alpha;
    ctx2.beginPath(); ctx2.moveTo(sx,sy); ctx2.lineTo(ex,ey);
    ctx2.strokeStyle = col; ctx2.lineWidth = lw; ctx2.stroke();
    var ax = ex-ux*8-uy*5, ay = ey-uy*8+ux*5;
    var bx = ex-ux*8+uy*5, by = ey-uy*8-ux*5;
    ctx2.beginPath(); ctx2.moveTo(ex,ey); ctx2.lineTo(ax,ay); ctx2.lineTo(bx,by);
    ctx2.closePath(); ctx2.fillStyle=col; ctx2.fill();
    ctx2.restore();
  }

  var t2 = 0, lastFrame2 = 0;
  function render2(ts){
    requestAnimationFrame(render2);
    var dt = Math.min(0.05, (ts - lastFrame2) / 1000);
    lastFrame2 = ts; t2 += dt;

    ctx2.fillStyle = '#020610';
    ctx2.fillRect(0, 0, W2, H2);

    ctx2.strokeStyle = 'rgba(13,30,50,0.35)';
    ctx2.lineWidth   = 0.5;
    for(var x=0; x<W2; x+=40){
      ctx2.beginPath(); ctx2.moveTo(x,0); ctx2.lineTo(x,H2); ctx2.stroke();
    }
    for(var y=0; y<H2; y+=40){
      ctx2.beginPath(); ctx2.moveTo(0,y); ctx2.lineTo(W2,y); ctx2.stroke();
    }

    if(!hasAttack || attackNodes.length === 0) return;

    // Draw replayed edges (faded, persistent)
    replayEdges.forEach(function(e){
      var sPos = nodePos2[e.source], tPos = nodePos2[e.target];
      if(!sPos || !tPos) return;
      drawArrowEdge(sPos.x, sPos.y, tPos.x, tPos.y, e.color, 0.40, 1.2);
    });

    // Draw active particle + animated edge
    if(activeParticle){
      var p = activeParticle;
      p.progress = Math.min(1, p.progress + dt / 0.65);
      drawArrowEdge(p.sx, p.sy, p.ex, p.ey, p.color, 0.22, 0.8);
      var px = p.sx + (p.ex - p.sx) * p.progress;
      var py = p.sy + (p.ey - p.sy) * p.progress;
      ctx2.globalAlpha = 1;
      ctx2.beginPath(); ctx2.arc(px, py, 5, 0, Math.PI*2);
      ctx2.fillStyle = p.color; ctx2.fill();
      ctx2.globalAlpha = 0.35;
      ctx2.beginPath(); ctx2.arc(px, py, 10, 0, Math.PI*2);
      ctx2.fillStyle = p.color; ctx2.fill();
      ctx2.globalAlpha = 1;
    }

    // Nodes (always visible — shown before replay starts)
    attackNodes.forEach(function(n){
      var pos = nodePos2[n.id];
      if(!pos) return;
      var isFraud  = n.role === 'fraud';
      var r        = isFraud ? 13 : 9;
      var col      = isFraud ? '#ff2244' : '#ff8833';
      var pulse    = isFraud ? 1+0.20*Math.sin(t2*3.5+pos.x*0.01) : 1;
      var rp       = r * pulse;

      if(isFraud){
        ctx2.save(); ctx2.globalAlpha = 0.14+0.10*Math.sin(t2*3);
        ctx2.beginPath(); ctx2.arc(pos.x, pos.y, rp*2.2, 0, Math.PI*2);
        ctx2.fillStyle = col; ctx2.fill(); ctx2.restore();
      }

      ctx2.beginPath(); ctx2.arc(pos.x, pos.y, rp, 0, Math.PI*2);
      ctx2.fillStyle   = col+'44'; ctx2.fill();
      ctx2.strokeStyle = col;
      ctx2.lineWidth   = isFraud ? 2 : 1.2;
      ctx2.stroke();

      ctx2.beginPath(); ctx2.arc(pos.x, pos.y, rp*0.38, 0, Math.PI*2);
      ctx2.fillStyle = 'rgba(255,255,255,0.8)'; ctx2.fill();

      ctx2.font      = 'bold '+(isFraud?9:8)+'px Share Tech Mono,monospace';
      ctx2.fillStyle = isFraud ? '#ff6644' : '#ff9944';
      ctx2.textAlign = 'center';
      ctx2.textBaseline = 'bottom';
      ctx2.fillText(n.id.slice(-6), pos.x, pos.y - rp - 4);

      if(n.sus_score > 0){
        ctx2.font      = '7px Share Tech Mono,monospace';
        ctx2.fillStyle = '#553300';
        ctx2.textBaseline = 'top';
        ctx2.fillText('sus:'+(n.sus_score*100).toFixed(0), pos.x, pos.y + rp + 3);
      }
    });
  }
  requestAnimationFrame(render2);

  function pollLatestAttack(){
    fetch(API+'/latest_attack')
    .then(function(res){ return res.ok ? res.json() : null; })
    .then(function(data){
      if(!data || !data.attack_name || !data.nodes || data.nodes.length === 0){
        hasAttack = false;
        noFraudEl.style.display = 'block';
        g2c.style.display       = 'none';
        btnReplay.disabled      = true;
        document.getElementById('g2stats').textContent = 'No attack detected yet';
        document.getElementById('g2label').textContent = 'ATTACK SUBGRAPH \u2014 FRAUD NETWORK';
        return;
      }

      var wasNew = !hasAttack;
      hasAttack   = true;
      attackNodes = data.nodes  || [];
      attackEdges = data.edges  || [];
      noFraudEl.style.display = 'none';
      g2c.style.display       = 'block';

      var lbl = (data.attack_name || '').toUpperCase();
      document.getElementById('g2label').textContent = lbl + ' \u2014 ATTACK GRAPH';
      document.getElementById('g2stats').textContent =
        attackNodes.filter(function(n){ return n.role==='fraud'; }).length +
        ' fraud nodes \u00b7 ' + attackEdges.length +
        ' transactions \u00b7 click \u25b6 to replay';

      if(wasNew || replayEdges.length === 0){
        replayEdges    = [];
        replayIndex    = 0;
        replayActive   = false;
        activeParticle = null;
        if(replayTimer){ clearTimeout(replayTimer); replayTimer=null; }
        btnReplay.classList.remove('replaying');
        btnReplay.textContent = 'VIEW TRANSACTION FLOW';
        btnReplay.disabled    = attackEdges.length === 0;
        replayStatus.textContent = attackEdges.length > 0
          ? attackEdges.length + ' transactions ready to replay'
          : 'No transactions recorded for this attack';
      }
      computeLayout();
    })
    .catch(function(){});
  }

  pollLatestAttack();
  setInterval(pollLatestAttack, 5000);

})();
</script>
</body></html>"""

    html = html_head + html_consts + html_body
    components.html(html, height=height + 400, scrolling=False)