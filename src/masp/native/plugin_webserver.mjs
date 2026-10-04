/** Native Node HTTP seam for plugins contributing webServer routes. */
import {renderIndexInjections} from '@deepseek-ai/dsh-host-webserver';
import {Service} from '@deepseek-ai/cordis';
import {createServer,request as httpRequest} from 'node:http';
import {Readable} from 'node:stream';

export default class PluginWebServer extends Service {
 constructor(ctx){
  super(ctx,'webServer');this.routes=new Map();this.indexTaps=[];
  this.server=createServer(async(req,res)=>{
   const path=new URL(req.url,'http://localhost').pathname;
   const route=[...this.routes.values()].find(route=>route.kind==='prefix'?(path===route.path||path.startsWith(route.path+'/')):path===route.path);
   if(!route){
    const connection=this.ctx.get('connection');
    if(!connection?.routes.has(path)){res.writeHead(404);res.end();return;}
    try {
     const headers=Object.fromEntries(Object.entries(req.headers).filter(([,value])=>value!==undefined).map(([key,value])=>[key,Array.isArray(value)?value.join(', '):value]));
     const request=new Request('http://'+(req.headers.host||'localhost')+req.url,{method:req.method,headers,body:['GET','HEAD'].includes(req.method)?undefined:Readable.toWeb(req),duplex:'half'});
     const response=await connection.handleFetch(request);
     res.writeHead(response.status,Object.fromEntries(response.headers));
     if(response.body)Readable.fromWeb(response.body).pipe(res);else res.end();
    }catch(error){if(!res.headersSent)res.writeHead(500);res.end(String(error.message));}
    return;
   }
   try{await route.handler(req,res);}catch(error){if(!res.headersSent)res.writeHead(500);res.end(String(error.message));}
  });
  this.ready=new Promise((resolve,reject)=>{this.server.once('error',reject);this.server.listen(0,'127.0.0.1',resolve);});
  ctx.effect(()=>()=>{this.server.closeAllConnections();this.server.close();});
 }
 register(route){
  if(!route.path?.startsWith('/')||typeof route.handler!=='function')throw Error('Invalid plugin HTTP route');
  const key=Symbol(route.path);
  return this.ctx.effect(()=>{this.routes.set(key,route);return ()=>this.routes.delete(key);});
 }
 tapIndex(transform){return this.ctx.effect(()=>{this.indexTaps.push(transform);return ()=>{this.indexTaps=this.indexTaps.filter(item=>item!==transform);};});}
 collectIndexInjections(){const table=[];this.ctx.emit('webserver/index-inject',table);return table;}
 renderIndex(html){let result=renderIndexInjections(html,this.collectIndexInjections());for(const transform of this.indexTaps)result=transform(result);return result;}
 async request({path,method,headers,body}){
  await this.ready;
  const address=this.server.address();
  return await new Promise((resolve,reject)=>{
   const outgoing=httpRequest({hostname:'127.0.0.1',port:address.port,path,method,headers},response=>{
    const chunks=[];let size=0;
    response.on('data',chunk=>{size+=chunk.length;if(size>25*1024*1024){response.destroy(Error('Plugin HTTP response exceeds 25 MB'));return;}chunks.push(chunk);});
    response.on('error',reject);
    response.on('end',()=>resolve({status:response.statusCode,headers:response.headers,body:Buffer.concat(chunks).toString('base64')}));
   });
   outgoing.on('error',reject);outgoing.setTimeout(60000,()=>outgoing.destroy(Error('Plugin HTTP request timed out')));
   outgoing.end(['GET','HEAD'].includes(method)?undefined:Buffer.from(body??'','base64'));
  });
 }
}
