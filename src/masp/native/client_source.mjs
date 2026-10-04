import {parse} from 'acorn';
function walk(node,visit){if(!node||typeof node!=='object')return;visit(node);for(const [key,value] of Object.entries(node)){if(key==='start'||key==='end')continue;if(Array.isArray(value))for(const child of value)walk(child,visit);else if(value&&typeof value.type==='string')walk(value,visit);}}
const keyOf=node=>node?.name??node?.value;
/** Inspect executable syntax, never comments or error-message strings. */
export function clientSource(source){
 const ast=parse(source,{ecmaVersion:'latest',sourceType:'module'}),slots=new Set(),children=new Set(),imports=new Set();
 walk(ast,node=>{
  if(node.type==='CallExpression'&&node.callee.type==='MemberExpression'&&keyOf(node.callee.property)==='inject'&&typeof node.arguments[0]?.value==='string'&&node.arguments[0].value.includes('.'))slots.add(node.arguments[0].value);
  if(node.type==='Property'&&keyOf(node.key)==='children'&&node.value.type==='ObjectExpression')for(const prop of node.value.properties){const key=keyOf(prop.key);if(typeof key==='string'&&key.includes('.'))children.add(key);}
  if(node.type==='Property'&&keyOf(node.key)==='factory'&&['ArrowFunctionExpression','FunctionExpression'].includes(node.value.type)){
   const parameter=node.value.params[0]?.name;
   walk(node.value.body,call=>{if(call.type==='CallExpression'&&call.callee.type==='Identifier'&&[parameter,'require'].includes(call.callee.name)&&typeof call.arguments[0]?.value==='string')imports.add(call.arguments[0].value);});
  }
 });return {slots:[...slots],children:[...children],imports:[...imports]};
}
