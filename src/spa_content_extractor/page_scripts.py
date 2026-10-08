"""JavaScript avaliado dentro de cada frame da página (via Playwright `frame.evaluate`).

Mantidos aqui, separados do Python, para ajustar a heurística sem mexer no fluxo. Todos são funções puras de DOM:
recebem argumentos serializáveis e devolvem JSON.
"""

# Utilitários comuns: visibilidade, texto normalizado e um caminho CSS estável para reencontrar o elemento.
_COMMON = r"""
const visible = (el) => {
  if (!el || !el.getBoundingClientRect) return false
  const s = getComputedStyle(el)
  if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false
  const r = el.getBoundingClientRect()
  return r.width > 0 && r.height > 0
}
const clean = (t) => (t || '').replace(/\s+/g, ' ').trim()
const textOf = (el) => clean(el.innerText || el.textContent)
const cssPath = (el) => {
  const parts = []
  while (el && el.nodeType === 1 && el !== document.documentElement) {
    if (el.id && /^[A-Za-z][\w-]*$/.test(el.id) && document.querySelectorAll('#' + el.id).length === 1) {
      parts.unshift('#' + el.id)
      break
    }
    const tag = el.tagName.toLowerCase()
    const parent = el.parentElement
    if (!parent) { parts.unshift(tag); break }
    const same = Array.from(parent.children).filter((c) => c.tagName === el.tagName)
    parts.unshift(same.length > 1 ? `${tag}:nth-of-type(${same.indexOf(el) + 1})` : tag)
    el = parent
  }
  return parts.join(' > ')
}
const norm = (t) => clean(t).normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
"""

# Mapeia o menu: escolhe o container com mais itens clicáveis (ou o fixado na config), lista os itens e aponta o
# GRUPO de cada um (o pai: módulo, unidade) pelo DOM — o grupo cujo painel contém o item.
DISCOVER_NAV = (
    r"""
({ fixedContainer, candidates, itemSelector, groupSelector, noiseTexts }) => {
"""
    + _COMMON
    + r"""
  const noise = new Set(noiseTexts)
  const SUBLIST = 'ul, ol, [role=group]'
  // clicáveis por natureza; o que casa só por [aria-expanded]/[data-state] pode ser um invólucro
  const INTERACTIVE =
    'a, button, summary, [role=treeitem], [role=menuitem], [role=tab], [role=link], [role=option], [role=button], ' +
    '[tabindex], [onclick]'
  // texto do próprio item, sem o das sublistas (um <li> de módulo clicável contém as lições)
  const ownText = (el) => {
    const copy = el.cloneNode(true)
    for (const sub of copy.querySelectorAll(SUBLIST)) sub.remove()
    return clean(copy.innerText || copy.textContent)
  }
  const inSublist = (root, el) => {
    for (let p = el.parentElement; p && p !== root; p = p.parentElement) if (p.matches(SUBLIST)) return true
    return false
  }
  // invólucro: contém itens (fora das próprias sublistas) e não é clicável — o painel ou o bloco inteiro de uma
  // sanfona — ou é clicável mas contém vários itens. Não vira item; os de dentro, sim.
  const isWrapper = (el) => {
    const inner = Array.from(el.querySelectorAll(itemSelector)).filter((c) => visible(c) && !inSublist(el, c))
    return inner.length > 0 && (!el.matches(INTERACTIVE) || inner.length > 1)
  }
  const holderOf = (container, el) => {
    const h = el.closest('li, [role=treeitem], details')
    return h && h !== container && container.contains(h) ? h : null
  }
  const matchesGroup = (el) => {
    if (!groupSelector) return false
    try {
      return el.matches(groupSelector) || Array.from(el.querySelectorAll(groupSelector)).some((x) => !inSublist(el, x))
    } catch (e) {
      return false
    }
  }
  // grupo = abre/fecha subitens: aria-expanded, data-state de abrir/fechar, <summary>, aria-haspopup, classe
  // collapsed/expanded, `expanders` da config (no item ou num ícone dele) ou sublista, mesmo oculta, no mesmo <li>
  const isGroup = (container, el) => {
    const state = el.getAttribute('data-state')
    const popup = el.getAttribute('aria-haspopup')
    if (el.hasAttribute('aria-expanded') || el.tagName === 'SUMMARY') return true
    if (state && /^(open|closed|expanded|collapsed)$/.test(state)) return true
    if (popup && popup !== 'false') return true
    if (/(^|\s)(is-)?(collapsed|expanded)(\s|$)/.test(el.getAttribute('class') || '') || matchesGroup(el)) return true
    const holder = holderOf(container, el)
    return !!holder && Array.from(holder.querySelectorAll(SUBLIST)).some((s) => !s.contains(el))
  }
  const signature = (el) => el.tagName + '.' + ((el.getAttribute('class') || '').trim().split(/\s+/)[0] || '')
  // onde ficam os subitens de um grupo: o alvo de aria-controls, o <li>/treeitem/<details> do grupo ou, na sanfona sem
  // lista, o irmão seguinte do cabeçalho (subindo pelos invólucros de um filho só, como <h3><button>) — desde que não
  // seja o bloco do grupo seguinte (mesma tag e classe) nem outro item
  const panelsOf = (container, el, itemEls) => {
    const panels = []
    for (const id of (el.getAttribute('aria-controls') || '').split(/\s+/)) {
      const p = id ? document.getElementById(id) : null
      if (p) panels.push(p)
    }
    const holder = holderOf(container, el)
    if (holder) return [...panels, holder]
    let head = el
    while (head.parentElement && head.parentElement !== container && head.parentElement.children.length === 1)
      head = head.parentElement
    const next = head.nextElementSibling
    if (next && !itemEls.has(next) && signature(next) !== signature(head)) panels.push(next)
    return panels
  }
  // âncora para uma seção da própria página (sumário da lição), não um tópico
  const inPage = (el) => {
    const href = el.getAttribute('href') || ''
    if (!/^#[^/!]/.test(href)) return false
    try {
      return !!document.getElementById(decodeURIComponent(href.slice(1)))
    } catch (e) {
      return false
    }
  }
  const itemsIn = (container) => {
    const kept = []
    for (const el of container.querySelectorAll(itemSelector)) {
      if (!visible(el) || isWrapper(el)) continue
      const title = ownText(el)
      // rótulo dentro de outro item (ex.: <span>/<a> dentro do <li> clicável): fica só o de fora
      const outer = el.parentElement && el.parentElement.closest(itemSelector)
      if (outer && container.contains(outer) && !isWrapper(outer) && norm(ownText(outer)) === norm(title)) continue
      if (title.length < 2 || title.length > 140 || noise.has(norm(title))) continue
      kept.push({ el, title, group: isGroup(container, el) })
    }
    // pai = o grupo de painel mais interno que contém o item
    const itemEls = new Set(kept.map((k) => k.el))
    const groups = kept.filter((k) => k.group).map((k) => ({ k, panels: panelsOf(container, k.el, itemEls) }))
    return kept.map((item) => {
      let best = null
      for (const { k, panels } of groups) {
        if (k === item || item.el.contains(k.el)) continue
        for (const p of panels)
          if (p.contains(item.el) && (!best || (best.panel !== p && best.panel.contains(p)))) best = { k, panel: p }
      }
      return {
        title: item.title,
        selector: cssPath(item.el),
        href: item.el.getAttribute('href') || null,
        group: item.group,
        parent: best ? kept.indexOf(best.k) : null,
        inPage: inPage(item.el),
      }
    })
  }
  let containers = []
  if (fixedContainer) containers = Array.from(document.querySelectorAll(fixedContainer))
  else for (const sel of candidates) for (const el of document.querySelectorAll(sel)) containers.push(el)
  let best = null
  for (const c of containers) {
    if (!visible(c)) continue
    const items = itemsIn(c)
    if (items.length < 2) continue
    // itens curtos e numerosos parecem menu; muito texto corrido parece conteúdo
    const avg = items.reduce((s, i) => s + i.title.length, 0) / items.length
    const textLen = textOf(c).length
    const linkDensity = items.reduce((s, i) => s + i.title.length, 0) / Math.max(textLen, 1)
    const score = items.length * Math.min(1, linkDensity * 1.5) * (avg <= 80 ? 1 : 0.5)
    if (!best || score > best.score) best = { score, container: c, items }
  }
  if (!best) return null
  return { container: cssPath(best.container), score: best.score, items: best.items }
}
"""
)

# Abre grupos fechados (seletores `expanders` + <details>) visíveis dentro do menu. Devolve quantos abriu; quem chama
# repete em rodadas, porque cada nível aberto revela o seguinte.
EXPAND_COLLAPSED = r"""
({ containerSelector, expanders }) => {
  const root = containerSelector ? document.querySelector(containerSelector) : document
  if (!root) return 0
  let opened = 0
  for (const d of root.querySelectorAll('details:not([open])')) { d.open = true; opened++ }
  for (const el of root.querySelectorAll(expanders)) {
    const r = el.getBoundingClientRect()
    if (r.width === 0 && r.height === 0) continue  // dentro de um grupo ainda fechado: abre na próxima rodada
    try { el.click(); opened++ } catch (e) {}
  }
  return opened
}
"""

# Acha o container de conteúdo: o fixado na config ou o candidato com mais texto fora do menu.
FIND_CONTENT = (
    r"""
({ fixedContainer, candidates, navSelector }) => {
"""
    + _COMMON
    + r"""
  const nav = navSelector ? document.querySelector(navSelector) : null
  const pool = []
  if (fixedContainer) pool.push(...document.querySelectorAll(fixedContainer))
  else for (const sel of candidates) pool.push(...document.querySelectorAll(sel))
  if (!fixedContainer && document.body) pool.push(document.body)
  let best = null
  for (const el of pool) {
    if (!visible(el)) continue
    if (nav && (el === nav || nav.contains(el))) continue
    let len = textOf(el).length
    // o corpo inteiro inclui o menu: desconta para preferir um container específico
    if (nav && el.contains(nav)) len -= textOf(nav).length
    if (el === document.body) len *= 0.6
    if (!best || len > best.len) best = { len, el }
  }
  if (!best || best.len < 1) return null
  const heading = best.el.querySelector('h1, h2, [role=heading]')
  return { selector: cssPath(best.el), textLength: Math.round(best.len), heading: heading ? textOf(heading) : null }
}
"""
)

# Serializa o container em HTML "achatado": inclui shadow DOM aberto e iframes da mesma origem, descarta o que
# está oculto. É o que vai para a limpeza e a conversão em Markdown.
SERIALIZE = (
    r"""
(selector) => {
"""
    + _COMMON
    + r"""
  const root = document.querySelector(selector)
  if (!root) return null
  const KEEP = ['href', 'src', 'alt', 'title', 'colspan', 'rowspan', 'class', 'id', 'role', 'aria-label', 'aria-hidden', 'lang']
  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'svg', 'canvas', 'video', 'audio', 'link', 'meta'])
  const escText = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const escAttr = (t) => escText(t).replace(/"/g, '&quot;')
  const ser = (node) => {
    if (node.nodeType === 3) return escText(node.textContent)
    if (node.nodeType !== 1) return ''
    const tag = node.tagName.toLowerCase()
    if (SKIP.has(tag)) return ''
    if (node !== root && !visible(node) && tag !== 'br' && tag !== 'img') return ''
    let attrs = ''
    for (const a of KEEP) if (node.hasAttribute(a)) attrs += ` ${a}="${escAttr(node.getAttribute(a))}"`
    let inner = ''
    if (tag === 'iframe') {
      try {
        const doc = node.contentDocument
        if (doc && doc.body) inner = ser(doc.body)
      } catch (e) { /* outra origem: tratado como frame próprio pelo Playwright */ }
      return `<div data-iframe="${escAttr(node.getAttribute('src') || '')}">${inner}</div>`
    }
    if (node.shadowRoot) for (const c of node.shadowRoot.childNodes) inner += ser(c)
    for (const c of node.childNodes) inner += ser(c)
    if (tag === 'br' || tag === 'img' || tag === 'hr') return `<${tag}${attrs}>`
    return `<${tag}${attrs}>${inner}</${tag}>`
  }
  return ser(root)
}
"""
)

# Espera o frame ficar quieto: `quietMs` sem mutações no DOM (ou estoura em `timeoutMs`). Devolve ms esperados.
WAIT_QUIET = r"""
({ quietMs, timeoutMs }) => new Promise((resolve) => {
  let last = Date.now()
  const start = last
  const obs = new MutationObserver(() => { last = Date.now() })
  obs.observe(document, { subtree: true, childList: true, characterData: true })
  const timer = setInterval(() => {
    const now = Date.now()
    if (now - last >= quietMs || now - start >= timeoutMs) {
      clearInterval(timer)
      obs.disconnect()
      resolve(now - start)
    }
  }, 100)
})
"""

# Há indicador de carregamento visível?
IS_LOADING = (
    r"""
(selector) => {
"""
    + _COMMON
    + r"""
  return Array.from(document.querySelectorAll(selector)).some(visible)
}
"""
)

# Estado de um grupo do menu: 'open' | 'closed' | 'unknown' | 'missing'.
GROUP_STATE = r"""
(selector) => {
  const el = document.querySelector(selector)
  if (!el) return 'missing'
  const aria = el.getAttribute('aria-expanded')
  if (aria === 'true') return 'open'
  if (aria === 'false') return 'closed'
  const state = el.getAttribute('data-state')
  if (state === 'open' || state === 'expanded') return 'open'
  if (state === 'closed' || state === 'collapsed') return 'closed'
  if (el.tagName === 'SUMMARY') return el.parentElement && el.parentElement.open ? 'open' : 'closed'
  const cls = el.getAttribute('class') || ''
  if (/(^|\s)(is-)?collapsed(\s|$)/.test(cls)) return 'closed'
  if (/(^|\s)(is-)?expanded(\s|$)/.test(cls)) return 'open'
  return 'unknown'
}
"""
