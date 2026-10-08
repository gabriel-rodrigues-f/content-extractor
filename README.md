# spa-content-extractor

Extrai o conteúdo textual de aplicações web do tipo SPA — menus dinâmicos, módulos que carregam por JavaScript,
conteúdo dentro de iframes (inclusive aninhados e de outra origem) e shadow DOM, URLs que não mudam — para um arquivo
Markdown por item de navegação. Um passo opcional usa o Claude no SAP AI Core para deixar cada arquivo pronto para
base de conhecimento.

## Como funciona

| Passo | Comando | O que faz |
| --- | --- | --- |
| 1. Login | `uv run spa-extract login <url>` | Abre o navegador visível; **você** faz o login e pressiona Enter no terminal. A sessão fica em `.auth/<host>.json` (permissão 600, fora do git). O extrator nunca digita credenciais. |
| 2. Mapa | `uv run spa-extract map <url>` | Acha o menu sozinho (barra lateral, árvore, lista de tópicos — em qualquer frame), abre módulos recolhidos e lista os itens. Use para conferir antes de extrair. |
| 3. Extração | `uv run spa-extract extract <url> [--headed] [--only REGEX] [--limit N]` | Para cada item: clica, espera o conteúdo **estabilizar** e salva `output/<host>/<data>/raw/NNN-titulo.md` com front matter (título, módulo, frame, data) e um `manifest.json`. |
| 4. Formatação (opcional) | `uv run spa-extract format output/<host>/<data>` | Claude 4.6 Sonnet no SAP AI Core transforma cada `raw/*.md` em `knowledge/*.md` limpo (hierarquia, listas, termos em negrito, código, imagens comentadas). |

### Espera robusta ("renderizado, não só carregado")

1. rede ociosa (melhor esforço);
2. nenhum indicador de carregamento visível (`spinner`, `aria-busy`…), em nenhum frame;
3. `quiet_ms` sem mutações no DOM em **todos** os frames;
4. o texto do conteúdo diferente do que estava na tela antes do clique e igual em duas leituras seguidas.

### Limpeza de ruído

Remove navegação, cabeçalho, rodapé, botões, barras de ferramentas, diálogos, migalhas e textos de controle
("Próximo", "Anterior", "Marcar como concluído"…). Imagens viram `<!-- Imagem presente aqui: … -->`; blocos de código
mantêm a linguagem.

### Ritmo

Uma aba, uma ação por vez, pausas aleatórias de 1,5 a 4 s entre itens. É para não sobrecarregar o servidor do alvo —
não há técnicas de evasão de detecção. Use só em conteúdo que você tem direito de acessar e extrair.

## Instalação

```sh
brew install uv          # gerenciador de projeto/Python
uv sync                  # Python 3.12 + dependências no .venv
uv run playwright install chromium   # só se o Chromium do Playwright ainda não estiver no cache
```

## Ajustar a um alvo

Copie `extractor.example.toml` para `extractor.toml` e fixe os seletores (menu, conteúdo, ruído) — os comentários
indicam onde. Sem arquivo, vale a detecção automática de `src/spa_content_extractor/config.py`.

## SAP AI Core (passo 4)

Uma **pessoa** roda, com `cf login` feito e acesso à org de IA:

```sh
scripts/create-local-ai-core-key.sh
```

O script grava `.env.aicore` (permissão 600, fora do git) sem imprimir nada; o `format` converte a service key nas
variáveis do SDK só dentro do próprio processo.

## Testes

```sh
uv run pytest            # ponta a ponta contra uma SPA de exemplo (tests/fixtures/spa): iframes aninhados,
uv run ruff check src tests   # renderização progressiva, shadow DOM, menu recolhido, ruído de interface
```
