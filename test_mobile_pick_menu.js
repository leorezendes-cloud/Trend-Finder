const fs = require('fs'), vm = require('vm'), assert = require('assert');
async function check({mobile=true,failures=0,saved=1,statusCode=200}) {
  let submit, calls=0, scrolls=0;
  const button={disabled:false},status={textContent:''},label={},notice={};
  const summary={scrollIntoView:()=>scrolls++,focus:()=>{}};
  const menu={open:true,querySelector:selector=>selector==='summary'?summary:selector==='[data-pick-menu-label]'?label:notice};
  const form={action:'/picks/save',addEventListener:(name,handler)=>submit=handler,querySelector:selector=>selector.startsWith('button')?button:status,querySelectorAll:()=>[],closest:()=>menu};
  const document={addEventListener:()=>{},querySelectorAll:selector=>selector==='[data-pick-form]'?[form]:[menu]};
  const window={matchMedia:query=>({matches:query.includes('650')?mobile:false,addEventListener:()=>{}})};
  const fetch=async()=>{calls++;if(calls<=failures)throw new TypeError('Load failed');return {status:statusCode,ok:statusCode===200,headers:{get:()=> 'application/json'},json:async()=>({saved,message:'Picks saved',error:'Rejected'})}};
  vm.runInNewContext(fs.readFileSync('static/member_picks.js','utf8'),{document,window,fetch,FormData:class {}});
  await submit({preventDefault:()=>{}});
  return {menu,calls,scrolls,button,status};
}
(async()=>{
  let result=await check({});assert.equal(result.menu.open,false);assert.equal(result.scrolls,1);
  result=await check({mobile:false});assert.equal(result.menu.open,true);assert.equal(result.scrolls,0);
  result=await check({failures:1});assert.equal(result.calls,2);assert.equal(result.menu.open,false);
  result=await check({failures:2});assert.equal(result.menu.open,true);assert.match(result.status.textContent,/Connection interrupted/);assert.equal(result.button.disabled,false);
  result=await check({saved:0});assert.equal(result.menu.open,true);
  result=await check({statusCode:403});assert.equal(result.calls,1);assert.equal(result.menu.open,true);
  console.log('Mobile collapse, desktop behavior, one safe retry, and failed-save visibility passed');
})().catch(error=>{console.error(error);process.exit(1)});
