import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const wp={task_id:'old',sequence:1,lat:-7,lon:110,alt_m:10};
function mount({token='operator-test',capable=true,phase='ACTIVE',pending,reply}={}) {
  const server={phase,plan:{mission_id:'live',version:1,waypoints:[wp]},drones:[{armed:true}],
    tasks:[],edit_locked:true,append_allowed:capable,busy:false,append_pending:pending};
  const states=[server,[wp],false,true,false,'',10,null,token];
  const refs=[];let cursor=0,refCursor=0;const calls=[];
  const jsx=(type,props)=>({type,props});
  const modules={
    react:{createContext:()=>({Provider:'Provider'}),useContext(){},
      useState(initial){const i=cursor++;if(!(i in states))states[i]=initial;
        return [states[i],v=>{states[i]=typeof v==='function'?v(states[i]):v}];},
      useRef(value){const i=refCursor++;return refs[i]??=( {current:value} );},
      useEffect(){},useCallback:cb=>cb},
    'react/jsx-runtime':{jsx,jsxs:jsx},
    '@/hooks/useGCSStore':{useGCSStore:()=>({uavs:{}})},
    '@/hooks/useWebSocket':{useWebSocket(){}},
  };
  let ids=0;
  const context=vm.createContext({exports:{},require:name=>modules[name],process:{env:{}},
    sessionStorage:{setItem(){},getItem(){return null},removeItem(){}},
    crypto:{randomUUID:()=>`new-${++ids}`},
    fetch:async(url,options)=>{calls.push({url,body:JSON.parse(options.body),headers:options.headers});
      return reply ? reply(calls.at(-1),server) : {ok:true,json:async()=>({...server,plan:{...server.plan,version:2,
        waypoints:[wp,...calls.at(-1).body.waypoints]}})};},
  });
  const source=readFileSync(new URL('../src/components/swarm/SwarmMissionContext.tsx',import.meta.url),'utf8');
  vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,context);
  return {calls,render(){cursor=0;refCursor=0;return context.exports.SwarmMissionProvider({children:null}).props.value;}};
}

test('active map additions send only new waypoints with the current mission version and operator auth', async()=>{
  const app=mount();const mission=app.render();
  assert.equal(mission.locked,true);assert.equal(mission.canAdd,true);
  assert.equal(await mission.add(-7.001,110.001,12),true);
  assert.equal(app.calls.length,1);
  const call=app.calls[0];
  assert.ok(call.url.endsWith('/missions/live/append'));
  assert.equal(call.headers.Authorization,'Bearer operator-test');
  assert.equal(call.body.confirmation,'CONFIRM_APPEND');
  assert.equal(call.body.version,1);
  assert.deepEqual(call.body.waypoints,[{task_id:'wp-new-1',sequence:2,lat:-7.001,lon:110.001,alt_m:12}]);
  assert.equal(app.render().draft.length,2);
});

test('missing token or append capability blocks active addition',async()=>{
  for(const options of [{token:''},{capable:false}]){
    const app=mount(options);const mission=app.render();
    assert.equal(mission.canAdd,false);
    assert.equal(await mission.add(-7,110,10),false);
    assert.equal(app.calls.length,0);
  }
});

test('a second click cannot send a concurrent append before rerender',async()=>{
  let release;const waiting=new Promise(resolve=>{release=resolve});
  const app=mount({reply:async(call,server)=>{await waiting;return {ok:true,json:async()=>server}}});
  const mission=app.render();const first=mission.add(-7,110,10);
  assert.equal(await mission.add(-7.1,110.1,10),false);
  release();await first;
  assert.equal(app.calls.length,1);
});

test('append errors remain visible and leave the active plan unchanged',async()=>{
  const app=mount({reply:()=>({ok:false,json:async()=>({detail:'Mission/version changed'})})});
  assert.equal(await app.render().add(-7,110,10),false);
  assert.equal(app.render().draft.length,1);
  assert.equal(app.render().error,'Mission/version changed');
});

test('retry sends exactly the persisted pending addition',async()=>{
  const extra={...wp,task_id:'pending',sequence:2};
  const app=mount({phase:'HELD',capable:false,pending:{base_version:1,waypoints:[extra]}});
  assert.equal(await app.render().operate('append'),true);
  assert.deepEqual(app.calls[0].body.waypoints,[extra]);
});
