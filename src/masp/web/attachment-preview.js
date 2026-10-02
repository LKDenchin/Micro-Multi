import { renderMarkdownElement } from './markdown.js?v=43';

function attachmentText(attachment) {
  if (attachment.content) return attachment.content;
  const encoded = String(attachment.data_url || '').split(',')[1];
  if (!encoded) return '';
  try { return new TextDecoder().decode(Uint8Array.from(atob(encoded), char => char.charCodeAt(0))); }
  catch { return '附件内容无法解码。'; }
}

export function renderAttachmentCards(container, attachments = []) {
  if (!attachments.length) return;
  const list = document.createElement('div'); list.className = 'message-attachments';
  for (const attachment of attachments) {
    const name = attachment.name || 'attachment';
    const extension = name.includes('.') ? name.split('.').pop().toUpperCase().slice(0, 8) : 'FILE';
    const image = /^data:image\/(png|jpeg|webp|gif);base64,/.test(attachment.data_url || '');
    const card = document.createElement('button'); card.type = 'button'; card.className = 'attachment-file-card';
    const format = document.createElement(image ? 'img' : 'span'); format.className = 'attachment-format';
    if (image) { format.src = attachment.data_url; format.alt = ''; } else format.textContent = extension;
    const title = document.createElement('span'); title.textContent = name;
    const hint = document.createElement('small'); hint.textContent = '点击预览';
    card.append(format, title, hint);
    card.addEventListener('click', () => {
      const dialog = document.createElement('dialog'); dialog.className = 'attachment-preview-dialog';
      const header = document.createElement('header'); const label = document.createElement('strong'); label.textContent = name;
      const close = document.createElement('button'); close.textContent = '关闭'; close.addEventListener('click', () => dialog.close());
      header.append(label, close); dialog.append(header);
      const body = document.createElement('div'); body.className = 'attachment-preview-body';
      if (image) { const preview = document.createElement('img'); preview.src = attachment.data_url; preview.alt = name; body.append(preview); }
      else if (extension === 'MD' || extension === 'MARKDOWN') renderMarkdownElement(body, attachmentText(attachment));
      else if (extension === 'PDF' && /^data:application\/pdf;base64,/.test(attachment.data_url || '')) {
        const preview = document.createElement('iframe'); preview.title = name; preview.src = attachment.data_url; body.append(preview);
      } else {
        const preview = document.createElement('pre');
        preview.textContent = attachmentText(attachment) || '此格式暂不支持内嵌预览，请下载后打开。'; body.append(preview);
      }
      if (attachment.data_url) { const download = document.createElement('a'); download.href = attachment.data_url; download.download = name; download.textContent = '下载附件'; body.append(download); }
      dialog.append(body); dialog.addEventListener('close', () => dialog.remove()); document.body.append(dialog); dialog.showModal();
    });
    list.append(card);
  }
  container.append(list);
}
