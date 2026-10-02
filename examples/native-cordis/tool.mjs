import { defineTool } from '@deepseek-ai/dsh-tools';
export const name='native-example-tool';
export const inject=['tools','nativeCounter','microMulti'];
export function apply(ctx) {
 let observed=0;
 ctx.on('native-example/tick',value=>{observed=value;});
 ctx.tools.register(defineTool({
  name:'native_counter',description:'Increment a real Cordis service and observe its event.',
  parameters:{label:{type:'string',required:true}},
  output:{schema:{type:'object',additionalProperties:false,properties:{value:{type:'number',required:true},event:{type:'number',required:true},label:{type:'string',required:true},workspace:{type:'string',required:true}}},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
  async execute(args){return {value:ctx.nativeCounter.next(),event:observed,label:args.label,workspace:ctx.microMulti.workspace};}
 }));
}
