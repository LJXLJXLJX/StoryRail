// 统一宿主计量网关（原 scripts/evaluation/{gateway,kimi_gateway}.mjs）。
//
// config.mode 必填，必须由调用方显式选择真实 Agent 通道，网关不再静默默认：
// - "openai_responses"：Codex/OpenAI Responses 通道，凭据只在宿主读取；
// - "kimi_messages"：Kimi Coding SSE 通道，解析真实用量。
//
// 两种通道共用授权配置校验、0600 ledger 原子落盘、/health、逐 trial token 门禁与
// 请求体上限；转发前计量、不自动重试、不记录请求/响应正文或凭据。
// kimi_messages 支持可选 `maxRequests`（全局）与 `trials.<id>.maxRequests`（逐 trial）；
// 两者都缺省时保持既有「本轮不限次授权」语义，超限按 402 evaluation_budget_exhausted 拒绝。
//
// 用法：
//   node meter_gateway.mjs <config.json>                    # 启动网关
//   node meter_gateway.mjs --validate-config <config.json>  # 只按所选 mode 校验必需字段，exit 0/1
import http from 'node:http';
import fs from 'node:fs';
import { zstdDecompressSync } from 'node:zlib';
import { pathToFileURL } from 'node:url';

const MODES = ['openai_responses', 'kimi_messages'];

function selectMode(config) {
  if (config.mode === undefined || config.mode === null) {
    throw new Error('缺少 mode：必须显式选择 openai_responses 或 kimi_messages');
  }
  if (!MODES.includes(config.mode)) {
    throw new Error(`无效 mode：${JSON.stringify(config.mode)}；必须显式选择 openai_responses 或 kimi_messages`);
  }
  return config.mode;
}

function optionalLimit(value, label) {
  if (value === undefined || value === null) return;
  if (!Number.isInteger(value) || value <= 0) throw new Error(`授权配置不完整：${label} 必须是正整数`);
}

function validateConfig(config, mode) {
  if (config.authorized !== true) throw new Error('授权配置不完整：authorized 必须为 true');
  if (!Number.isInteger(config.port) || config.port < 0 || config.port > 65535) throw new Error('授权配置不完整：缺少有效 port');
  if (typeof config.ledger !== 'string' || config.ledger === '') throw new Error('授权配置不完整：缺少 ledger');
  if (!config.trials || typeof config.trials !== 'object' || Array.isArray(config.trials) || Object.keys(config.trials).length === 0) throw new Error('授权配置不完整：缺少 trials');
  optionalLimit(config.maxRequests, 'maxRequests');
  for (const [id, trial] of Object.entries(config.trials)) {
    if (trial === null || typeof trial !== 'object' || Array.isArray(trial)) throw new Error(`授权配置不完整：trial ${id} 不是对象`);
    if (typeof trial.token !== 'string' || trial.token === '') throw new Error(`授权配置不完整：trial ${id} 缺少 token`);
    optionalLimit(trial.maxRequests, `trial ${id} 的 maxRequests`);
  }
  if (mode === 'openai_responses') {
    if (config.maxRequests !== 12) throw new Error('授权配置不完整：openai_responses 需要全局 maxRequests === 12');
    if (config.real === true && typeof config.authModule !== 'string') throw new Error('授权配置不完整：真实模式需要 authModule');
    return;
  }
  if (config.limit !== null) throw new Error('缺少本轮不限次授权：kimi_messages 需要 limit === null');
  if (typeof config.authModule !== 'string' || config.authModule === '') throw new Error('授权配置不完整：kimi_messages 需要 authModule');
  if (typeof config.oauthModule !== 'string' || config.oauthModule === '') throw new Error('授权配置不完整：kimi_messages 需要 oauthModule');
}

const args = process.argv.slice(2);
const validateOnly = args[0] === '--validate-config';
let config;
try {
  config = JSON.parse(fs.readFileSync(validateOnly ? args[1] : args[0], 'utf8'));
  validateConfig(config, selectMode(config));
} catch (error) {
  if (validateOnly) {console.error('配置无效：' + error.message);process.exit(1);}
  throw error;
}
if (validateOnly) {
  console.log(JSON.stringify({valid: true, mode: config.mode}));
  process.exit(0);
}
const mode = config.mode;

async function runOpenAiResponses() {
let ledger = fs.existsSync(config.ledger) ? JSON.parse(fs.readFileSync(config.ledger, 'utf8')) : [];
function persist() {
  fs.writeFileSync(config.ledger + '.tmp', JSON.stringify(ledger, null, 2), {mode: 0o600});
  fs.renameSync(config.ledger + '.tmp', config.ledger);
}
const readCredential = config.real ? (await import(pathToFileURL(config.authModule))).readStoredCredential : null;
const server = http.createServer(async (req, res) => {
  const reject = (status, code) => {res.writeHead(status, {'Content-Type':'application/json'});res.end(JSON.stringify({error:{code,message:code}}));};
  if (req.method === 'GET' && req.url === '/health') {
    res.end(JSON.stringify({ready:true, real:config.real, consumed:ledger.length})); return;
  }
  const id = /^\/trial\/([a-z-]+)\/codex\/responses$/.exec(req.url ?? '')?.[1];
  const trial = id && config.trials[id];
  if (req.method !== 'POST' || !trial || req.headers.authorization !== 'Bearer ' + trial.token) {reject(403,'scope_denied');return;}
  let chunks = [], size = 0;
  for await (const chunk of req) {size += chunk.length;if(size > 2_000_000){reject(413,'body_limit');return;}chunks.push(chunk);}
  let body;
  try {const raw=Buffer.concat(chunks);const decoded=req.headers['content-encoding']==='zstd'?zstdDecompressSync(raw,{maxOutputLength:2_000_000}):raw;body=JSON.parse(decoded.toString());} catch {reject(400,'invalid_json');return;}
  if(body.model !== 'gpt-5.6-sol' || body.reasoning?.effort !== 'medium' || body.stream !== true) {reject(400,'model_conditions_changed');return;}
  if(ledger.length >= config.maxRequests || ledger.filter(x=>x.trial===id).length >= trial.maxRequests) {reject(402,'evaluation_budget_exhausted');return;}
  let credential;
  if(config.real) {
    credential=readCredential('openai-codex');
    if(!credential || credential.type!=='oauth' || credential.expires <= Date.now()) {reject(403,'credential_unavailable');return;}
  }
  const record={sequence:ledger.length+1, trial:id, real:config.real, started:new Date().toISOString(), input_bytes:size, outcome:'pending', usage:null};
  ledger.push(record);persist();
  const started=Date.now();
  if(!config.real){record.outcome='dry_run';record.elapsed_ms=0;persist();res.end(JSON.stringify({dry_run:true}));return;}
  try {
    const payload=JSON.parse(Buffer.from(credential.access.split('.')[1],'base64url').toString());
    const account=payload['https://api.openai.com/auth']?.chatgpt_account_id;
    const headers={'Authorization':'Bearer '+credential.access,'chatgpt-account-id':account,'Content-Type':'application/json','Accept':'text/event-stream','originator':'pi'};
    for(const key of ['user-agent','openai-beta','session-id','x-client-request-id']) if(req.headers[key]) headers[key]=req.headers[key];
    const response=await fetch('https://chatgpt.com/backend-api/codex/responses',{method:'POST',headers,body:JSON.stringify(body),redirect:'error',signal:AbortSignal.timeout(175000)});
    record.http_status=response.status;
    if(!response.ok){record.outcome='upstream_rejected';record.elapsed_ms=Date.now()-started;persist();reject(400,'upstream_rejected');return;}
    res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-store'});
    let pending='';
    for await (const bytes of response.body) {
      if(!res.destroyed) res.write(Buffer.from(bytes));
      pending+=Buffer.from(bytes).toString('utf8');
      let newline;
      while((newline=pending.indexOf('\n'))>=0){
        const line=pending.slice(0,newline);pending=pending.slice(newline+1);
        if(line.startsWith('data: ')) try {
          const event=JSON.parse(line.slice(6));
          if(event.response?.usage) record.usage=event.response.usage;
          if(['response.completed','response.failed','response.incomplete'].includes(event.type)) record.outcome=event.type;
        } catch {}
      }
    }
    if(record.outcome==='pending') record.outcome='stream_closed_without_completion';
    res.end();
  } catch {record.outcome='transport_failed';if(!res.headersSent) reject(400,'upstream_transport_failed');else res.end();}
  record.elapsed_ms=Date.now()-started;persist();
});
server.on('upgrade',(_req,socket)=>socket.destroy());
server.listen(config.port,'127.0.0.1',()=>console.log(JSON.stringify({gateway_port:server.address().port,real:config.real})));
}

async function runKimiMessages() {
const {AuthStorage}=await import(pathToFileURL(config.authModule));
const {kimiCodingOAuth}=await import(pathToFileURL(config.oauthModule));
const auth=AuthStorage.create();
const ledger=fs.existsSync(config.ledger)?JSON.parse(fs.readFileSync(config.ledger,'utf8')):[];
function save(){fs.writeFileSync(config.ledger+'.tmp',JSON.stringify(ledger,null,2),{mode:0o600});fs.renameSync(config.ledger+'.tmp',config.ledger);}
http.createServer(async(req,res)=>{
 const reject=(status,error)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify({type:'error',error:{type:'evaluation_error',message:error}}));};
 if(req.url==='/health'){res.end(JSON.stringify({ready:true,consumed:ledger.length}));return;}
 const id=/^\/trial\/([a-z0-9-]+)\/v1\/messages(?:\?.*)?$/.exec(req.url??'')?.[1];
 const trial=id&&config.trials[id];
 if(!trial || req.headers['x-api-key']!==trial.token || req.method!=='POST'){reject(403,'scope_denied');return;}
 let body;try{let chunks=[],size=0;for await(const chunk of req){size+=chunk.length;if(size>10_000_000)throw Error();chunks.push(chunk);}body=JSON.parse(Buffer.concat(chunks).toString());}catch{reject(400,'invalid_body');return;}
 if(body.model!=='kimi-for-coding' || body.stream!==true){reject(400,'model_changed');return;}
 const budget=config.maxRequests??Infinity;
 const trialBudget=trial.maxRequests??Infinity;
 if(ledger.length>=budget || ledger.filter(x=>x.trial===id).length>=trialBudget){reject(402,'evaluation_budget_exhausted');return;}
 let credential;try{credential=await auth.modify('kimi-coding',async c=>c.expires>Date.now()+60000?undefined:await kimiCodingOAuth.refresh(c,AbortSignal.timeout(30000)));}catch{reject(403,'credential_unavailable');return;}
 const record={sequence:ledger.length+1,trial:id,started:new Date().toISOString(),outcome:'pending',usage:{},thinking:body.thinking,output_config:body.output_config};ledger.push(record);save();
 const start=Date.now();try{
  const headers={'authorization':'Bearer '+credential.access,'content-type':'application/json','anthropic-version':req.headers['anthropic-version']??'2023-06-01','user-agent':req.headers['user-agent']??'pi (evaluation)'};
  if(req.headers['anthropic-beta'])headers['anthropic-beta']=req.headers['anthropic-beta'];
  const response=await fetch('https://api.kimi.com/coding/v1/messages',{method:'POST',headers,body:JSON.stringify(body),redirect:'error',signal:AbortSignal.timeout(300000)});
  record.http_status=response.status;
  if(!response.ok){record.outcome='upstream_rejected';reject(400,'upstream_rejected');}
  else{res.writeHead(200,{'Content-Type':'text/event-stream'});let pending='';
   for await(const bytes of response.body){if(!res.destroyed)res.write(Buffer.from(bytes));pending+=Buffer.from(bytes).toString();let n;while((n=pending.indexOf('\n'))>=0){const line=pending.slice(0,n);pending=pending.slice(n+1);if(line.startsWith('data:'))try{const e=JSON.parse(line.slice(5).trimStart());if(e.message?.usage)Object.assign(record.usage,e.message.usage);if(e.usage)Object.assign(record.usage,e.usage);if(e.type==='message_stop')record.outcome='completed';if(e.type==='error')record.outcome='stream_error';}catch{}}}
   if(record.outcome==='pending')record.outcome='incomplete';res.end();}
 }catch{record.outcome='transport_failed';if(!res.headersSent)reject(400,'transport_failed');else res.end();}
 record.elapsed_ms=Date.now()-start;save();
}).listen(config.port,'127.0.0.1',()=>console.log('KIMI_GATEWAY_READY'));
}

if (mode === 'kimi_messages') {
  await runKimiMessages();
} else {
  await runOpenAiResponses();
}
