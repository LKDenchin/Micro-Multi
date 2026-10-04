/**
 * Markdown & LaTeX Math Renderer ported from deepseek-ai/deepseek-harness
 * (packages/client/ui-primitives/src/markdown/*)
 */

export function visibleAssistantContent(content) {
  return String(content || '').replace(/<tool-execution-memory>[\s\S]*?(?:<\/tool-execution-memory>|$)/gi, '');
}

const GREEK_AND_SYMBOLS = {
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ϵ', varepsilon: 'ε',
  zeta: 'ζ', eta: 'η', theta: 'θ', vartheta: 'ϑ', iota: 'ι', kappa: 'κ',
  lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', rho: 'ρ', sigma: 'σ',
  tau: 'τ', upsilon: 'υ', phi: 'ϕ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π',
  Sigma: 'Σ', Upsilon: 'Υ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
  times: '×', cdot: '·', div: '÷', pm: '±', mp: '∓', star: '⋆', ast: '∗',
  leq: '≤', le: '≤', geq: '≥', ge: '≥', neq: '≠', ne: '≠', approx: '≈',
  equiv: '≡', sim: '∼', simeq: '≃', cong: '≅', propto: '∝',
  infty: '∞', partial: '∂', nabla: '∇', forall: '∀', exists: '∃', nexists: '∄',
  in: '∈', notin: '∉', ni: '∋', subset: '⊂', supset: '⊃', subseteq: '⊆', supseteq: '⊇',
  cup: '∪', cap: '∩', emptyset: '∅', varnothing: '∅',
   leftarrow: '←', rightarrow: '→', to: '→', leftrightarrow: '↔',
  Leftarrow: '⇐', Rightarrow: '⇒', implies: '⟹', Leftrightarrow: '⇔', iff: '⟺',
  mapsto: '↦', uparrow: '↑', downarrow: '↓',
  sum: '∑', prod: '∏', coprod: '∐', int: '∫', iint: '∬', iiint: '∭', oint: '∮',
  lim: 'lim', sup: 'sup', inf: 'inf', max: 'max', min: 'min',
  sin: 'sin', cos: 'cos', tan: 'tan', cot: 'cot', sec: 'sec', csc: 'csc',
  ln: 'ln', log: 'log', exp: 'exp', det: 'det', dim: 'dim', ker: 'ker',
  dots: '…', ldots: '…', cdots: '⋯', vdots: '⋮', ddots: '⋱',
  angle: '∠', triangle: '△', perp: '⊥', parallel: '∥', degree: '°', circ: '∘',
  prime: '′', ell: 'ℓ', hbar: 'ℏ', Re: 'ℜ', Im: 'ℑ', wp: '℘', aleph: 'ℵ',
  neg: '¬', lnot: '¬', land: '∧', lor: '∨', oplus: '⊕', otimes: '⊗',
};

const BLACKBOARD_BOLD = {
  R: 'ℝ', N: 'ℕ', Z: 'ℤ', Q: 'ℚ', C: 'ℂ', P: 'ℙ', E: '𝔼', F: '𝔽', H: 'ℍ',
};

function escapeHtml(raw) {
  return String(raw ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Ported from deepseek-harness mathCompatibility.ts:
 * Normalize \[...\] and \(...\) delimiters into $$...$$ and $...$ outside code spans.
 */
export function normalizeMathDelimiters(markdown) {
  const src = String(markdown ?? '');
  if (!src) return '';
  // Split by fenced code blocks and inline code to avoid mutating code
  const segments = src.split(/(```[\s\S]*?```|`[^`\n]+`)/g);
  return segments
    .map((segment, index) => {
      if (index % 2 === 1) return segment;
      return segment
        .replace(/\\\[([\s\S]*?)\\\]/g, (_m, body) => `$$\n${String(body).trim()}\n$$`)
        .replace(/\\\(([\s\S]*?)\\\)/g, (_m, body) => `$${String(body).trim()}$`);
    })
    .join('');
}

function extractBracedGroup(str, startIdx) {
  if (str[startIdx] !== '{') return null;
  let depth = 0;
  for (let i = startIdx; i < str.length; i += 1) {
    if (str[i] === '\\') {
      i += 1;
      continue;
    }
    if (str[i] === '{') depth += 1;
    else if (str[i] === '}') {
      depth -= 1;
      if (depth === 0) {
        return { content: str.slice(startIdx + 1, i), end: i + 1 };
      }
    }
  }
  return { content: str.slice(startIdx + 1), end: str.length };
}

function renderLatexAst(expr) {
  let s = String(expr ?? '').trim();
  if (!s) return '';

  // Handle environments like \begin{pmatrix}...\end{pmatrix}, \begin{cases}...\end{cases}, \begin{aligned}...\end{aligned}
  s = s.replace(/\\begin\{(pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|matrix|aligned|align\*?|cases)\}([\s\S]*?)\\end\{\1\}/g, (_m, env, body) => {
    const rows = String(body)
      .trim()
      .split(/\\\\/)
      .map((r) => r.trim())
      .filter(Boolean);
    const renderedRows = rows
      .map((row) => {
        const cells = row.split('&').map((c) => `<span class="math-matrix-cell">${renderLatexAst(c.trim())}</span>`);
        return `<span class="math-matrix-row">${cells.join('')}</span>`;
      })
      .join('');
    let leftDelim = '';
    let rightDelim = '';
    if (env === 'pmatrix') { leftDelim = '('; rightDelim = ')'; }
    else if (env === 'bmatrix') { leftDelim = '['; rightDelim = ']'; }
    else if (env === 'Bmatrix') { leftDelim = '{'; rightDelim = '}'; }
    else if (env === 'vmatrix') { leftDelim = '|'; rightDelim = '|'; }
    else if (env === 'Vmatrix') { leftDelim = '‖'; rightDelim = '‖'; }
    else if (env === 'cases') { leftDelim = '{'; rightDelim = ''; }
    return `\u0000MATH_HTML_START\u0000<span class="math-env math-env-${env}">${leftDelim ? `<span class="math-delim">${leftDelim}</span>` : ''}<span class="math-matrix">${renderedRows}</span>${rightDelim ? `<span class="math-delim">${rightDelim}</span>` : ''}</span>\u0000MATH_HTML_END\u0000`;
  });

  const htmlTokens = [];
  const stashHtml = (html) => {
    const id = `\u0001H${htmlTokens.length}\u0001`;
    htmlTokens.push(html);
    return id;
  };

  s = s.replace(/\u0000MATH_HTML_START\u0000([\s\S]*?)\u0000MATH_HTML_END\u0000/g, (_m, html) => stashHtml(html));

  // Process recursive macros: \frac{a}{b}, \dfrac{a}{b}, \tfrac{a}{b}, \sqrt[n]{x}, \sqrt{x}, \mathbb{X}, \text{...}, \mathbf{...}, \mathrm{...}
  let cursor = 0;
  let out = '';
  while (cursor < s.length) {
    if (s[cursor] === '\\') {
      const cmdMatch = s.slice(cursor + 1).match(/^([a-zA-Z]+|[,;:!]|[{}_%#$& ])/);
      if (cmdMatch) {
        const cmd = cmdMatch[1];
        const nextIdx = cursor + 1 + cmd.length;
        if (cmd === 'frac' || cmd === 'dfrac' || cmd === 'tfrac') {
          let p = nextIdx;
          while (p < s.length && /\s/.test(s[p])) p += 1;
          const numGroup = extractBracedGroup(s, p);
          if (numGroup) {
            p = numGroup.end;
            while (p < s.length && /\s/.test(s[p])) p += 1;
            const denGroup = extractBracedGroup(s, p);
            if (denGroup) {
              out += stashHtml(
                `<span class="math-frac"><span class="math-num">${renderLatexAst(numGroup.content)}</span><span class="math-den">${renderLatexAst(denGroup.content)}</span></span>`
              );
              cursor = denGroup.end;
              continue;
            }
          }
        } else if (cmd === 'sqrt') {
          let p = nextIdx;
          while (p < s.length && /\s/.test(s[p])) p += 1;
          let rootIndex = '';
          if (s[p] === '[') {
            const closeBracket = s.indexOf(']', p + 1);
            if (closeBracket !== -1) {
              rootIndex = s.slice(p + 1, closeBracket);
              p = closeBracket + 1;
              while (p < s.length && /\s/.test(s[p])) p += 1;
            }
          }
          const radGroup = extractBracedGroup(s, p);
          if (radGroup) {
            out += stashHtml(
              `<span class="math-sqrt">${rootIndex ? `<sup class="math-root-idx">${renderLatexAst(rootIndex)}</sup>` : ''}<span class="math-radix">√</span><span class="math-radicand">${renderLatexAst(radGroup.content)}</span></span>`
            );
            cursor = radGroup.end;
            continue;
          }
        } else if (cmd === 'mathbb') {
          let p = nextIdx;
          while (p < s.length && /\s/.test(s[p])) p += 1;
          const grp = extractBracedGroup(s, p);
          if (grp) {
            const key = grp.content.trim();
            const mapped = BLACKBOARD_BOLD[key] || escapeHtml(key);
            out += stashHtml(`<span class="math-bb">${mapped}</span>`);
            cursor = grp.end;
            continue;
          }
        } else if (cmd === 'text' || cmd === 'textrm' || cmd === 'mathrm' || cmd === 'operatorname') {
          let p = nextIdx;
          while (p < s.length && /\s/.test(s[p])) p += 1;
          const grp = extractBracedGroup(s, p);
          if (grp) {
            out += stashHtml(`<span class="math-rm">${escapeHtml(grp.content)}</span>`);
            cursor = grp.end;
            continue;
          }
        } else if (cmd === 'mathbf' || cmd === 'boldsymbol' || cmd === 'bm') {
          let p = nextIdx;
          while (p < s.length && /\s/.test(s[p])) p += 1;
          const grp = extractBracedGroup(s, p);
          if (grp) {
            out += stashHtml(`<strong class="math-bf">${renderLatexAst(grp.content)}</strong>`);
            cursor = grp.end;
            continue;
          }
        } else if (cmd === 'hat' || cmd === 'bar' || cmd === 'vec' || cmd === 'tilde' || cmd === 'dot') {
          let p = nextIdx;
          while (p < s.length && /\s/.test(s[p])) p += 1;
          const grp = extractBracedGroup(s, p);
          if (grp) {
            const accentMap = { hat: '̂', bar: '̄', vec: '⃗', tilde: '̃', dot: '̇' };
            out += stashHtml(`<span class="math-accent">${renderLatexAst(grp.content)}${accentMap[cmd] || ''}</span>`);
            cursor = grp.end;
            continue;
          }
        } else if (cmd === 'left' || cmd === 'right') {
          cursor = nextIdx;
          continue;
        } else if (cmd in GREEK_AND_SYMBOLS) {
          const sym = GREEK_AND_SYMBOLS[cmd];
          const isFunc = /^[a-z]{2,4}$/.test(sym);
          out += stashHtml(`<span class="${isFunc ? 'math-fn' : 'math-sym'}">${escapeHtml(sym)}</span>`);
          cursor = nextIdx;
          continue;
        } else if (cmd === ',' || cmd === ';' || cmd === ':') {
          out += ' ';
          cursor = nextIdx;
          continue;
        } else if (cmd === '!') {
          cursor = nextIdx;
          continue;
        } else if (cmd === '{' || cmd === '}' || cmd === '_' || cmd === '%' || cmd === '#' || cmd === '$' || cmd === '&') {
          out += escapeHtml(cmd);
          cursor = nextIdx;
          continue;
        } else {
          out += stashHtml(`<span class="math-rm">${escapeHtml(cmd)}</span>`);
          cursor = nextIdx;
          continue;
        }
      }
    }

    // Handle superscript ^ and subscript _
    if (s[cursor] === '^' || s[cursor] === '_') {
      const isSup = s[cursor] === '^';
      const tag = isSup ? 'sup' : 'sub';
      let p = cursor + 1;
      while (p < s.length && /\s/.test(s[p])) p += 1;
      if (s[p] === '{') {
        const grp = extractBracedGroup(s, p);
        if (grp) {
          out += stashHtml(`<${tag} class="math-${tag}">${renderLatexAst(grp.content)}</${tag}>`);
          cursor = grp.end;
          continue;
        }
      } else if (s[p] === '\\') {
        const m = s.slice(p + 1).match(/^[a-zA-Z]+/);
        if (m) {
          const token = `\\${m[0]}`;
          out += stashHtml(`<${tag} class="math-${tag}">${renderLatexAst(token)}</${tag}>`);
          cursor = p + 1 + m[0].length;
          continue;
        }
      } else if (p < s.length) {
        const ch = s[p];
        out += stashHtml(`<${tag} class="math-${tag}">${renderLatexAst(ch)}</${tag}>`);
        cursor = p + 1;
        continue;
      }
    }

    if (s[cursor] === '{') {
      const grp = extractBracedGroup(s, cursor);
      if (grp) {
        out += stashHtml(renderLatexAst(grp.content));
        cursor = grp.end;
        continue;
      }
    }

    out += s[cursor];
    cursor += 1;
  }

  // Format remaining plain characters: numbers and Latin/Greek letters in math style
  let formatted = '';
  let i = 0;
  while (i < out.length) {
    if (out[i] === '\u0001') {
      const endMarker = out.indexOf('\u0001', i + 1);
      if (endMarker !== -1) {
        const tokenKey = out.slice(i + 2, endMarker);
        const idx = Number(tokenKey);
        formatted += Number.isFinite(idx) && htmlTokens[idx] !== undefined ? htmlTokens[idx] : '';
        i = endMarker + 1;
        continue;
      }
    }
    const ch = out[i];
    if (/[a-zA-Z]/.test(ch)) {
      formatted += `<var class="math-var">${ch}</var>`;
    } else if (/[0-9]/.test(ch)) {
      let numRun = ch;
      while (i + 1 < out.length && /[0-9.]/.test(out[i + 1])) {
        i += 1;
        numRun += out[i];
      }
      formatted += `<span class="math-num-lit">${numRun}</span>`;
    } else if (ch === '-' || ch === '+' || ch === '=' || ch === '<' || ch === '>') {
      formatted += `<span class="math-op">${escapeHtml(ch)}</span>`;
    } else {
      formatted += escapeHtml(ch);
    }
    i += 1;
  }

  return formatted;
}

export function renderLatexMath(tex, displayMode = false) {
  const clean = String(tex ?? '').trim();
  if (!clean) return '';
  if (typeof window !== 'undefined' && window.katex && typeof window.katex.renderToString === 'function') {
    try {
      return window.katex.renderToString(clean, {
        displayMode,
        throwOnError: false,
        strict: 'ignore',
      });
    } catch {
      // Fall back to built-in math renderer
    }
  }
  const inner = renderLatexAst(clean);
  return displayMode
    ? `<div class="masp-math-block" role="math" aria-label="${escapeHtml(clean)}">${inner}</div>`
    : `<span class="masp-math-inline" role="math" aria-label="${escapeHtml(clean)}">${inner}</span>`;
}

function renderInlineMarkdown(text, mathBag) {
  let s = String(text ?? '');
  if (!s) return '';

  const inlineTokens = [];
  const stash = (html) => {
    const key = `\u0002I${inlineTokens.length}\u0002`;
    inlineTokens.push(html);
    return key;
  };

  // 1. Inline code `...`
  s = s.replace(/`([^`\n]+)`/g, (_m, code) => stash(`<code class="md-inline-code">${escapeHtml(code)}</code>`));

  // 2. Inline math $...$ (avoid matching currency like $100 or $ 50)
  s = s.replace(/(^|[^\\$])\$(?!\s)((?:\\.|[^$\n])+?)(?<!\s)\$/g, (match, prefix, expr) => {
    if (/^\d+(?:[.,]\d+)*\s*$/.test(expr) && prefix && /\s/.test(prefix)) {
      // Allow single numbers like $5$ or $x=5$ in math mode!
    }
    return `${prefix}${stash(renderLatexMath(expr, false))}`;
  });

  // Restore any pre-extracted math tokens from mathBag
  if (mathBag && mathBag.length) {
    s = s.replace(/\u0003M(\d+)\u0003/g, (_m, idx) => stash(mathBag[Number(idx)] || ''));
  }

  // Escape HTML on remaining text
  s = escapeHtml(s);

  // 3. Links [label](url)
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|file:\/\/\/[^\s)]+|\/[^\s)]+)\)/g, (_m, label, url) => {
    const safeUrl = url.replace(/&amp;/g, '&');
    return stash(`<a class="md-link" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  });

  // 4. CJK-friendly bold **...** and __...__
  s = s.replace(/\*\*([\s\S]+?)\*\*/g, '<strong class="md-strong">$1</strong>');
  s = s.replace(/__([^_\n]+?)__/g, '<strong class="md-strong">$1</strong>');

  // 5. Strikethrough ~~...~~
  s = s.replace(/~~([^~\n]+?)~~/g, '<del>$1</del>');

  // 6. Italic *...*
  s = s.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, '$1<em class="md-em">$2</em>');

  // Restore stashed inline HTML
  s = s.replace(/\u0002I(\d+)\u0002/g, (_m, idx) => inlineTokens[Number(idx)] || '');
  return s;
}

function parseTableRow(line) {
  const trimmed = line.trim();
  const inner = trimmed.startsWith('|') ? trimmed.slice(1) : trimmed;
  const withoutEnd = inner.endsWith('|') ? inner.slice(0, -1) : inner;
  return withoutEnd.split('|').map((c) => c.trim());
}

function isTableSeparator(line) {
  if (!line || !line.includes('|')) return false;
  const cells = parseTableRow(line);
  return cells.length > 0 && cells.every((c) => /^:?-{3,}:?$/.test(c));
}

function highlightMdCodeLine(rawLine) {
  const text = String(rawLine ?? '');
  if (!text) return '';
  const tokenRegex = /(\/\/.*$|#.*$|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:import|from|export|default|function|return|const|let|var|if|else|for|while|switch|case|break|continue|class|extends|new|try|catch|finally|throw|async|await|def|elif|except|raise|with|as|pass|lambda|yield|True|False|None|true|false|null|undefined|typeof|instanceof|in|of|interface|type|enum|public|private|protected|readonly|static|struct|impl|fn|mut|pub|use|package|go|defer|chan|select)\b|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\())/gm;
  let result = '';
  let lastIndex = 0;
  let match;
  while ((match = tokenRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      result += escapeHtml(text.slice(lastIndex, match.index));
    }
    const tok = match[0];
    let cls = 'tok-kw';
    if (tok.startsWith('//') || tok.startsWith('#') || tok.startsWith('/*')) {
      cls = 'tok-com';
    } else if (tok.startsWith('"') || tok.startsWith("'") || tok.startsWith('`')) {
      cls = 'tok-str';
    } else if (/^\d/.test(tok)) {
      cls = 'tok-num';
    } else if (/^[A-Za-z_]/.test(tok) && text.slice(match.index + tok.length).trimStart().startsWith('(')) {
      const kwSet = new Set(['if', 'for', 'while', 'switch', 'catch', 'return', 'function', 'def', 'class', 'import', 'from', 'typeof']);
      if (!kwSet.has(tok)) cls = 'tok-fn';
    }
    result += '<span class="' + cls + '">' + escapeHtml(tok) + '</span>';
    lastIndex = tokenRegex.lastIndex;
  }
  if (lastIndex < text.length) {
    result += escapeHtml(text.slice(lastIndex));
  }
  return result;
}

export function renderMarkdownToHtml(rawText) {
  const raw = String(rawText ?? '');
  if (!raw.trim()) return '';

  // Hide internal tool/team configuration tags (<tool-execution-memory>, <configure_team>, <start_team>, DSML)
  let cleaned = raw
    .replace(/<tool-execution-memory>[\s\S]*?<\/tool-execution-memory>\s*/gi, '')
    .replace(/```(?:xml|json)?\s*<(configure_team|start_team)\b[^>]*>[\s\S]*?(?:<\/\1>\s*```|$)/gi, '')
    .replace(/<(configure_team|start_team)\b[^>]*>[\s\S]*?(?:<\/\1>|$)/gi, '')
    .replace(/<\s*[|｜]{1,2}\s*DSML\s*[|｜]{1,2}\s*(?:calls|function_calls)\s*>[\s\S]*?(?:<\s*\/?[|｜]{1,2}\s*\/?[|｜]{1,2}\s*(?:calls|function_calls)\s*>|$)/gi, '')
    .replace(/<\s*[|｜]{1,2}\s*DSML\s*[|｜]{1,2}\s*invoke[\s\S]*?(?:<\s*\/?[|｜]{1,2}\s*\/?[|｜]{1,2}\s*invoke\s*>|$)/gi, '')
    .replace(/<\s*[|｜]{1,2}\s*(?:tool[_▁]calls?[_▁]begin|DSML)[\s\S]*$/gi, '')
    .replace(/<\s*\/?\s*[|｜]{1,2}\s*(?:tool[_▁]|DSML|calls|invoke|parameter)[^\n>]*>/gi, '');
  if (!cleaned.trim()) return '';

  // Handle DeepSeek-Harness <compacted-summary> checkpoint block
  const compactedBlocks = [];
  cleaned = cleaned.replace(/<compacted-summary>([\s\S]*?)<\/compacted-summary>/g, (_m, summaryBody) => {
    const idx = compactedBlocks.length;
    compactedBlocks.push(
      `<details class="md-compacted-checkpoint"><summary class="md-compacted-summary-bar">上下文已自动压缩归档 · 点击展开历史检查点</summary><div class="md-compacted-body">${renderMarkdownToHtml(summaryBody)}</div></details>`
    );
    return `\n\n@@COMPACTED_BLOCK_${idx}@@\n\n`;
  });

  const normalized = normalizeMathDelimiters(cleaned).replace(/\r\n/g, '\n');

  // Extract fenced code blocks first so their contents are untouched
  const codeBlocks = [];
  let text = normalized.replace(/```([a-zA-Z0-9_+-]*)[ \t]*\n([\s\S]*?)```/g, (_m, lang, code) => {
    const idx = codeBlocks.length;
    const cleanLang = (lang || 'text').trim();
    const trimmedCode = code.replace(/\n$/, '');
    const codeRowsHtml = trimmedCode.split('\n').map((lineText, lineIdx) =>
      `<div class="ide-code-row kind-ctx"><span class="ide-ln">${lineIdx + 1}</span><span class="ide-code-cell">${highlightMdCodeLine(lineText)}</span></div>`
    ).join('');
    codeBlocks.push(
      `<div class="md-code-block"><div class="md-code-header"><span class="md-code-lang">${escapeHtml(cleanLang)}</span><button type="button" class="md-code-copy" data-copy-code="1">复制</button></div><code class="md-raw-code language-${escapeHtml(cleanLang)}" hidden>${escapeHtml(trimmedCode)}</code><div class="ide-code-table">${codeRowsHtml}</div></div>`
    );
    return `\n@@CODE_BLOCK_${idx}@@\n`;
  });

  // Extract multi-line or block $$...$$ math
  const mathBag = [];
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_m, expr) => {
    const idx = mathBag.length;
    mathBag.push(renderLatexMath(expr, true));
    return `\u0003M${idx}\u0003`;
  });

  const lines = text.split('\n');
  const htmlParts = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    const compactedMatch = trimmed.match(/^@@COMPACTED_BLOCK_(\d+)@@$/);
    if (compactedMatch) {
      htmlParts.push(compactedBlocks[Number(compactedMatch[1])] || '');
      i += 1;
      continue;
    }

    const codeMatch = trimmed.match(/^@@CODE_BLOCK_(\d+)@@$/);
    if (codeMatch) {
      htmlParts.push(codeBlocks[Number(codeMatch[1])] || '');
      i += 1;
      continue;
    }

    const mathBlockMatch = trimmed.match(/^\u0003M(\d+)\u0003$/);
    if (mathBlockMatch) {
      htmlParts.push(mathBag[Number(mathBlockMatch[1])] || '');
      i += 1;
      continue;
    }

    // Horizontal Rule
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      htmlParts.push('<hr class="md-hr" />');
      i += 1;
      continue;
    }

    // Heading #..######
    const headingMatch = line.match(/^\s*(#{1,6})\s+(.+?)\s*$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      htmlParts.push(`<h${level} class="md-h${level}">${renderInlineMarkdown(headingMatch[2], mathBag)}</h${level}>`);
      i += 1;
      continue;
    }

    // Table
    if (line.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const headers = parseTableRow(line);
      const alignments = parseTableRow(lines[i + 1]).map((cell) => {
        if (cell.startsWith(':') && cell.endsWith(':')) return 'center';
        if (cell.endsWith(':')) return 'right';
        return 'left';
      });
      i += 2;
      const bodyRows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
        bodyRows.push(parseTableRow(lines[i]));
        i += 1;
      }
      const thead = `<thead><tr>${headers
        .map((h, idx) => `<th style="text-align:${alignments[idx] || 'left'}">${renderInlineMarkdown(h, mathBag)}</th>`)
        .join('')}</tr></thead>`;
      const tbody = `<tbody>${bodyRows
        .map(
          (row) =>
            `<tr>${headers
              .map((_, idx) => `<td style="text-align:${alignments[idx] || 'left'}">${renderInlineMarkdown(row[idx] ?? '', mathBag)}</td>`)
              .join('')}</tr>`
        )
        .join('')}</tbody>`;
      htmlParts.push(`<div class="md-table-wrap"><table class="md-table">${thead}${tbody}</table></div>`);
      continue;
    }

    // Blockquote
    if (/^\s*>\s?/.test(line)) {
      const quoteLines = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^\s*>\s?/, ''));
        i += 1;
      }
      htmlParts.push(`<blockquote class="md-blockquote">${renderMarkdownToHtml(quoteLines.join('\n'))}</blockquote>`);
      continue;
    }

    // Unordered or Ordered List
    const ulMatch = line.match(/^(\s*)([-*+])\s+(.*)$/);
    const olMatch = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
    if (ulMatch || olMatch) {
      const isOrdered = Boolean(olMatch);
      const listTag = isOrdered ? 'ol' : 'ul';
      const items = [];
      while (i < lines.length) {
        const itemMatch = isOrdered
          ? lines[i].match(/^(\s*)\d+\.\s+(.*)$/)
          : lines[i].match(/^(\s*)[-*+]\s+(.*)$/);
        if (!itemMatch) break;
        let itemText = itemMatch[2];
        const taskMatch = itemText.match(/^\[([ xX])\]\s+(.*)$/);
        if (taskMatch) {
          const checked = taskMatch[1].toLowerCase() === 'x';
          items.push(
            `<li class="md-task-item"><input type="checkbox" disabled ${checked ? 'checked' : ''} /><span>${renderInlineMarkdown(taskMatch[2], mathBag)}</span></li>`
          );
        } else {
          items.push(`<li>${renderInlineMarkdown(itemText, mathBag)}</li>`);
        }
        i += 1;
      }
      htmlParts.push(`<${listTag} class="md-list">${items.join('')}</${listTag}>`);
      continue;
    }

    // Normal paragraph
    const paraLines = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^@@(?:CODE|COMPACTED)_BLOCK_\d+@@$/.test(lines[i].trim()) &&
      !/^\u0003M\d+\u0003$/.test(lines[i].trim()) &&
      !/^\s*(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+\.\s+|(?:-{3,}|\*{3,}|_{3,})$)/.test(lines[i]) &&
      !(lines[i].includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1]))
    ) {
      paraLines.push(lines[i]);
      i += 1;
    }
    if (paraLines.length) {
      htmlParts.push(`<p class="md-p">${paraLines.map((l) => renderInlineMarkdown(l, mathBag)).join('<br />')}</p>`);
    } else {
      i += 1;
    }
  }

  return htmlParts.join('\n');
}

export function renderMarkdownElement(container, rawText) {
  if (!container) return;
  if (container.__markdownSource === rawText) return;
  container.__markdownSource = rawText;
  container.classList.add('masp-markdown');
  container.innerHTML = renderMarkdownToHtml(rawText);
  container.querySelectorAll('.md-code-copy').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const codeEl = btn.closest('.md-code-block')?.querySelector('code');
      if (!codeEl) return;
      try {
        await navigator.clipboard.writeText(codeEl.textContent || '');
        btn.textContent = '已复制';
        setTimeout(() => {
          btn.textContent = '复制';
        }, 1500);
      } catch {
        btn.textContent = '复制失败';
      }
    });
  });
}
