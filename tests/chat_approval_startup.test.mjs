import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {buildSync} from 'esbuild';
import {JSDOM} from 'jsdom';

const source = readFileSync('src/masp/web/chat.js', 'utf8') + `
window.testChat = {
  setState(value) { projects=value.projects; profiles=value.profiles; conversations=value.conversations; conversationId=value.conversationId; draftProjectId=value.projectId; team=value.team; teamDirty=false; renderSelectors(); renderTeam(); },
  card(value) { const card=createOrUpdatePlanApprovalCard(null,value); thread.append(card); return card; },
  confirm: confirmAndStartTeamExecution,
  setSend(fn) { send=fn; },
  refreshConversationPlugins,
  setPluginInventory(value) { dshPluginInventory=value; },
  setImport(fn) { importPluginClient=fn; },
};`;
const bundle = buildSync({stdin:{contents:source,resolveDir:resolve('src/masp/web'),sourcefile:'chat.js'},bundle:true,format:'iife',write:false}).outputFiles[0].text;
const dom = new JSDOM(readFileSync('src/masp/web/chat.html','utf8'),{url:'http://localhost:3080',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window;
w.matchMedia=()=>({matches:false,addEventListener(){}});
const reply = value => new Response(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve,30));
let releaseInventory;
const inventory = new Promise(resolve => {releaseInventory=resolve;});
w.fetch=async url=>{
  if(String(url).includes('/dsh/settings')) return reply({general:{locale:'zh-CN'},theme:{mode:'light'}});
  if(String(url).includes('/dsh/plugins')) return inventory;
  return reply([]);
};
try {
  w.eval(bundle);
  await tick(); await tick();
  assert.ok(w.document.querySelector('#thread').textContent.trim(), 'chat must render while plugin inventory is blocked');
  releaseInventory(reply({installed:[],official:[],mcp_servers:[],skills:[]}));
  await tick();

  const makeTeam = version => ({version,status:'draft',requirement:'骑行',main_profile_id:'profile',agents:[{id:'worker',name:'worker',responsibility:'画鹈鹕',owned_paths:['pelican-bicycle.html']}],max_concurrency:2});
  let latest=makeTeam(2), approvals=0, sends=0;
  let finishTurn;
  let saving = new Promise(resolve => { finishTurn=resolve; });
  w.fetch=async (url,options={})=>{
    if(String(url).endsWith('/live')) { await saving; return reply({active:false}); }
    if(String(url).includes('/team/approve')) {
      approvals++; const body=JSON.parse(options.body);
      assert.equal(body.version,latest.version);
      latest={...latest,status:'approved',approval_consumed:false};
      return reply(latest);
    }
    if(String(url).includes('/team?')) return reply(latest);
    return reply([]);
  };
  w.testChat.setState({projects:[{id:'project',name:'Test'}],profiles:[{id:'profile',name:'Test',model:'test'}],conversations:[{id:'conversation',project_id:'project'}],conversationId:'conversation',projectId:'project',team:makeTeam(1)});
  w.testChat.setSend(async (_text,_attachments,options)=>{assert.equal(options.executeTeamNow,true);sends++;});
  const card=w.testChat.card(latest);
  // The card and server agree; a stale local team must not block approval.
  const firstApproval=w.testChat.confirm(2,card);
  const duplicateApproval=w.testChat.confirm(2,card);
  assert.equal(firstApproval,duplicateApproval, 'concurrent confirmation calls share one operation');
  await tick();
  assert.equal(approvals,0, 'approval must wait for the planning turn to finish saving');
  finishTurn(); saving=Promise.resolve();
  await firstApproval;
  assert.equal(approvals,1); assert.equal(sends,1);
  assert.ok(card.textContent.includes('已批准'));

  latest=makeTeam(3);
  const stale=w.testChat.card(makeTeam(2));
  await w.testChat.confirm(2,stale);
  assert.equal(approvals,1); assert.equal(stale.dataset.teamVersion,'3');
  await w.testChat.confirm(3,stale);
  assert.equal(approvals,2); assert.equal(sends,2);

  // A slow first plugin does not serialize other independent client loads.
  let releaseFirst;
  const first=new Promise(resolve=>{releaseFirst=resolve;});
  const mounted=[];
  w.fetch=async url=>{if(String(url).includes('/first/surface'))await first;return reply({available:true,client_revision:'test'});};
  w.testChat.setImport(async id=>({mount:async()=>{mounted.push(id);return async()=>{};}}));
  w.testChat.setPluginInventory({installed:['first','second','third','fourth'].map(id=>({id,enabled:true,runtime:'native-cordis-host'}))});
  const refresh=w.testChat.refreshConversationPlugins();
  await tick();
  assert.ok(mounted.includes('second')); assert.ok(mounted.includes('fourth'));
  assert.ok(!mounted.includes('first'));
  releaseFirst(); await refresh;
  assert.equal(mounted.length,4);
} finally { w.close(); }
console.log('PASS: startup survives blocked plugins; confirmation uses server revision, refreshes stale cards and coalesces concurrent calls; plugin clients load concurrently; no simulated clicks');
