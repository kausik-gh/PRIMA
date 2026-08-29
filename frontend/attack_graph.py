"""
frontend/attack_graph.py — Graph 2

Orbital layout attack burst graph.
- Polls /latest_attack every 2.5s
- Fraud/mule nodes on inner ring
- Receiver nodes on outer ring
- Bezier arcs with animated particles and ₹ amount labels
- Shows idle state when no attack has run
"""
import streamlit.components.v1 as components


def render_attack_graph(api_url: str, height: int = 440):
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#04080f;overflow:hidden;font-family:'Courier New',monospace;}}
#wrap{{position:relative;width:100%;height:{height}px;background:#04080f;}}
canvas{{position:absolute;top:0;left:0;}}
#scanlines{{position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,
  rgba(0,0,0,0.04) 2px,rgba(0,0,0,0.04) 4px);}}
#hud-title{{position:absolute;top:10px;left:50%;transform:translateX(-50%);
  color:#ff4466;font-size:11px;font-weight:bold;letter-spacing:2px;
  text-shadow:0 0 12px #ff224488;white-space:nowrap;pointer-events:none;}}
#hud-sub{{position:absolute;top:28px;left:50%;transform:translateX(-50%);
  color:#445566;font-size:9px;letter-spacing:1px;white-space:nowrap;pointer-events:none;}}
#live{{position:absolute;top:10px;right:12px;color:#00ff88;
  font-size:9px;letter-spacing:1px;pointer-events:none;}}
#legend{{position:absolute;bottom:10px;left:50%;transform:translateX(-50%);
  display:flex;gap:18px;pointer-events:none;}}
.li{{color:#556677;font-size:8px;letter-spacing:1px;}}
.lf{{color:#ff4466;}}.le{{color:#ffaa00;}}.lr{{color:#1a9fff;}}
</style>
</head>
<body>
<div id="wrap">
  <canvas id="c"></canvas>
  <div id="scanlines"></div>
  <div id="hud-title" id="attackTitle">⚠ ATTACK BURST GRAPH</div>
  <div id="hud-sub"   id="attackSub">monitoring attack surface...</div>
  <div id="live">● LIVE</div>
  <div id="legend">
    <span class="li lf">● Fraud / Mule</span>
    <span class="li le">● Early Warning</span>
    <span class="li lr">● Receiver</span>
  </div>
</div>

<script>
const API    = '{api_url}';
const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
const wrap   = document.getElementById('wrap');

let W, H, CX, CY, state=null, pulseT=0;

function resize(){{
  W=canvas.width=wrap.clientWidth||800;
  H=canvas.height=wrap.clientHeight||{height};
  CX=W/2; CY=H/2;
}}
resize();
window.addEventListener('resize',resize);

const COL={{fraud:'#ff2244',early:'#ffaa00',receiver:'#1a9fff'}};
const GLW={{fraud:'rgba(255,34,68,',early:'rgba(255,170,0,',receiver:'rgba(26,159,255,'}};

function nc(r){{return COL[r]||COL.receiver;}}
function ng(r){{return GLW[r]||GLW.receiver;}}

function computePositions(nodes){{
  const fraud=nodes.filter(n=>n.role==='fraud');
  const early=nodes.filter(n=>n.role==='early');
  const recv =nodes.filter(n=>n.role==='receiver');
  const R1=Math.min(W,H)*0.18, R2=Math.min(W,H)*0.33, Rm=(R1+R2)*0.55;
  const pm={{}};
  fraud.forEach((n,i)=>{{const a=(2*Math.PI*i/Math.max(fraud.length,1))-Math.PI/2;pm[n.id]={{x:CX+R1*Math.cos(a),y:CY+R1*Math.sin(a),role:n.role}};}});
  early.forEach((n,i)=>{{const a=(2*Math.PI*i/Math.max(early.length,1))+Math.PI/4; pm[n.id]={{x:CX+Rm*Math.cos(a),y:CY+Rm*Math.sin(a),role:n.role}};}});
  recv .forEach((n,i)=>{{const a=(2*Math.PI*i/Math.max(recv.length, 1))-Math.PI/2+0.3;pm[n.id]={{x:CX+R2*Math.cos(a),y:CY+R2*Math.sin(a),role:n.role}};}});
  return pm;
}}

function rrect(ctx,x,y,w,h,r){{
  ctx.beginPath();ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);ctx.arcTo(x+w,y,x+w,y+r,r);
  ctx.lineTo(x+w,y+h-r);ctx.arcTo(x+w,y+h,x+w-r,y+h,r);
  ctx.lineTo(x+r,y+h);ctx.arcTo(x,y+h,x,y+h-r,r);
  ctx.lineTo(x,y+r);ctx.arcTo(x,y,x+r,y,r);ctx.closePath();
}}

function drawGrid(){{
  ctx.strokeStyle='#0a1825';ctx.lineWidth=0.5;ctx.globalAlpha=0.4;
  for(let x=0;x<W;x+=32){{ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}}
  for(let y=0;y<H;y+=32){{ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}}
  ctx.globalAlpha=1;
}}

function drawNode(x,y,role,pulse){{
  const r=role==='fraud'?14:role==='early'?11:9;
  const col=nc(role),glow=ng(role);
  const pf=role==='fraud'?(0.7+0.3*Math.sin(pulse)):1;
  [5,3,2].forEach((m,i)=>{{
    const gr=ctx.createRadialGradient(x,y,0,x,y,r*m*pf);
    gr.addColorStop(0,glow+(0.22-i*0.06)+')');gr.addColorStop(1,glow+'0)');
    ctx.beginPath();ctx.arc(x,y,r*m*pf,0,Math.PI*2);ctx.fillStyle=gr;ctx.fill();
  }});
  if(role==='fraud'){{
    ctx.beginPath();ctx.arc(x,y,r*(1.8+0.6*Math.sin(pulse)),0,Math.PI*2);
    ctx.strokeStyle=col;ctx.lineWidth=1.2;ctx.globalAlpha=0.5-0.3*Math.sin(pulse);ctx.stroke();ctx.globalAlpha=1;
  }}
  if(role==='early'){{
    ctx.beginPath();ctx.arc(x,y,r*1.6,0,Math.PI*2);
    ctx.strokeStyle=col;ctx.lineWidth=0.8;ctx.globalAlpha=0.35;ctx.stroke();ctx.globalAlpha=1;
  }}
  ctx.beginPath();ctx.arc(x,y,r*1.1,0,Math.PI*2);ctx.fillStyle='#060d18';ctx.fill();
  ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);
  ctx.strokeStyle=col;ctx.lineWidth=role==='fraud'?2:1.5;ctx.stroke();
  ctx.fillStyle=col;ctx.globalAlpha=0.15;ctx.fill();ctx.globalAlpha=1;
  ctx.beginPath();ctx.arc(x,y,r*0.2,0,Math.PI*2);
  ctx.fillStyle='rgba(255,255,255,0.9)';ctx.fill();
}}

function drawLabel(x,y,r,id,role){{
  const txt='ACC-'+String(id).slice(-4);
  const col=nc(role);
  ctx.font='bold 8px Courier New';
  const tw=ctx.measureText(txt).width+10;
  const px=x-tw/2,py=y+r+6;
  ctx.fillStyle='rgba(4,8,15,0.88)';
  rrect(ctx,px,py,tw,14,3);ctx.fill();
  ctx.strokeStyle=col;ctx.lineWidth=0.6;ctx.globalAlpha=0.5;
  rrect(ctx,px,py,tw,14,3);ctx.stroke();ctx.globalAlpha=1;
  ctx.fillStyle=col;ctx.textAlign='center';
  ctx.fillText(txt,x,py+10);ctx.textAlign='left';
}}

function drawEdge(x1,y1,x2,y2,amount,channel,isFraud,tick){{
  const mx=(x1+x2)/2,my=(y1+y2)/2;
  const dx=x2-x1,dy=y2-y1,len=Math.sqrt(dx*dx+dy*dy)||1,bend=len*0.22;
  const cpx=mx-dy/len*bend,cpy=my+dx/len*bend;
  const t=((tick*0.012)%1);
  const bx=(1-t)*(1-t)*x1+2*(1-t)*t*cpx+t*t*x2;
  const by=(1-t)*(1-t)*y1+2*(1-t)*t*cpy+t*t*y2;
  const ecol=isFraud?'#ff2244':'#1a9fff';
  const ealp=isFraud?0.65:0.30;
  ctx.beginPath();ctx.moveTo(x1,y1);ctx.quadraticCurveTo(cpx,cpy,x2,y2);
  ctx.strokeStyle=ecol;ctx.lineWidth=3.5;ctx.globalAlpha=ealp*0.2;ctx.stroke();
  ctx.beginPath();ctx.moveTo(x1,y1);ctx.quadraticCurveTo(cpx,cpy,x2,y2);
  ctx.strokeStyle=ecol;ctx.lineWidth=1.0;ctx.globalAlpha=ealp;ctx.stroke();ctx.globalAlpha=1;
  const t2=0.92;
  const ax=(1-t2)*(1-t2)*x1+2*(1-t2)*t2*cpx+t2*t2*x2;
  const ay=(1-t2)*(1-t2)*y1+2*(1-t2)*t2*cpy+t2*t2*y2;
  ctx.save();ctx.translate(x2,y2);ctx.rotate(Math.atan2(y2-ay,x2-ax));
  ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(-7,-3);ctx.lineTo(-7,3);ctx.closePath();
  ctx.fillStyle=ecol;ctx.globalAlpha=ealp;ctx.fill();ctx.globalAlpha=1;ctx.restore();
  ctx.beginPath();ctx.arc(bx,by,3,0,Math.PI*2);
  ctx.fillStyle=isFraud?'#ff6688':'#44aaff';ctx.globalAlpha=0.9;ctx.fill();ctx.globalAlpha=1;
  if(amount>0){{
    const amtStr='₹'+(amount>=1000?(amount/1000).toFixed(1)+'K':amount.toFixed(0));
    const ch_str=channel?(' '+channel):'';
    const label=amtStr+ch_str;
    ctx.font='7px Courier New';
    const tw=ctx.measureText(label).width+8;
    ctx.fillStyle='rgba(4,8,15,0.80)';
    rrect(ctx,cpx-tw/2,cpy-9,tw,13,2);ctx.fill();
    ctx.fillStyle=isFraud?'#ff8899':'#4499cc';
    ctx.textAlign='center';ctx.fillText(label,cpx,cpy);ctx.textAlign='left';
  }}
}}

function drawCenter(name,pulse){{
  const r=26+3*Math.sin(pulse);
  ctx.beginPath();ctx.arc(CX,CY,r*1.6,0,Math.PI*2);
  ctx.strokeStyle='#ff2244';ctx.lineWidth=1;
  ctx.globalAlpha=0.25+0.15*Math.sin(pulse);ctx.stroke();ctx.globalAlpha=1;
  ctx.beginPath();ctx.arc(CX,CY,r,0,Math.PI*2);
  ctx.strokeStyle='#ff2244';ctx.lineWidth=1.5;
  ctx.globalAlpha=0.5;ctx.stroke();ctx.globalAlpha=1;
  ctx.font='bold 9px Courier New';
  const parts=name.toUpperCase().replace(/_/g,' ').split(' ');
  parts.forEach((p,i)=>{{
    ctx.fillStyle='#ff4466';ctx.textAlign='center';
    ctx.shadowColor='#ff2244';ctx.shadowBlur=8;
    ctx.fillText(p,CX,CY-(parts.length-1)*6+i*13);ctx.shadowBlur=0;
  }});
  ctx.textAlign='left';
}}

let posMap={{}},lastIds='';

function draw(){{
  pulseT+=0.04;
  ctx.clearRect(0,0,W,H);ctx.fillStyle='#04080f';ctx.fillRect(0,0,W,H);
  drawGrid();

  if(!state||!state.nodes||state.nodes.length===0){{
    ctx.font='bold 10px Courier New';ctx.textAlign='center';
    ctx.fillStyle=`rgba(13,37,55,${{0.4+0.3*Math.sin(pulseT*0.5)}})`;
    ctx.fillText('MONITORING ATTACK SURFACE',CX,CY-8);
    ctx.font='8px Courier New';
    ctx.fillStyle=`rgba(13,37,55,${{0.3+0.2*Math.sin(pulseT*0.3)}})`;
    ctx.fillText('waiting for next attack...',CX,CY+10);
    ctx.textAlign='left';
    requestAnimationFrame(draw);return;
  }}

  const ids=state.nodes.map(n=>n.id).join(',');
  if(ids!==lastIds){{posMap=computePositions(state.nodes);lastIds=ids;}}

  state.edges.forEach((e,i)=>{{
    const s=posMap[e.source],t=posMap[e.target];
    if(!s||!t) return;
    const isFraud=(s.role==='fraud'||s.role==='early');
    drawEdge(s.x,s.y,t.x,t.y,e.amount,e.channel,isFraud,pulseT*25+i*7);
  }});

  drawCenter(state.attack_name||'ATTACK',pulseT);

  state.nodes.forEach(n=>{{
    const p=posMap[n.id];if(!p)return;
    drawNode(p.x,p.y,n.role,pulseT);
  }});
  state.nodes.forEach(n=>{{
    const p=posMap[n.id];if(!p)return;
    drawLabel(p.x,p.y,n.role==='fraud'?14:n.role==='early'?11:9,n.id,n.role);
  }});

  requestAnimationFrame(draw);
}}

async function poll(){{
  try{{
    const res=await fetch(API+'/latest_attack',{{signal:AbortSignal.timeout(3000)}});
    if(!res.ok)return;
    const data=await res.json();
    state=data;
    const ok=data.attack_name&&data.nodes&&data.nodes.length>0;
    document.getElementById('hud-title').textContent=ok
      ?('⚠  '+data.attack_name.toUpperCase().replace(/_/g,' ')+'  —  ATTACK GRAPH')
      :'⚠ ATTACK BURST GRAPH';
    document.getElementById('hud-sub').textContent=ok
      ?(data.nodes.length+' nodes  ·  '+data.edges.length+' transactions')
      :'monitoring attack surface...';
  }}catch(e){{}}
}}

poll();setInterval(poll,2500);
draw();
</script>
</body></html>"""
    components.html(html, height=height, scrolling=False)