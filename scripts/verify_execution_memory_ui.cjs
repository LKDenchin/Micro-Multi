const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: false, width: 900, height: 600, webPreferences: { sandbox: true } });
  try {
    const css = fs.readFileSync(path.resolve('src/masp/web/chat.css'), 'utf8');
    await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<html><head><style>${css}</style></head><body class="theme-light"><div class="subagent-step-item"><div class="subagent-step-head"><span class="subagent-step-left"><strong id="name">backend_developer</strong></span></div><div class="subagent-step-log-row is-pending" id="pending">运行测试与结果检验</div><details class="subagent-thinking-box" open><summary class="subagent-thinking-title" id="thinking">思考中</summary></details></div><div class="inspector"><button class="review-console-btn primary" id="review">开始审查</button></div><button class="conversation-delete" id="delete">删除</button><div id="answer"></div></body></html>`));
    const module = fs.readFileSync(path.resolve('src/masp/web/markdown.js'), 'utf8');
    const results = await window.webContents.executeJavaScript(`(async () => {
      const markdown = await import(URL.createObjectURL(new Blob([${JSON.stringify(module)}], {type:'text/javascript'})));
      const original = '回复<tool-execution-memory>secret server.js</tool-execution-memory>完成';
      const output = markdown.visibleAssistantContent(original);
      if (output !== '回复完成') throw new Error('Internal memory leaked');
      if (!markdown.visibleAssistantContent('\x60\x60\x60js\\nconst x=1;\\n\x60\x60\x60').includes('const x')) throw new Error('Legitimate code removed');
      document.querySelector('#answer').textContent = output;
      const expected = {name:'rgb(37, 37, 37)',pending:'rgb(102, 102, 102)',thinking:'rgb(64, 64, 64)',review:'rgb(37, 37, 37)',delete:'rgb(89, 89, 89)'};
      return Object.entries(expected).map(([id,color]) => {
        const actual = getComputedStyle(document.getElementById(id)).color;
        if (actual !== color) throw new Error(id+': '+actual+' expected '+color);
        return {id,color:actual};
      });
    })()`);
    fs.mkdirSync('evidence/ui-regression', {recursive:true});
    fs.writeFileSync('evidence/ui-regression/execution-memory-light.png', (await window.webContents.capturePage()).toPNG());
    fs.writeFileSync('evidence/ui-regression/execution-memory-light.json', JSON.stringify({passed:results.length+2, results}, null, 2));
    app.exit(0);
  } catch (error) { console.error(error.stack); app.exit(1); }
});
