const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('maspDesktop', {
  isDesktop: true,
  readClipboardFiles: () => ipcRenderer.invoke('masp:clipboard-files'),
  chooseProjectDirectory: () => ipcRenderer.invoke('masp:choose-project'),
  onMenuAction: (callback) => {
    const listener = (_event, action) => callback(action);
    ipcRenderer.on('masp:menu-action', listener);
    return () => ipcRenderer.removeListener('masp:menu-action', listener);
  },
});
