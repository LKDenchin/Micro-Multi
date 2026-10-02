const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
app.whenReady().then(async () => {
  const evidence = path.resolve('evidence/refraction-live');
  const summary = JSON.parse(fs.readFileSync(path.join(evidence, 'summary.json'), 'utf8'));
  const win = new BrowserWindow({show:false, width:1280, height:900, webPreferences:{sandbox:true}});
  const errors = [];
  win.webContents.on('console-message', (_event, level, message) => { if(level===3) errors.push(message); });
  await win.loadFile(path.join(summary.project_root, 'light-refraction.html'));
  const result = await win.webContents.executeJavaScript(`(() => {
    const assert=(ok,label)=>{if(!ok)throw Error(label)};
    assert(Math.abs(computeOptics(45,1,1.33).theta2-32.1176)<0.01,'Snell');
    assert(computeOptics(50,1.33,1).tir,'TIR');
    assert(Math.abs(computeOptics(0,1,1.5).theta2)<1e-9,'normal incidence');
    const slider=document.getElementById('angle');
    slider.value=30; slider.dispatchEvent(new Event('input',{bubbles:true}));
    assert(state.theta1===30,'angle control');
    const originalArrow=drawArrowLine;
    let rays=[];
    drawArrowLine=(...args)=>rays.push(args);
    state.showReflect=true;
    for(const fromRight of [false,true]) {
      state.fromRight=fromRight; state.n1=1;state.n2=1;state.theta1=30;rays=[];draw();
      const [incoming,reflected,refracted]=rays;
      assert(rays.length===3,'three rays');
      const dx=incoming[2]-incoming[0];
      assert(dx*(reflected[2]-reflected[0])>0,'reflection tangential continuity');
      assert(dx*(refracted[2]-refracted[0])>0,'refraction tangential continuity');
      const cross=dx*(refracted[3]-refracted[1])-(incoming[3]-incoming[1])*(refracted[2]-refracted[0]);
      assert(Math.abs(cross)<1e-6,'equal index straight propagation');
    }
    state.n1=1.33;state.n2=1;state.theta1=50;rays=[];draw();
    assert(rays.length===2,'TIR hides refraction');
    drawArrowLine=originalArrow;
    state.n1=1;state.n2=1.33;state.theta1=30;state.fromRight=false;draw();
    const canvas=document.getElementById('cv');
    assert(canvas.width>0 && canvas.height>0,'canvas dimensions');
    return {physics:true,geometry:true,controls:true,canvas:true,title:document.title};
  })()`);
  await new Promise(resolve=>setTimeout(resolve,300));
  fs.writeFileSync(path.join(evidence,'browser-check.json'), JSON.stringify({...result,errors},null,2));
  fs.writeFileSync(path.join(evidence,'demo.png'),(await win.webContents.capturePage()).toPNG());
  console.log(JSON.stringify({...result,errors}));
  app.exit(errors.length?1:0);
}).catch(error=>{console.error(error);app.exit(1)});
