const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const window = new BrowserWindow({ show:false, width:1000, height:750, webPreferences:{sandbox:true} });
  try {
    const css = fs.readFileSync('src/masp/web/chat.css','utf8');
    await window.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent(`<html><head><style>${css}</style></head><body class="theme-light"><article class="message user"><div class="bubble" id="files">读取附件</div></article></body></html>`));
    const markdown = fs.readFileSync('src/masp/web/markdown.js','utf8');
    const preview = fs.readFileSync('src/masp/web/attachment-preview.js','utf8');
    const results = await window.webContents.executeJavaScript(`(async()=>{
      const markdownUrl=URL.createObjectURL(new Blob([${JSON.stringify(markdown)}],{type:'text/javascript'}));
      const source=${JSON.stringify(preview)}.replace("'./markdown.js?v=43'",JSON.stringify(markdownUrl));
      const module=await import(URL.createObjectURL(new Blob([source],{type:'text/javascript'})));
      const records=[{name:'README.md',content:'# Project preview\\nReadable Markdown.'},{name:'config.json',content:'{"enabled":true}'},{name:'image.png',data_url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII='}];
      const host=document.getElementById('files');
      module.renderAttachmentCards(host,records);
      if(host.querySelectorAll('.attachment-file-card').length!==3)throw Error('Missing file cards');
      host.querySelector('button').click();
      if(document.querySelector('dialog h1')?.textContent!=='Project preview')throw Error('Markdown preview missing');
      document.querySelector('dialog').close(); await new Promise(resolve=>setTimeout(resolve,20));
      host.querySelectorAll('button')[1].click();
      if(!document.querySelector('dialog pre')?.textContent.includes('enabled'))throw Error('JSON preview missing');
      document.querySelector('dialog').close(); await new Promise(resolve=>setTimeout(resolve,20));
      host.replaceChildren(); module.renderAttachmentCards(host,JSON.parse(JSON.stringify(records)));
      host.querySelectorAll('button')[2].click();
      if(!document.querySelector('dialog img'))throw Error('Restored image preview missing');
      document.querySelector('dialog').close(); await new Promise(resolve=>setTimeout(resolve,20));
      return {fileCards:true,markdownPreview:true,jsonPreview:true,restoredImagePreview:true};
    })()`);
    fs.writeFileSync('evidence/ui-regression/attachment-preview.json',JSON.stringify({passed:4,...results},null,2));
    fs.writeFileSync('evidence/ui-regression/attachment-preview.png',(await window.webContents.capturePage()).toPNG());
    app.exit(0);
  }catch(error){console.error(error.stack);app.exit(1);}
});
