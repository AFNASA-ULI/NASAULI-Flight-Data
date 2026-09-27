"""Self-contained interactive HTML report for one flight (Plotly.js from a CDN)."""

from __future__ import annotations

import html
import json
import math

import numpy as np
import pandas as pd

from . import __version__
from .clean import Session

MAX_PLOT_HZ = 10.0


def _arr(s: pd.Series, nd: int = 2) -> list:
    v = pd.to_numeric(s, errors="coerce").round(nd).to_numpy(dtype=float)
    return [None if math.isnan(x) else (int(x) if nd == 0 else float(x)) for x in v]


def _fmt(x, unit="", nd=1):
    if x is None:
        return "–"
    return f"{x:,.{nd}f}{unit}"


def plot_data(s: Session) -> dict:
    df = s.flight
    rate = (len(df) - 1) / max(df["elapsed_s"].iloc[-1] - df["elapsed_s"].iloc[0], 1e-9)
    step = max(1, round(rate / MAX_PLOT_HZ))
    d = df.iloc[::step]
    data = {
        "t": _arr(d["elapsed_s"], 2),
        "utc": [x.strftime("%H:%M:%S.%f")[:-4] if pd.notna(x) else None for x in d["time_gps_utc"]],
        "E": _arr(d["east_m"], 1), "N": _arr(d["north_m"], 1),
        "alt": _arr(d["alt_rel_m"], 2), "gs": _arr(d["groundspeed_m_s"], 2), "vz": _arr(d["climb_m_s"], 2),
        "roll": _arr(d["roll_deg"], 1), "pitch": _arr(d["pitch_deg"], 1),
        "V": _arr(d["batt_voltage_v"], 2), "I": _arr(d["batt_current_a"], 2),
        "mah": _arr(d["batt_consumed_mah"], 0),
        "m1": _arr(d["motor1_us"], 0), "m2": _arr(d["motor2_us"], 0),
        "m3": _arr(d["motor3_us"], 0), "m4": _arr(d["motor4_us"], 0),
        "vx": _arr(d["vib_x_m_s2"], 2), "vy": _arr(d["vib_y_m_s2"], 2), "vzb": _arr(d["vib_z_m_s2"], 2),
        "ev": _arr(d["ekf_vel_var"], 3), "eph": _arr(d["ekf_pos_horiz_var"], 3),
        "epv": _arr(d["ekf_pos_vert_var"], 3), "ec": _arr(d["ekf_compass_var"], 3),
        "sats": _arr(d["gps_sats"], 0), "hdop": _arr(d["gps_hdop"], 2),
        "mode": [m if isinstance(m, str) else "—" for m in d["flight_mode"].astype(object)],
    }
    wind = None
    if s.wind is not None and len(s.wind):
        w = s.wind
        wind = {"t": _arr(w["elapsed_s"], 2), "spd": _arr(w["wind_speed_m_s"], 1),
                "dir": _arr(w["wind_dir_deg"], 0), "temp": _arr(w["temperature_c"], 1)}
    return {"D": data, "W": wind}


def _stats_html(sm: dict, s: Session) -> str:
    tiles = []
    if sm.get("airborne_s") is not None:
        tiles.append(("Flight", f"≈{sm['airborne_s']:.0f} s airborne",
                      f"takeoff ≈{sm['takeoff_s']:.0f} s, landed ≈{sm['landing_s']:.0f} s"
                      if sm.get("landed_in_log") else f"takeoff ≈{sm['takeoff_s']:.0f} s, log ends airborne"))
    else:
        tiles.append(("Flight", "not airborne", f"{sm['duration_s']:.0f} s logged"))
    modes = [m[2] for m in sm["modes"] if m[2] != "—"]
    dur: dict[str, float] = {}
    for a, b, m in sm["modes"]:
        if m != "—":
            dur[m] = dur.get(m, 0.0) + (b - a)
    main_mode = max(dur, key=dur.get) if dur else "–"
    sub = f"RTL from {sm['rtl_s']:.1f} s" if sm.get("rtl_s") is not None else ", ".join(dict.fromkeys(modes))
    tiles.append(("Mission", f"{main_mode}" + (f", {sm['mission_items']} WPs" if sm.get("mission_items") else ""), sub))
    if sm.get("cruise_speed_m_s") is not None:
        tiles.append(("Cruise", f"{sm['cruise_alt_m']:.0f} m, {sm['cruise_speed_m_s']:.1f} m/s",
                      "relative alt, groundspeed"))
    tiles.append(("Max range", _fmt(sm.get("max_range_m"), " m", 0), f"from home; max alt {_fmt(sm.get('max_alt_rel_m'), ' m')}"))
    bsub = f"{_fmt(sm.get('batt_v_start'), ' V')} → {_fmt(sm.get('batt_v_end'), ' V')}"
    bsub += " at rest" if sm.get("batt_v_end_at_rest") else " (end not at rest)"
    if sm.get("cruise_current_a") is not None:
        bsub += f", ≈{sm['cruise_current_a']:.0f} A cruise"
    tiles.append(("Battery", _fmt(sm.get("batt_consumed_mah"), " mAh", 0), bsub))
    if s.wind is not None:
        if len(s.wind):
            w = s.wind
            tiles.append(("Wind (sensor)", f"{w['wind_speed_m_s'].mean():.1f} m/s mean",
                          f"max {w['wind_speed_m_s'].max():.1f} m/s, from ≈{_circmean(w['wind_dir_deg']):.0f}°"))
        else:
            tiles.append(("Wind (sensor)", "no overlap", "see notes"))
    return "\n".join(
        f'<div class="stat"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div>'
        f'<div class="s">{html.escape(sub)}</div></div>' for k, v, sub in tiles)


def _circmean(deg: pd.Series) -> float:
    r = np.radians(deg.dropna())
    return float(np.degrees(np.arctan2(np.sin(r).mean(), np.cos(r).mean())) % 360)


def _notes_html(checks: list[dict]) -> str:
    if not checks:
        return ""
    n_warn = sum(c["level"] == "warn" for c in checks)
    items = "\n".join(
        f'<p class="{c["level"]}"><strong>{html.escape(c["title"])}.</strong> {html.escape(c["detail"])}</p>'
        for c in checks)
    summary = f"Things to check in this log ({n_warn} warning{'s' if n_warn != 1 else ''}, {len(checks) - n_warn} note{'s' if len(checks) - n_warn != 1 else ''})"
    return f'<details class="notes" open>\n<summary>{summary}</summary>\n{items}\n</details>'


def render(s: Session, summary: dict, checks: list[dict], downloads: dict[str, str]) -> str:
    h = s.info["header"]
    start = pd.Timestamp(summary["start_utc"])
    end = pd.Timestamp(summary["end_utc"])
    platform = summary.get("platform") or "Flight"
    title = f"{platform.split(' (')[0]} flight, {start:%d %b %Y %H:%M} UTC"
    sub = (f"Session <code>{html.escape(summary['session_id'])}</code>, {start:%d %b %Y}, host UTC "
           f"{start:%H:%M:%S} to {end:%H:%M:%S} ({summary['duration_s']:.0f} s at "
           f"{summary['sample_rate_hz']:.0f} Hz). Shaded bands are AUTO mode. Zoom any time plot and the "
           "others follow; the time range you zoom to is highlighted on the ground track.")
    dl = " · ".join(f'<a href="{html.escape(href)}">{html.escape(label)}</a>' for label, href in downloads.items())
    footer = (f"Generated from <code>{html.escape(s.source.name)}</code> ({html.escape(h.get('format', ''))}) by the "
              f"nasauli pipeline v{__version__}, reader <code>{s.info['reader']}</code>. Time axis is "
              f"<code>elapsed_s</code>; hover times are GPS-corrected UTC.")
    wind_section = ""
    if s.wind is not None and len(s.wind):
        wind_section = ('<section><h2>Wind sensor</h2><p class="cap">Wind drone, speed (left axis) and direction '
                        '(right axis, dots). Trimmed to this flight on GPS time.</p><div id="p-wind" class="plot"></div></section>')
    pd_json = json.dumps(plot_data(s), separators=(",", ":"))
    modes_json = json.dumps(summary["modes"], separators=(",", ":"))
    out = TEMPLATE
    for k, v in {
        "__TITLE__": html.escape(title), "__H1__": html.escape(f"{platform.split(' (')[0]} flight"),
        "__SUB__": sub, "__STATS__": _stats_html(summary, s), "__NOTES__": _notes_html(checks),
        "__WIND__": wind_section, "__DOWNLOADS__": dl, "__FOOTER__": footer,
        "__MODES__": modes_json, "__DATA__": pd_json,
    }.items():
        out = out.replace(k, v)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
:root{--bg:#EEF2F5;--panel:#FFFFFF;--ink:#1C2733;--muted:#5B6B7B;--rule:#C9D3DC;--grid:#E1E7EC;
--c1:#2F6690;--c2:#C77D19;--c3:#3A7D6B;--c4:#B23A48;--warn-bg:#FBF1E3;--info-bg:#E9EFF5;--band:rgba(47,102,144,.06)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141A21;--panel:#1B232C;--ink:#DCE3EA;--muted:#8C9AA8;--rule:#2E3945;--grid:#26303A;--c1:#6FA8D6;--c2:#E0A04A;--c3:#6CB8A0;--c4:#E07480;--warn-bg:#2A2419;--info-bg:#1E2833;--band:rgba(111,168,214,.08)}}
:root[data-theme="dark"]{--bg:#141A21;--panel:#1B232C;--ink:#DCE3EA;--muted:#8C9AA8;--rule:#2E3945;--grid:#26303A;--c1:#6FA8D6;--c2:#E0A04A;--c3:#6CB8A0;--c4:#E07480;--warn-bg:#2A2419;--info-bg:#1E2833;--band:rgba(111,168,214,.08)}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
main{max-width:1200px;margin:0 auto;padding:28px 16px 48px}
a{color:var(--c1)}
h1{font-size:1.6rem;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0 0 18px}
code{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.88em;overflow-wrap:anywhere}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 0 18px}
.stat{background:var(--panel);border:1px solid var(--rule);border-radius:4px;padding:10px 12px}
.stat .k{color:var(--muted);font-size:.8rem}.stat .v{font-size:1.25rem;font-weight:500}.stat .s{color:var(--muted);font-size:.8rem}
details.notes{background:var(--warn-bg);border-left:3px solid var(--c2);padding:10px 16px;margin:0 0 20px;border-radius:2px}
details.notes summary{cursor:pointer;font-weight:600}
details.notes p{margin:8px 0 0;max-width:90ch}
details.notes p.info{color:var(--muted)}
.top{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:14px;margin-bottom:14px}
@media (max-width:820px){.top{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--rule);border-radius:4px;padding:12px 12px 4px}
.stack section{margin-bottom:14px}
h2{font-size:1rem;font-weight:600;margin:0 2px 2px}
.cap{color:var(--muted);font-size:.85rem;margin:0 2px 4px}
.plot{width:100%;height:230px}
#p-track{height:440px}
.bar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 10px}
.readout{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.85rem;color:var(--muted)}
button{font:inherit;font-size:.85rem;color:var(--ink);background:var(--panel);border:1px solid var(--rule);border-radius:3px;padding:4px 10px;cursor:pointer}
button:focus-visible{outline:2px solid var(--c1);outline-offset:2px}
.downloads{margin:0 0 18px;font-size:.9rem}
footer{color:var(--muted);font-size:.85rem;margin-top:10px}
</style>
</head>
<body>
<main>
<p class="downloads"><a href="../">← All flights</a></p>
<h1>__H1__</h1>
<p class="sub">__SUB__</p>
<div class="stats">
__STATS__
</div>
__NOTES__
<p class="downloads">Download: __DOWNLOADS__</p>
<div class="bar"><span class="readout" id="readout">Hover a plot to read values.</span><button id="reset" type="button">Reset zoom</button></div>
<div class="top">
<section><h2>Ground track</h2><p class="cap">Metres from home, equal scale. Colour is time.</p><div id="p-track" class="plot"></div></section>
<div class="stack">
<section><h2>Relative altitude</h2><div id="p-alt" class="plot"></div></section>
<section><h2>Groundspeed and climb rate</h2><div id="p-gs" class="plot"></div></section>
</div>
</div>
<section style="margin-bottom:14px"><h2>3D trajectory</h2><p class="cap">Metres from home; height relative to takeoff, vertical scale exaggerated. Drag to rotate, scroll to zoom.</p><div id="p-3d" class="plot" style="height:520px"></div></section>
<div class="stack">
__WIND__
<section><h2>Attitude</h2><p class="cap">Roll and pitch in degrees.</p><div id="p-att" class="plot"></div></section>
<section><h2>Battery</h2><p class="cap">Voltage (left axis), current (right axis)</p><div id="p-bat" class="plot"></div></section>
<section><h2>Motor outputs</h2><p class="cap">SRV1–4 PWM, µs</p><div id="p-mot" class="plot"></div></section>
<section><h2>Vibration</h2><p class="cap">m/s²</p><div id="p-vib" class="plot"></div></section>
<section><h2>EKF variances</h2><p class="cap">Dotted line: ArduPilot's default failsafe threshold (0.8)</p><div id="p-ekf" class="plot"></div></section>
</div>
<footer>__FOOTER__</footer>
</main>
<script>
const MODES=__MODES__;
const P=__DATA__;const D=P.D,W=P.W;
const TS=['p-alt','p-gs','p-att','p-bat','p-mot','p-vib','p-ekf'].concat(W?['p-wind']:[]);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const cfg={responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']};
function axis(extra){return Object.assign({gridcolor:css('--grid'),zerolinecolor:css('--rule'),linecolor:css('--rule'),tickfont:{color:css('--muted')},title:{font:{color:css('--muted')}}},extra||{});}
function base(extra){
  const shapes=MODES.filter(m=>m[2]==='AUTO').map(m=>({type:'rect',xref:'x',yref:'paper',x0:m[0],x1:m[1],y0:0,y1:1,fillcolor:css('--band'),line:{width:0},layer:'below'}));
  const span=D.t[D.t.length-1]-D.t[0];
  const ann=MODES.filter(m=>m[1]-m[0]>span/12&&m[2]!=='—').map(m=>({x:(m[0]+m[1])/2,y:1,xref:'x',yref:'paper',yanchor:'top',text:m[2],showarrow:false,font:{size:10,color:css('--muted')}}));
  return Object.assign({margin:{l:56,r:56,t:30,b:36},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
    font:{family:'IBM Plex Sans, system-ui, sans-serif',size:12,color:css('--ink')},
    xaxis:axis({title:{text:'time [s]'}}),yaxis:axis(),shapes,annotations:ann,
    legend:{orientation:'h',x:1,xanchor:'right',y:1,yanchor:'bottom',bgcolor:'rgba(0,0,0,0)',font:{size:11}},
    hovermode:'x unified',hoverlabel:{bgcolor:css('--panel'),bordercolor:css('--rule'),font:{color:css('--ink')}}},extra||{});
}
const L=(y,name,c,o)=>Object.assign({x:D.t,y,name,type:'scatter',mode:'lines',line:{color:c,width:1.3}},o||{});
const hmax=Math.max(5,...D.alt.filter(v=>v!==null));
let xr=null;
function draw(){
  const c1=css('--c1'),c2=css('--c2'),c3=css('--c3'),c4=css('--c4');
  const tr={x:D.E,y:D.N,type:'scatter',mode:'markers',name:'track',marker:{size:3,color:D.t,colorscale:'Viridis',showscale:true,colorbar:{title:{text:'s',font:{color:css('--muted')}},thickness:10,tickfont:{color:css('--muted')},len:.8}},
    customdata:D.t.map((t,i)=>[t,D.alt[i],D.gs[i]]),hovertemplate:'t %{customdata[0]:.1f} s<br>E %{x:.1f} m, N %{y:.1f} m<br>alt %{customdata[1]:.1f} m, gs %{customdata[2]:.1f} m/s<extra></extra>'};
  const home={x:[0],y:[0],type:'scatter',mode:'markers',name:'home',marker:{symbol:'triangle-up',size:13,color:c4},hovertemplate:'home<extra></extra>'};
  const sel=[];
  if(xr){const i0=D.t.findIndex(t=>t>=xr[0]),i1=D.t.findIndex(t=>t>xr[1]);const j=i1<0?D.t.length:i1;
    if(i0>=0)sel.push({x:D.E.slice(i0,j),y:D.N.slice(i0,j),type:'scatter',mode:'lines',name:'zoomed range',line:{color:c4,width:4},hoverinfo:'skip'});}
  Plotly.react('p-track',[tr,home,...sel],{margin:{l:52,r:10,t:10,b:40},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
    font:{family:'IBM Plex Sans, system-ui, sans-serif',size:12,color:css('--ink')},showlegend:false,
    xaxis:axis({title:{text:'east [m]'}}),yaxis:axis({title:{text:'north [m]'},scaleanchor:'x',scaleratio:1}),
    hoverlabel:{bgcolor:css('--panel'),bordercolor:css('--rule'),font:{color:css('--ink')}}},cfg);
  // 3D: one coloured segment per flight-mode run
  const pal=[c1,c2,c3,c4,css('--muted')],names=[...new Set(D.mode)],cm={};names.forEach((n,i)=>cm[n]=n==='—'?css('--muted'):pal[i%4]);
  const segs=[],seen=new Set();let st=0;
  for(let i=1;i<=D.mode.length;i++){if(i===D.mode.length||D.mode[i]!==D.mode[st]){const a=Math.max(0,st-1),m=D.mode[st];
    segs.push({type:'scatter3d',mode:'lines',name:m,legendgroup:m,showlegend:!seen.has(m),x:D.E.slice(a,i),y:D.N.slice(a,i),z:D.alt.slice(a,i),
      customdata:D.t.slice(a,i),line:{color:cm[m],width:6},hovertemplate:'t %{customdata:.1f} s<br>E %{x:.0f} m, N %{y:.0f} m<br>h %{z:.1f} m<extra>'+m+'</extra>'});seen.add(m);st=i;}}
  const shadow={type:'scatter3d',mode:'lines',name:'ground track',x:D.E,y:D.N,z:D.alt.map(()=>0),line:{color:css('--rule'),width:3},hoverinfo:'skip'};
  const dx=[],dy=[],dz=[],every=Math.max(1,Math.round(5/((D.t[1]-D.t[0])||0.1)));
  for(let i=0;i<D.alt.length;i+=every){if(D.alt[i]>1){dx.push(D.E[i],D.E[i],null);dy.push(D.N[i],D.N[i],null);dz.push(0,D.alt[i],null);}}
  const drops={type:'scatter3d',mode:'lines',name:'drop lines (5 s)',x:dx,y:dy,z:dz,line:{color:css('--rule'),width:2},hoverinfo:'skip'};
  const hm={type:'scatter3d',mode:'markers',name:'home',x:[0],y:[0],z:[0],marker:{size:5,color:c4,symbol:'diamond'},hovertemplate:'home<extra></extra>'};
  const sa=a=>Object.assign(axis(a),{backgroundcolor:'rgba(0,0,0,0)',showbackground:false});
  const ex=v=>v.filter(x=>x!==null),span=a=>Math.max(1,Math.max(...ex(a))-Math.min(...ex(a)));
  const sx=span(D.E),sy=span(D.N),big=Math.max(sx,sy);
  Plotly.react('p-3d',[shadow,drops,...segs,hm],{margin:{l:0,r:0,t:0,b:0},paper_bgcolor:'rgba(0,0,0,0)',font:{family:'IBM Plex Sans, system-ui, sans-serif',size:12,color:css('--ink')},
    legend:{orientation:'h',x:0,y:1,bgcolor:'rgba(0,0,0,0)'},uirevision:'3d',
    scene:{xaxis:sa({title:{text:'east [m]'}}),yaxis:sa({title:{text:'north [m]'}}),zaxis:sa({title:{text:'height [m]'},range:[0,hmax*1.15]}),
      aspectmode:'manual',aspectratio:{x:1.2*sx/big,y:1.2*sy/big,z:0.36},camera:{eye:{x:1.35,y:-1.3,z:0.75},center:{x:0,y:0,z:-0.15}}},
    hoverlabel:{bgcolor:css('--panel'),bordercolor:css('--rule'),font:{color:css('--ink')}}},cfg);
  const X=xr?{range:xr}:{range:[D.t[0],D.t[D.t.length-1]]};
  const B=(ex)=>{const b=base(ex);b.xaxis=Object.assign(b.xaxis,X);return b;};
  Plotly.react('p-alt',[L(D.alt,'alt [m]',c1)],B({yaxis:axis({title:{text:'m'},rangemode:'tozero'}),showlegend:false}),cfg);
  Plotly.react('p-gs',[L(D.gs,'groundspeed',c1),L(D.vz,'climb rate',c2)],B({yaxis:axis({title:{text:'m/s'}})}),cfg);
  Plotly.react('p-att',[L(D.roll,'roll',c1),L(D.pitch,'pitch',c2)],B({yaxis:axis({title:{text:'deg'}})}),cfg);
  Plotly.react('p-bat',[L(D.V,'voltage',c1),L(D.I,'current',c4,{yaxis:'y2',line:{color:c4,width:1}})],
    B({yaxis:axis({title:{text:'V'}}),yaxis2:axis({title:{text:'A'},overlaying:'y',side:'right',showgrid:false,rangemode:'tozero'})}),cfg);
  Plotly.react('p-mot',[L(D.m1,'SRV1',c1),L(D.m2,'SRV2',c2),L(D.m3,'SRV3',c3),L(D.m4,'SRV4',c4)],B({yaxis:axis({title:{text:'µs'}})}),cfg);
  Plotly.react('p-vib',[L(D.vx,'X',c1),L(D.vy,'Y',c2),L(D.vzb,'Z',c3)],B({yaxis:axis({title:{text:'m/s²'},rangemode:'tozero'})}),cfg);
  Plotly.react('p-ekf',[L(D.ev,'velocity',c1),L(D.eph,'pos horiz',c3),L(D.epv,'pos vert',c2),L(D.ec,'compass',c4)],
    B({yaxis:axis({title:{text:'variance'},rangemode:'tozero'}),shapes:base().shapes.concat([{type:'line',xref:'paper',x0:0,x1:1,y0:.8,y1:.8,line:{color:c4,width:1,dash:'dot'}}])}),cfg);
  if(W)Plotly.react('p-wind',[{x:W.t,y:W.spd,name:'speed',type:'scatter',mode:'lines',line:{color:c1,width:1.3}},
      {x:W.t,y:W.dir,name:'direction',type:'scatter',mode:'markers',yaxis:'y2',marker:{color:c2,size:3}}],
    B({yaxis:axis({title:{text:'m/s'},rangemode:'tozero'}),yaxis2:axis({title:{text:'deg'},overlaying:'y',side:'right',showgrid:false,range:[0,360],dtick:90})}),cfg);
}
let busy=false;
function nearest(a,x){let lo=0,hi=a.length-1;while(hi-lo>1){const m=(lo+hi)>>1;if(a[m]<x)lo=m;else hi=m;}return Math.abs(a[lo]-x)<=Math.abs(a[hi]-x)?lo:hi;}
function hook(){
  TS.forEach(id=>{const el=document.getElementById(id);
    el.on('plotly_relayout',ev=>{if(busy)return;
      if(ev['xaxis.range[0]']!==undefined)xr=[ev['xaxis.range[0]'],ev['xaxis.range[1]']];
      else if(ev['xaxis.autorange'])xr=null; else return;
      busy=true;draw();busy=false;});
    el.on('plotly_hover',ev=>{const i=nearest(D.t,ev.points[0].x);
      let s=`t ${D.t[i].toFixed(2)} s | UTC ${D.utc[i]} | ${D.mode[i]} | alt ${D.alt[i]} m | gs ${D.gs[i]} m/s | ${D.V[i]} V ${D.I[i]} A | ${D.mah[i]} mAh | sats ${D.sats[i]} hdop ${D.hdop[i]}`;
      if(W&&W.t.length){const j=nearest(W.t,D.t[i]);if(Math.abs(W.t[j]-D.t[i])<1)s+=` | wind ${W.spd[j]} m/s @ ${W.dir[j]}°`;}
      document.getElementById('readout').textContent=s;});
  });
}
if(window.Plotly){
  draw();hook();
  document.getElementById('reset').addEventListener('click',()=>{xr=null;busy=true;draw();busy=false;});
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{busy=true;draw();busy=false;});
  new MutationObserver(()=>{busy=true;draw();busy=false;}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
}else{
  document.querySelectorAll('.plot').forEach(el=>{el.style.height='auto';el.textContent='The plotting library did not load. Check your connection and reload.';});
}
</script>
</body>
</html>
"""
