# spa-content-extractor

Extrai o conteúdo textual de aplicações web do tipo SPA — menus dinâmicos, módulos que carregam por JavaScript,
conteúdo dentro de iframes (inclusive aninhados e de outra origem) e shadow DOM, URLs que não mudam — para um arquivo
Markdown por item de navegação. Um passo opcional usa o Claude no SAP AI Core para deixar cada arquivo pronto para
base de conhecimento.

## Como funciona

| Passo | Comando | O que faz |
| --- | --- | --- |
| 1. Login | `uv run spa-extract login <url>` | Abre o navegador visível; **você** faz o login e pressiona Enter no terminal. A sessão fica em `.auth/<host>.json` (permissão 600, fora do git). O extrator nunca digita credenciais. |
| 2. Mapa | `uv run spa-extract map <url> [--start-click "Resume learning"] [--headed --pause]` | Clica no(s) botão(ões) de entrada, acha o menu sozinho (em qualquer frame), abre os grupos nível por nível e lista os itens (`▸` = grupo). Use para conferir antes de extrair. |
| 3. Extração | `uv run spa-extract extract <url> [--start-click TEXTO] [--headed] [--only REGEX] [--limit N] [--include-groups] [--pause]` | Para cada item: clica, espera o conteúdo **estabilizar** e salva `output/<host>/<data>/raw/NNN-titulo.md` com front matter (título, caminho "Módulo › Unidade", frame, data) e um `manifest.json`. |
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

### Ação de entrada e menus recursivos

- `--start-click "Resume learning"` (ou `start_click` no `extractor.toml`) clica no botão pelo texto logo ao abrir; se o
  clique abrir outra aba, a extração segue nela. Repita a opção para vários cliques em sequência.
- O menu é aberto em rodadas — módulo, unidade, lição — até não aparecer item novo. Grupos são reconhecidos por
  `aria-expanded`, `data-state`, `<details>` ou classes `collapsed`/`expanded`; acrescente a classe do alvo em
  `selectors.expanders` se precisar.

### robots.txt

O extrator respeita o `robots.txt`: se o site proíbe robôs, ele para com uma mensagem. Para um site seu ou com
permissão por escrito que bloqueia robôs, cadastre o host e a autorização em `authorized_hosts` no `extractor.toml`.

### Ritmo

Uma aba, uma ação por vez, pausas aleatórias de 1,5 a 4 s entre itens. É para não sobrecarregar o servidor do alvo —
não há técnicas de evasão de detecção. Use só em conteúdo que você tem direito de acessar e extrair (respeitando o
`robots.txt` e os termos de uso do site).

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
