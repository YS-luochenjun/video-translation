// Built against the official MCP Apps SDK. Never sends a message on load or events.
import { App } from '../../.runtime/console-ui/ext-apps/package/dist/src/app-with-deps.js';
const app = new App({name:'译制台',version:'0.3.0'}, {}, {autoResize:false});
const host = window.ConsoleHost = {available:false, canSend:false, app};
host.ready = app.connect().then(()=>{
  host.available=true;
  host.canSend=!!app.getHostCapabilities()?.message;
}).catch(()=>{});
host.call = async(name,args)=>{
  await host.ready;
  if(!host.available)throw Error('宿主插件连接不可用；请使用本机控制台和手动交办');
  const result=await app.callServerTool({name,arguments:args});
  if(result.isError)throw Error(result.content?.find(c=>c.type==='text')?.text||'插件接口失败');
  return result.structuredContent||JSON.parse(result.content.find(c=>c.type==='text').text);
};
host.send = async prompt=>{
  await host.ready;
  if(!host.canSend)throw Error('当前宿主没有声明消息交办能力');
  const result=await app.sendMessage({role:'user',content:[{type:'text',text:prompt}]});
  if(result.isError)throw Error('宿主未确认收到交办消息');
};
