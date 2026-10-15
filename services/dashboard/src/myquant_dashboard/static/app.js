"use strict";
const $ = selector => document.querySelector(selector);
let data = null, activeTab = "signals", csrf = "", loading = false, curveMode = "net_liq";
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const number = value => value == null ? "—" : new Intl.NumberFormat("zh-CN", {maximumFractionDigits:2}).format(value);
const stamp = value => value ? new Intl.DateTimeFormat("zh-CN", {year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(new Date(value)) : "尚未同步";
function money(value, currency) { return value == null ? "—" : `${currency === "USD" ? "$" : (currency || "")} ${number(value)}`; }
function text(selector, value) { $(selector).textContent = value; }
function pnl(selector, value, currency) { const node=$(selector); node.textContent=money(value,currency); node.classList.toggle("positive",value>0);node.classList.toggle("negative",value<0); }
function cell(value, className) { const td=document.createElement("td");td.textContent=value; if(className) td.className=className;return td; }
const actionName = value => ({BUY:"买入",SELL:"卖出"}[value]||"方向待核对");
function reason(value) { const td=document.createElement("td");td.className="reason";const details=document.createElement("details"),summary=document.createElement("summary"),p=document.createElement("p");summary.textContent="查看策略原因";p.textContent=value||"无本项目策略关联，不推断操作原因";details.append(summary,p);td.append(details);return td; }
const names={PLANNED:"计划 · 未提交",SUBMITTING:"提交中",PRE_SUBMITTED:"券商预接受",SUBMITTED:"已提交 · 未全成",PARTIALLY_FILLED:"部分成交",FILLED:"券商报告已成交",CANCELLED:"已取消",REJECTED:"被拒绝",UNKNOWN:"待核对",PENDING_CANCEL:"撤单待确认"};
function statusCell(value) {const td=document.createElement("td"),span=document.createElement("span");span.textContent=names[value]||value;span.className="badge"+(value==="UNKNOWN"?" warning":value==="FILLED"?" good":"");td.append(span);return td;}
function renderRecords(){
  if(!data)return;
  const rows=data[activeTab]||[],head=$("#record-head"),body=$("#records");head.replaceChildren();body.replaceChildren();
  const headers=activeTab==="signals"?["收盘数据日","股票","目标仓位","快 / 慢均线","记录时间","策略原因"]:activeTab==="orders"?["股票 / 方向","订单状态","订单量 / 已成量","限价","状态更新时间","策略原因"]:["实际成交时间","股票 / 方向","成交数量","成交价格","手续费","策略原因"];
  const tr=document.createElement("tr");for(const title of headers){const th=document.createElement("th");th.textContent=title;tr.append(th);}head.append(tr);
  for(const row of rows){const tr=document.createElement("tr");
    if(activeTab==="signals")tr.append(cell(row.session),cell(row.symbol),cell(`${(row.target*100).toFixed(0)}%`),cell(`${number(row.fast)} / ${number(row.slow)}`),cell(stamp(row.created_at)),reason(row.reason));
    else if(activeTab==="orders")tr.append(cell(`${row.symbol} · ${actionName(row.action)}`),statusCell(row.status),cell(`${row.quantity?number(row.quantity):"待同步"} / ${number(row.filled)}`),cell(money(row.limit_price,"USD")),cell(stamp(row.updated_at)),reason(row.reason));
    else tr.append(cell(stamp(row.executed_at)),cell(`${row.symbol} · ${actionName(row.action)}`),cell(number(row.quantity)),cell(money(row.price,"USD")),cell(row.commission==null?"待券商回报":money(row.commission,row.commission_currency)),reason(row.reason));
    body.append(tr);
  }
  $("#records-empty").hidden=rows.length>0;
  text("#record-note",(activeTab==="signals"?"信号是判断，不等于已经提交订单。":activeTab==="orders"?"订单状态由券商报告，实际成交明细以执行回报为准。":"仅展示真实执行回报；一张订单可对应多笔成交。")+` 当前显示最近 ${rows.length} 条，累计 ${data.counts[activeTab]||0} 条。`);
  $("#export").href=`/api/export/${activeTab}.csv`;
}
function svgNode(name, attrs={}, content){const node=document.createElementNS("http://www.w3.org/2000/svg",name);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);if(content!=null)node.textContent=content;return node;}
function chart(){
 const svg=$("#equity-chart");let history=(data.history||[]).filter(row=>row[curveMode]!=null);
 if(curveMode==="daily_pnl"&&history.length){const nyDay=value=>new Intl.DateTimeFormat("en-CA",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(value));const day=nyDay(history[history.length-1].observed_at);history=history.filter(row=>nyDay(row.observed_at)===day);}
 text("#curve-note",curveMode==="daily_pnl"?"IBKR 当日盈亏读数，每日重置；显示最近纽约日期，不拼接为累计收益。":"资产变动率未剔除出入金，不等于策略投资回报。");text("#curve-legend",curveMode==="daily_pnl"?"券商当日盈亏":"账户净资产");text("#chart-empty",curveMode==="daily_pnl"?"券商尚未回报当日盈亏。":"当前没有可显示的账户数据，等待 IBKR 同步。");svg.replaceChildren();svg.toggleAttribute("hidden",!history.length);$("#chart-empty").hidden=!!history.length;
 if(!history.length){text("#asset-change","—");return;}
 const first=history[0][curveMode],last=history[history.length-1][curveMode],change=curveMode==="net_liq"?(first?last/first-1:0):last;text("#asset-change",curveMode==="net_liq"?`${change>=0?"+":""}${(change*100).toFixed(2)}%`:money(last,data.account?.currency));$("#asset-change").className=change>=0?"positive":"negative";
 const left=62,right=870,top=22,bottom=235,t0=new Date(history[0].observed_at).getTime(),t1=new Date(history[history.length-1].observed_at).getTime();
 const values=history.map(r=>r[curveMode]),lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.15,Math.abs(hi)*.005,1),min=lo-pad,max=hi+pad;
 const x=t=>left+(new Date(t).getTime()-t0)/Math.max(t1-t0,1)*(right-left),y=v=>bottom-(v-min)/(max-min)*(bottom-top);
 for(let i=0;i<4;i++){const value=min+(max-min)*i/3,yy=y(value);svg.append(svgNode("line",{x1:left,x2:right,y1:yy,y2:yy,stroke:"#e8efed"}),svgNode("text",{x:left-10,y:yy+4,"text-anchor":"end",fill:"#82948f","font-size":"11"},number(value)));}
 const points=history.map(r=>`${x(r.observed_at)},${y(r[curveMode])}`);svg.append(svgNode("polyline",{points:points.join(" "),fill:"none",stroke:"#10776d","stroke-width":"2.5","stroke-linejoin":"round"}));
 if(history.length===1)svg.append(svgNode("circle",{cx:left,cy:y(first),r:4,fill:"#10776d"}));
 for(const event of [...(data.signals||[]).slice(0,50).map(s=>({...s,when:s.created_at,kind:"signal"})),...(data.fills||[]).map(f=>({...f,when:f.executed_at,kind:"fill"}))]){
  const time=new Date(event.when).getTime();if(time<t0||time>t1)continue;const nearest=history.reduce((a,b)=>Math.abs(new Date(a.observed_at)-time)<Math.abs(new Date(b.observed_at)-time)?a:b),xx=x(event.when),yy=y(nearest[curveMode]);
  const color=event.kind==="signal"?"#839a96":event.action==="BUY"?"#10776d":"#c35363";
  const marker=event.kind==="signal"?svgNode("path",{d:`M ${xx} ${yy-5} l 5 5 -5 5 -5 -5 Z`,fill:"white",stroke:color}):event.action==="BUY"?svgNode("circle",{cx:xx,cy:yy,r:4,fill:color,stroke:"white","stroke-width":1}):svgNode("path",{d:`M ${xx-5} ${yy-4} l 10 0 -5 9 Z`,fill:color,stroke:"white","stroke-width":1});
  marker.append(svgNode("title",{},event.kind==="signal"?`${event.symbol} 信号：${event.reason}`:`${event.symbol} ${actionName(event.action)} ${number(event.quantity)} 股，成交价 ${money(event.price,"USD")}\n${stamp(event.when)}\n${event.reason||"券商导入成交"}`));svg.append(marker);
 }
 for(const [at,anchor] of [[history[0].observed_at,"start"],[history[history.length-1].observed_at,"end"]])svg.append(svgNode("text",{x:anchor==="start"?left:right,y:267,"text-anchor":anchor,fill:"#82948f","font-size":"11"},stamp(at)));
}
function render(){
 const account=data.account,worker=data.worker||{},fresh=worker.heartbeat_at&&(Date.now()-new Date(worker.heartbeat_at))<180000,accountFresh=!account||Date.now()-new Date(account.updated_at)<180000,online=worker.connected&&fresh&&accountFresh;
 text("#status",online?"后台已连接":worker.connected?"数据延迟":"IBKR 未连接");$("#status").className="status"+(online?" connected":"");text("#worker-message",worker.message||"等待后台同步");text("#updated",`账户数据：${stamp(account?.updated_at)} · 后台心跳：${stamp(worker.heartbeat_at)}`);
 const currency=account?.currency;text("#currency",currency||"");text("#net-liq",money(account?.net_liq,currency));text("#cash",money(account?.cash,currency));pnl("#unrealized",account?.unrealized_pnl,currency);pnl("#realized",account?.realized_pnl,currency);text("#account-id",account?`模拟账户 ${account.account}`:"等待 IBKR 模拟账户");
 for(const [key,table] of [["#signal-count","signals"],["#order-count","orders"],["#fill-count","fills"]])text(key,number(data.counts[table]||0));
 text("#execution-mode",worker.orders_enabled?"模拟自动执行已启用":"仅监控 · 模拟下单未启用");text("#strategy-budget",account?`策略预算 ${money(account.strategy_budget_usd,"USD")}`:"");text("#signal-date",worker.latest_completed_session?`最近已收盘日线 ${worker.latest_completed_session}`:"");
 const positions=account?.positions||[],body=$("#positions");body.replaceChildren();for(const row of positions){const tr=document.createElement("tr");tr.append(cell(row.symbol),cell(number(row.quantity)),cell(money(row.average_cost,row.currency)),cell(money(row.market_price,row.currency)),cell(money(row.market_value,row.currency)),cell(money(row.unrealized_pnl,row.currency),row.unrealized_pnl>=0?"positive":"negative"));body.append(tr);}
 $("#positions-empty").hidden=positions.length>0;text("#positions-empty",account?"当前券商回报没有持仓。":"等待 IBKR 账户同步，不以零余额代替缺失数据。");text("#position-count",account?`${positions.length} 个持仓 · ${stamp(account.updated_at)}`:"尚未同步");chart();renderRecords();
}
async function refresh(){if(loading)return;loading=true;$("#refresh").disabled=true;try{const response=await fetch("/api/state",{cache:"no-store"});if(response.status===401){location.assign("/login");return;}if(!response.ok)throw new Error("unavailable");data=await response.json();render();$("#network-error").hidden=true;}catch{$("#network-error").hidden=false;}finally{loading=false;$("#refresh").disabled=false;}}
$("#timezone").textContent=`显示时区 ${zone}`;$("#refresh").addEventListener("click",refresh);
for(const button of document.querySelectorAll("[data-tab]"))button.addEventListener("click",()=>{activeTab=button.dataset.tab;for(const tab of document.querySelectorAll("[data-tab]"))tab.setAttribute("aria-selected",String(tab===button));renderRecords();});
$("#logout").addEventListener("click",async()=>{const response=await fetch("/logout",{method:"POST",headers:{"X-CSRF-Token":csrf}});if(response.ok)location.assign("/login");});
fetch("/api/me").then(r=>r.ok?r.json():Promise.reject()).then(user=>{csrf=user.csrf;text("#user",user.username);}).catch(()=>location.assign("/login"));refresh();setInterval(refresh,10000);

for(const button of document.querySelectorAll("[data-curve]"))button.addEventListener("click",()=>{curveMode=button.dataset.curve;for(const other of document.querySelectorAll("[data-curve]"))other.setAttribute("aria-pressed",String(other===button));if(data)chart();});
