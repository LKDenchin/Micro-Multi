const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  try {
    await win.loadURL('data:text/html,<main id="form"></main>');
    await win.webContents.executeJavaScript(fs.readFileSync('src/masp/web/native-form.js', 'utf8'));
    const checks = await win.webContents.executeJavaScript(`(() => {
      const checks=[];
      const assert=(condition,label)=>{if(!condition)throw Error(label);checks.push(label);};
      const schema={
        $defs:{settings:{type:'object',properties:{
          label:{type:'string'},enabled:{type:'boolean'},count:{type:'integer',minimum:1},
          choice:{type:'string',enum:['a','b']},nested:{type:'object',properties:{child:{type:'string'}}}
        }}},
        'x-cordis':{entries:[{id:'fixture',name:'fixture-plugin',configRef:'#/$defs/settings'}],diagnostics:[]}
      };
      const data={schema,entries:[{id:'fixture',name:'fixture-plugin',config:{
        label:'original',enabled:true,count:2,choice:'a',nested:{child:'nested',extra:7},unknown:'preserve'
      }}]};
      const read=NativeProfileForm.render(document.querySelector('#form'),data);
      assert(JSON.stringify(read()[0].config)===JSON.stringify(data.entries[0].config),'Unchanged form preserves all settings');
      const inputs=document.querySelectorAll('input');
      inputs[0].value='edited';inputs[0].dispatchEvent(new Event('input'));
      inputs[1].value='3';inputs[1].dispatchEvent(new Event('input'));
      const selects=document.querySelectorAll('select');
      selects[0].value='false';selects[0].dispatchEvent(new Event('change'));
      selects[1].value='1';selects[1].dispatchEvent(new Event('change'));
      const config=read()[0].config;
      assert(config.label==='edited'&&config.count===3,'Text and number fields edit correctly');
      assert(config.enabled===false&&config.choice==='b','Boolean and enum fields retain types');
      assert(config.unknown==='preserve'&&config.nested.extra===7,'Unknown and nested properties survive edits');
      const raw=document.querySelector('#form>details>div>details>textarea');
      raw.value='{bad json';raw.dispatchEvent(new Event('input'));
      let rejected=false;try{read();}catch{rejected=true;}
      assert(rejected,'Invalid JSON is rejected before saving');
      return checks;
    })()`);
    console.log(JSON.stringify({ passed: checks.length, checks }, null, 2));
    win.destroy();
    app.exit(0);
  } catch (error) {
    console.error(error);
    win.destroy();
    app.exit(1);
  }
});
