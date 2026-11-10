import { writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { Client } from 'file:///D:/Tools/REA-Research/rea/node_modules/@modelcontextprotocol/client/dist/index.mjs';
import { StdioClientTransport } from 'file:///D:/Tools/REA-Research/rea/node_modules/@modelcontextprotocol/client/dist/stdio.mjs';

const config = JSON.parse(execFileSync('C:\\Python313\\python.exe', ['-c',
  "import tomllib,pathlib,json; print(json.dumps(tomllib.loads((pathlib.Path.home()/'.codex/config.toml').read_text(encoding='utf-8-sig'))['mcp_servers']['rea']))"
], {encoding:'utf8', windowsHide:true}));
const transport = new StdioClientTransport({command:config.command,args:config.args,env:{...process.env,...config.env},stderr:'pipe'});
let errors = '';
transport.stderr?.on('data', data => { errors += data.toString(); });
const client = new Client({name:'rea-install-verification',version:'1.0.0'}, {capabilities:{}});
try {
  await client.connect(transport, {timeout:30000});
  const tools = [];
  let cursor;
  do {
    const page = await client.listTools(cursor ? {cursor} : {});
    tools.push(...page.tools);
    cursor = page.nextCursor;
  } while (cursor);
  if (!tools.length) throw new Error('REA returned no MCP tools');
  const report = {verified_at:new Date().toISOString(),server:client.getServerVersion(),tool_count:tools.length,tools:tools.map(({name,description,annotations})=>({name,description,annotations}))};
  writeFileSync(new URL('../reports/rea-mcp-tools.json',import.meta.url),JSON.stringify(report,null,2));
  console.log(JSON.stringify({server:report.server,tool_count:tools.length,sample_tools:tools.slice(0,12).map(t=>t.name)}));
} catch(error) {
  if (errors) console.error(errors);
  throw error;
} finally {
  await client.close();
}
