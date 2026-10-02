/** Application transport around the official AgentLoop and SubagentRuntime. */
import {randomUUID} from 'node:crypto';
import {LlmAdapter} from '@deepseek-ai/dsh-llm';

const bridges=new Map();
export function receiveBridge(packet){
 const pending=bridges.get(packet.bridgeId);
 if(!pending)return;
 if(packet.action==='bridge-chunk'){pending.queue.push(packet.chunk);pending.wake?.();return;}
 pending.done=true;pending.error=packet.error;pending.result=packet.result;pending.wake?.();
}
async function* bridge(write,requestId,kind,data,signal){
 const bridgeId=randomUUID(),pending={queue:[],done:false};bridges.set(bridgeId,pending);
 const abort=()=>{pending.done=true;pending.error='Operation cancelled';pending.wake?.();};
 signal?.addEventListener('abort',abort,{once:true});
 try{
  if(signal?.aborted)throw signal.reason??Error('Cancelled');
  write({event:'bridge',requestId,bridgeId,kind,data});
  while(!pending.done||pending.queue.length){
   while(pending.queue.length)yield pending.queue.shift();
   if(!pending.done)await new Promise(resolve=>{pending.wake=resolve;});
  }
  if(pending.error)throw Error(pending.error);
  return pending.result;
 }finally{signal?.removeEventListener('abort',abort);bridges.delete(bridgeId);}
}
async function bridgeValue(write,id,kind,data,signal){
 const iterator=bridge(write,id,kind,data,signal);
 while(true){const next=await iterator.next();if(next.done)return next.value;}
}
export async function runNativeChat(root,request,write,controllers){
 const controller=new AbortController();controllers.set(String(request.id),controller);
 const signal=controller.signal,children=new Map(),childIds=new Map();
 let main,steps=0;
 const nativeNames=new Set(root.tools.schemas().map(tool=>tool.name));
 const receipts=new Map(),noEvidenceRetries=new Map();
 const event=(kind,data)=>write({event:'chat-event',requestId:request.id,kind,data});
 const owned=agent=>agent?.id===main?.agent.id||childIds.has(agent?.id);
 const disposers=[];
 class ApplicationAdapter extends LlmAdapter{
  async *stream(options){
   yield* bridge(write,request.id,'model',{...options,signal:undefined},options.signal);
  }
 }
 const provider='micro-multi-'+request.id;
 const adapterDispose=root.llm.registerAdapter([provider],new ApplicationAdapter());
 disposers.push(adapterDispose);
 const progress=(id,status,detail)=>{
  const name=childIds.get(id)??id;
  event('subagent_progress',{agent_id:name,native_agent_id:id,agent_name:name,role:name,status,detail,thinking:detail,progress_pct:status==='completed'?100:status==='failed'?0:30});
 };
 const consumeReady=()=>{
  const reports=[];
  for(const [name,entry] of children)if(entry.report){reports.push(entry.report);children.delete(name);}
  return {reports,pending:[...children.keys()]};
 };
 const start=async(args,exec)=>{
  if(exec.agent?.id!==main.agent.id)throw Error('Nested delegation is not enabled for this turn');
  const tasks=args.tasks;
  if(!Array.isArray(tasks)||!tasks.length||tasks.length>64)throw Error('Invalid independent task batch');
  const names=new Set();
  for(const task of tasks){
   if(typeof task.subagent_name!=='string'||!task.subagent_name.trim()||typeof task.prompt!=='string'||!task.prompt.trim()||names.has(task.subagent_name)||children.has(task.subagent_name))throw Error('Invalid or duplicate child');
   names.add(task.subagent_name);
  }
  for(const task of tasks){
   const entry={};children.set(task.subagent_name,entry);
   entry.promise=(async()=>{
    let run;
    try{
     // Queue only excess work; every admitted child uses the native provider.
     while([...children.values()].filter(item=>item.active).length>=request.maxConcurrency){
      await Promise.race([...children.values()].filter(item=>item.active).map(item=>item.promise));
      if(signal.aborted)throw Error('Cancelled');
     }
     entry.active=true;
     run=await root.subagents.start('spawn',{parent:main.agent,prompt:[{type:'text',text:task.prompt}],signal,
      agentOptions:{provider,model:request.model,maxTokens:Math.min(request.maxTokens,4096)},
      persona:'Execute the assigned task directly. Coordinate file ownership. Use necessary checks, avoid repeated planning and review. Return a concise report of changes, evidence, and unresolved issues.',
      maxDepth:1});
     childIds.set(run.id,task.subagent_name);progress(run.id,'running',task.prompt);
     const result=await run.result;
     entry.report={subagent_name:task.subagent_name,status:result.stopReason==='completed'?'completed':'failed',summary:(result.output??[]).filter(block=>block.type==='text').map(block=>block.text).join('\n'),native_session_id:run.id,stop_reason:result.stopReason};
     progress(run.id,entry.report.status,entry.report.summary||result.stopReason);
    }catch(error){entry.report={subagent_name:task.subagent_name,status:'failed',error:String(error.message??error)};
     progress(run?.id??task.subagent_name,'failed',entry.report.error);
    }finally{entry.active=false;await run?.dispose();}
   })();
  }
  event('team',{conversation_id:request.conversationId,status:'approved',workflow_state:'running',agents:[...children.keys()].map(name=>({id:name,name,role:name,status:'running'}))});
  return {status:'started',subagents:[...names],background:true,runtime:'native-subagent'};
 };
 const wait=async(args)=>{
  if(children.size&&![...children.values()].some(entry=>entry.report)){
   const timeout=Math.max(0,Math.min(30,Number(args.timeout_seconds??10)))*1000;
   let timer;try{await Promise.race([...children.values()].map(entry=>entry.promise).concat(new Promise(resolve=>{timer=setTimeout(resolve,timeout);})));}finally{clearTimeout(timer);}
  }
  return consumeReady();
 };
 const setup=async ctx=>{
  ctx.systemPrompt.section({name:'deployment:persona-prefix',order:-100,text:request.system,interpolate:false});
  for(const schema of request.tools){
   const fn=schema.function;
   if(root.tools.schemas().some(tool=>tool.name===fn.name))continue;
   const execute=fn.name==='start_subagents'?start:fn.name==='wait_subagents'?wait:
    async(args,exec)=>{
     const value=await bridgeValue(write,request.id,'tool',{name:fn.name,arguments:args,agentId:exec.agent?.id},exec.signal);
     if(value?.error)throw Error(value.error);
     return value?.text??value;
    };
   ctx.tools.register({name:fn.name,description:fn.description,parameters:fn.parameters,
    output:{schema:{},render:(_args,value)=>[{type:'text',text:typeof value==='string'?value:JSON.stringify(value)}]},execute});
  }
 };
 disposers.push(root.on('tools/pre-execute',async(exec,next)=>{
  if(!owned(exec.agent))return next();
  if(nativeNames.has(exec.name)){
   const allowed=await bridgeValue(write,request.id,'authorize',{name:exec.name,arguments:exec.arguments,agentId:exec.agent?.id},exec.signal);
   if(!allowed)throw Error('User did not approve this operation');
  }
  event('native-tool',{name:exec.name,arguments:JSON.stringify(exec.arguments),agent_id:childIds.get(exec.agent?.id)??exec.agent?.id,status:'running'});
  return next();
 }));
 disposers.push(root.on('tools/result',(exec,result)=>{
  if(!owned(exec.agent))return;
  if(!result.isError)receipts.set(exec.agent.id,(receipts.get(exec.agent.id)??0)+1);
  event('native-tool',{name:exec.name,arguments:JSON.stringify(exec.arguments),agent_id:childIds.get(exec.agent?.id)??exec.agent?.id,status:'complete',result:result.isError?JSON.stringify(result.error):typeof result.value==='string'?result.value:JSON.stringify(result.value),native_result:result});
 }));
 disposers.push(root.on('agent/pre-finish',payload=>{
  if(!owned(payload.agent)||!request.requiresExecution||receipts.has(payload.agent.id))return;
  const count=noEvidenceRetries.get(payload.agent.id)??0;
  if(count>=2)return;
  noEvidenceRetries.set(payload.agent.id,count+1);
  payload.agent.steer({id:randomUUID(),role:'user',source:{kind:'user'},content:[{type:'text',text:'No successful execution evidence exists. Execute the requested changes with tools now; do not report delivery from prose alone.'}]});
 }));
 disposers.push(root.on('agent/assistant-stream',payload=>{
  if(!owned(payload.agent)||payload.frame.type!=='chunk')return;
  const chunk=payload.frame.chunk;
  if(payload.agent.id===main.agent.id){
   if(chunk.type==='text-delta')event('delta',{content:chunk.text});
   if(chunk.type==='reasoning-delta')event('thinking',{content:chunk.text,status:'streaming'});
  }else if(chunk.type==='text-delta'||chunk.type==='reasoning-delta')progress(payload.agent.id,'running',chunk.text);
 }));
 disposers.push(root.on('agent/pre-step',async function(payload,next){
  if(!owned(payload.agent))return next();
  if(signal.aborted||++steps>request.maxSteps){payload.agent.cancel('user');return {kind:'reject'};}
  const ready=payload.agent.id===main.agent.id?consumeReady():{reports:[]};
  if(ready.reports.length)payload.agent.inject({id:randomUUID(),role:'user',source:{kind:'user'},content:[{type:'text',text:'Completed child reports: '+JSON.stringify(ready)}]});
  return next();
 }));
 try{
  main=await root.agents.create({sessionId:request.sessionId,meta:{cwd:root.microMulti.workspace},agentOptions:{provider,model:request.model,maxTokens:request.maxTokens},setup});
  if(request.requireSubagent)await start({tasks:[{subagent_name:'task_worker',prompt:'Your only deliverable is a concise, directly usable content or implementation proposal for the lead to implement concurrently. Do not implement the original request, modify shared files, start external agents, or repeat reviews. Return one concrete result and stop. Reference requirements: '+request.prompt}]},{agent:main.agent});
  main.agent.followup({id:randomUUID(),role:'user',source:{kind:'user'},content:[{type:'text',text:request.prompt}]});
  await main.agent.whenIdle();
  while(children.size&&!signal.aborted){
   await Promise.race([...children.values()].map(entry=>entry.promise));
   const reports=consumeReady();
   main.agent.followup({id:randomUUID(),role:'user',source:{kind:'user'},content:[{type:'text',text:'Integrate these completed results and finish the original task: '+JSON.stringify(reports)}]});
   await main.agent.whenIdle();
  }
  const events=main.agent.session.snapshotEvents();
  const terminal=events.filter(event=>event.type==='turn/end').at(-1);
  return {runtime:'native-agent-loop',sessionId:main.agent.id,eventCount:events.length,cancelled:signal.aborted,
   stopReason:terminal?.data?.stopReason,missingExecution:request.requiresExecution&&!receipts.has(main.agent.id)};
 }finally{
  controller.abort();await Promise.allSettled([...children.values()].map(entry=>entry.promise));
  await main?.dispose();for(const dispose of disposers.reverse())dispose();controllers.delete(String(request.id));
 }
}
