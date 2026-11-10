// Audit-only execution of precisely hash-pinned shipped policy source, with
// synthetic contexts whose numerical APIs were executed from original qp/qw.
const fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto'),path=require('node:path');
const base=path.resolve(__dirname,'../../analysis/hrc-deep/general-scripts');
const hashes={preflop:'50841e520d2eace9730126a9880149ea6004a2c4c1ad57601d4f267887ddf30a',postflop:'93ac409c00866c3d1b7c2353bbb0d2a01a2eda3e2eddb894b7f9642b53025f39'};
const scripts={};for(const street of Object.keys(hashes)){const data=fs.readFileSync(path.join(base,`${street}_general.js`));if(crypto.createHash('sha256').update(data).digest('hex')!==hashes[street])throw Error('Unreviewed script');scripts[street]=new vm.Script(data.toString());}
const records=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),results=[];
for(const record of records){const a=record.actual;let actions=a.history.map(x=>({getPlayer:()=>x.actor,getActionType:()=>x.kind,getStreet:()=>x.street}));
 const current=actions.filter(x=>x.getStreet()===a.street);const last=[...actions].reverse().find(x=>x.getActionType()==='raise');
 const ctx={getActivePlayer:()=>a.actor,getBetCount:()=>a.bets,getStreet:()=>a.street,getFlatCallCount:()=>a.flats,
  getNumberOfPlayers:()=>a.getNumberOfPlayers,getPlayerIndexSmallBlind:()=>a.getPlayerIndexSmallBlind,getPlayerIndexBigBlind:()=>a.getPlayerIndexBigBlind,getPlayerIndexButton:()=>a.getPlayerIndexButton,
  getPotState:()=>({countPlayersLive:()=>a.live,countPlayersFolded:()=>a.history.reduce((m,x)=>x.kind==='fold'?m|(1<<x.actor):m,0).toString(2).replace(/0/g,'').length,hasPlayerFolded:p=>!!(a.foldedMask&(1<<p)),getChipsActive:p=>a.streetContributions[p]}),
  sizingAllIn:()=>a.maximum,sizingsPreflop:text=>a.pre_sizes[text],sizingsPostflop:text=>a.post_sizes[text],getStackPotRatio:()=>a.spr,
  getLastRaiseAction:()=>last,getActionSequence:()=>current,getActionSequenceFull:()=>actions,isPlayerInPosition:(x,y)=>a.ip[x][y],isClosingAction:()=>a.closing,isDonkBet:()=>a.donk};
 const out={id:record.id,settings_read:[]};
 for(const street of Object.keys(scripts)){const sandbox={FLOP:1,TURN:2,RIVER:3,RAISE:'raise'};vm.createContext(sandbox,{codeGeneration:{strings:false,wasm:false}});scripts[street].runInContext(sandbox,{timeout:1000});for(const [key,value] of Object.entries(record.settings[street]))Object.defineProperty(sandbox,key,{get(){out.settings_read.push(key);return value;}});
  if(street==='postflop')out.next=sandbox.hasNextStreetBetting(ctx);
  if(a.actor>=0&&a.minimum>0&&((a.street===0)===(street==='preflop'))){let sizes=street==='preflop'?sandbox.getSizingsPreflop(ctx):sandbox.getSizingsPostflop(ctx);if(typeof sizes==='number')sizes=[sizes];out.sizes=[...new Set(sizes)].sort((x,y)=>x-y);if(street==='preflop')out.flat=sandbox.canFlatCallPreflop(ctx);}}
 results.push(out);
}
process.stdout.write(JSON.stringify(results));
