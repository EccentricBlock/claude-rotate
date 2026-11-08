"""Render the actual panel JavaScript with a tiny DOM sink harness (Node optional)."""
import ast
import json
import shutil
import subprocess
from pathlib import Path


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP panel JavaScript execution: Node.js is not installed")
        return
    tree = ast.parse((Path(__file__).resolve().parent.parent / "rotator.py").read_text())
    panel = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PANEL_HTML" for t in n.targets))
    script = panel.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = JSON.parse(process.argv[1]);
const value = '<mark data-audit="marker">&\'"</mark>';
const elements = {}, urls = [], replaced = [];
const usage = {requests:1,input_tokens:1,output_tokens:1,cache_read:0,cache_write:0,cost_usd:0};
const stats = {devices:{[value]:{last_model:value,last_account:value,key_suffix:value}},alerts:[{level:'warn',text:value}],by_device:{[value]:usage},by_model:{[value]:usage},by_account:{[value]:usage},periods:{since:value,'7d':{device:{[value]:usage},model:{[value]:usage}},'30d':{device:{[value]:usage},model:{[value]:usage}},all:{device:{[value]:usage,[value+'-gone']:usage},model:{[value]:usage}},trend:{[value]:[0,1,2]}}};
const status = {accounts:{[value]:{priority:100,private_to:[value,value+"-2"],reset_5h:1793883600,reset_7d:1793883600,reset_5h_in_min:30,reset_7d_in_h:50}},active_account:value,strategy:value,switch_threshold:.8,switch_threshold_7d:.98,recent_events:[{ts:value,from:value,to:value,reason:value}],weekly:{series:[[0,0,100],[3600,10,100]],projection:[[3600,10,100],[7200,100,100]],rate_per_day:5,eta:7200,back:9000,back_account:value,capacity:200}};
const context = vm.createContext({URL,URLSearchParams,location:{search:'?key=fake-viewer-key',href:'http://proxy/rotate/panel?key=fake-viewer-key'},history:{replaceState:(_a,_b,url)=>replaced.push(url)},document:{getElementById:id=>elements[id]??=( {innerHTML:'',textContent:''} )},setInterval:()=>{},fetch:async(url,opts)=>{urls.push({url,opts});return {json:async()=>url.includes('/status')?status:stats}}});
(async()=>{
  vm.runInContext(script,context,{timeout:1000});
  await vm.runInContext('refresh()',context,{timeout:1000});
  assert(replaced.every(url=>!url.includes('key=')));
  assert(urls.every(({url,opts})=>!url.includes('key=')&&opts.headers.Authorization==='Bearer fake-viewer-key'));
  assert(elements.weekly.innerHTML.includes('class="hit"'),'shortfall band not drawn');
  assert(elements.devices.innerHTML.includes('removed'),'removed device not listed');
  for(const id of ['pills','accounts','weekly','alerts','devices','models','by-account','events']){
    assert(!elements[id].innerHTML.includes('<mark'),id+' contains raw markup');
    assert(elements[id].innerHTML.includes('&lt;mark'),id+' lost escaped text');
  }
  assert(elements.accounts.innerHTML.includes('private to &lt;mark') && elements.accounts.innerHTML.includes('&lt;/mark&gt;-2'),'private badge missing or unescaped');
  const titles=elements.accounts.innerHTML.match(/title="[^"]*2026-11-05 13:00 UTC"/g)||[];
  assert.equal(titles.length,2,'5h and 7d reset spans need a UTC title');
  const acct=(extra)=>{status.accounts={flat:Object.assign({priority:100},extra)};return vm.runInContext('refresh()',context,{timeout:1000}).then(()=>elements.accounts.innerHTML)};
  let html=await acct({weekly_cap:.5,weekly_pacing:false,weekly_allowance:.5,effective_util_7d:.2});
  assert(html.includes('weekly cap 50%') && !html.includes('reached') && !html.includes('paced'),'flat cap badge wrong');
  html=await acct({weekly_cap:.5,weekly_pacing:true,weekly_allowance:.1071,effective_util_7d:.05});
  assert(html.includes('paced 11% now of 50%') && !html.includes('reached') && !html.includes('weekly cap'),'paced badge wrong');
  html=await acct({weekly_cap:null,weekly_pacing:true,weekly_allowance:.1071,effective_util_7d:.05});
  assert(html.includes('paced 11% now of 100%'),'paced badge without a cap wrong');
  html=await acct({weekly_cap:.5,weekly_pacing:true,weekly_allowance:.1071,effective_util_7d:.2});
  assert(html.includes('paced 11% now of 50% · reached'),'reached marker missing');
  html=await acct({weekly_cap:null,weekly_pacing:false,weekly_allowance:null,effective_util_7d:.2});
  assert(!html.includes('weekly cap') && !html.includes('paced'),'badge shown without cap or pacing');
  console.log('panel JavaScript security checks passed');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    subprocess.run([node, "-e", harness, json.dumps(script)], check=True)


if __name__ == "__main__":
    main()
