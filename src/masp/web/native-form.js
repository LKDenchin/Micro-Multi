/* Native schema forms keep unknown properties and defer authoritative validation to Loader. */
(() => {
  function resolveSchema(schema, document, depth = 0) {
    if (!schema || typeof schema !== 'object' || depth > 12) return {};
    if (schema.$ref?.startsWith('#/')) {
      const target = schema.$ref.slice(2).split('/').reduce((value, key) =>
        value?.[key.replace(/~1/g, '/').replace(/~0/g, '~')], document);
      return resolveSchema(target, document, depth + 1);
    }
    if (schema.allOf) {
      const merged = { ...schema, properties: { ...schema.properties } };
      for (const child of schema.allOf) {
        const part = resolveSchema(child, document, depth + 1);
        const properties = { ...merged.properties, ...part.properties };
        Object.assign(merged, part);
        merged.properties = properties;
      }
      delete merged.allOf;
      return merged;
    }
    return schema;
  }

  function editor(schema, value, documentSchema, depth = 0) {
    schema = resolveSchema(schema, documentSchema);
    const container = document.createElement('div');
    container.className = 'setting-row-stack';
    if (schema.type === 'object' && schema.properties && depth < 6) {
      const children = [];
      for (const [key, field] of Object.entries(schema.properties)) {
        const label = document.createElement('label');
        label.textContent = key + ((schema.required || []).includes(key) ? ' *' : '');
        const child = editor(field, value?.[key], documentSchema, depth + 1);
        label.append(child.element);
        container.append(label);
        children.push([key, child]);
      }
      // The JSON editor also exposes additional fields and uncommon schema constructs.
      const advanced = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = '完整设置';
      const raw = document.createElement('textarea');
      raw.rows = 5;
      raw.value = JSON.stringify(value ?? {}, null, 2);
      let rawChanged = false;
      raw.addEventListener('input', () => { rawChanged = true; });
      advanced.append(summary, raw);
      container.append(advanced);
      return { element: container, read() {
        if (rawChanged) return JSON.parse(raw.value);
        const result = structuredClone(value ?? {});
        for (const [key, child] of children) {
          const updated = child.read();
          if (updated !== undefined) result[key] = updated;
        }
        if (value === undefined && Object.keys(result).length === 0) return undefined;
        return result;
      } };
    }
    let input;
    if (schema.enum && schema.enum.every(item => ['string', 'number', 'boolean'].includes(typeof item))) {
      input = document.createElement('select');
      input.append(new Option('使用默认值', ''));
      schema.enum.forEach((item, index) => input.append(new Option(String(item), String(index))));
      const index = schema.enum.findIndex(item => item === value);
      input.value = index < 0 ? '' : String(index);
    } else if (schema.type === 'boolean') {
      input = document.createElement('select');
      input.append(new Option('使用默认值', ''), new Option('启用', 'true'), new Option('停用', 'false'));
      input.value = value === undefined ? '' : String(value);
    } else if (['string', 'number', 'integer'].includes(schema.type) && (value === undefined || typeof value !== 'object')) {
      input = document.createElement('input');
      input.type = schema.type === 'string' ? (schema.writeOnly || schema.format === 'password' ? 'password' : 'text') : 'number';
      if (schema.minimum !== undefined) input.min = schema.minimum;
      if (schema.maximum !== undefined) input.max = schema.maximum;
      input.step = schema.type === 'integer' ? '1' : 'any';
      input.value = value ?? '';
      input.placeholder = schema.default === undefined ? '' : String(schema.default);
    } else {
      input = document.createElement('textarea');
      input.rows = 4;
      input.value = JSON.stringify(value ?? schema.default ?? null, null, 2);
    }
    let changed = false;
    input.addEventListener('input', () => { changed = true; });
    input.addEventListener('change', () => { changed = true; });
    container.append(input);
    if (typeof schema.description === 'string') {
      const hint = document.createElement('small');
      hint.textContent = schema.description;
      container.append(hint);
    }
    return { element: container, read() {
      if (!changed) return value;
      if (schema.enum && input.tagName === 'SELECT') return input.value === '' ? undefined : schema.enum[Number(input.value)];
      if (schema.type === 'boolean') return input.value === '' ? undefined : input.value === 'true';
      if (input.tagName === 'TEXTAREA') return JSON.parse(input.value);
      if (schema.type === 'string') return input.value;
      if (input.value === '') return undefined;
      const number = Number(input.value);
      if (!Number.isFinite(number)) throw Error('请输入有效数字');
      return number;
    } };
  }

  window.NativeProfileForm = { render(container, data) {
    container.replaceChildren();
    const readers = [];
    const declarations = data.schema['x-cordis']?.entries || [];
    function visit(entries) {
      for (const entry of entries) {
        if (entry.group && Array.isArray(entry.config)) { visit(entry.config); continue; }
        if (!entry.id || !entry.name) continue;
        const declaration = declarations.find(item => item.id === entry.id && item.name === entry.name);
        const section = document.createElement('details');
        const title = document.createElement('summary');
        title.textContent = entry.id + ' · ' + entry.name;
        const field = editor(declaration?.configRef ? { $ref: declaration.configRef } : {}, entry.config ?? {}, data.schema);
        section.append(title, field.element);
        container.append(section);
        readers.push(() => ({ id: entry.id, config: field.read() }));
      }
    }
    visit(data.entries);
    for (const diagnostic of data.schema['x-cordis']?.diagnostics || []) {
      const message = document.createElement('p');
      message.textContent = diagnostic.message;
      container.append(message);
    }
    return () => readers.map(read => read());
  } };
})();
