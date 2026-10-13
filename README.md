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
| 3. Extração | `uv run spa-extract extract <url> [--start-click TEXTO] [--name NOME] [--headed] [--only REGEX] [--limit N] [--include-groups] [--pause]` | Para cada tópico: clica, espera o conteúdo **estabilizar** e salva em `output/NN-<curso>/<data-hora>/`, **uma pasta por grupo do menu** (`01-modulo/02-unidade/01-topico.md`), com front matter (título, caminho "Módulo › Unidade", frame, data) e um `manifest.json`. |
| 4. Formatação (opcional) | `uv run spa-extract format output/NN-<curso>` | Claude 4.6 Sonnet no SAP AI Core transforma cada `.md` da extração mais recente do curso (ou da pasta de data indicada) no mesmo caminho em `knowledge/NN-<curso>/<data-hora>/`, limpo (hierarquia, listas, termos em negrito, código, imagens comentadas). |

### Espera robusta ("renderizado, não só carregado")

1. rede ociosa (melhor esforço);
2. nenhum indicador de carregamento visível (`spinner`, `aria-busy`…), em nenhum frame;
3. `quiet_ms` sem mutações no DOM em **todos** os frames;
4. o texto do conteúdo diferente do que estava na tela antes do clique e igual em duas leituras seguidas.

### Limpeza de ruído

Remove navegação, cabeçalho, rodapé, botões, barras de ferramentas, diálogos, migalhas e textos de controle
("Próximo", "Anterior", "Marcar como concluído"…). Imagens viram `<!-- Imagem presente aqui: … -->`; blocos de código
mantêm a linguagem.

### Ação de entrada e ordem de navegação

- `--start-click "Resume Learning"` (ou `start_click` no `extractor.toml`) clica no botão pelo texto (sem diferenciar
  maiúsculas) e **só segue quando a página do conteúdo abriu de verdade**: outra URL, outra aba (mesmo que demore) ou o
  botão sumiu e o texto da página mudou (SPA na mesma URL). Sem transição em `transition_timeout_s` (30 s), para com
  uma mensagem — nunca extrai a página de entrada. Depois espera o menu do player aparecer.
- `--wait-for "texto ou seletor"` (ou `start_wait_for`): opcional, algo que só existe no player; o extrator espera ele
  aparecer antes de começar.
- O terminal mostra cada etapa (clique, espera, "página do conteúdo carregada: …"); sem `--start-click`, avisa que
  vai extrair a página que abriu.
- O menu é percorrido **em profundidade, sempre a partir do primeiro item**: abre o primeiro módulo, entra em cada
  tópico (e em cada unidade dentro dele, recursivamente), extrai, e só então passa ao segundo módulo — até o último.
  Não importa em que lição o player abriu (cache/"retomar de onde parou") nem se o menu é "sanfona" (abrir um módulo
  fecha os outros): antes de cada clique o caminho Módulo › Unidade é reaberto.
- **Cada curso é uma pasta direto em `output/`**, numerada na ordem em que os cursos são baixados (`00-`, `01-`,
  `02-`…), com o nome tirado do título da página de entrada (ou `--name`). Cada extração fica numa pasta com a data e
  a hora dentro do curso; baixar de novo o mesmo curso (mesma URL) reaproveita a pasta e o número dele e cria outra
  pasta de data. Dentro dela, a saída repete o menu: **cada grupo (módulo, unidade) é uma pasta e cada tópico é um
  arquivo**, numerados pela posição no menu (o `00-` dentro de um módulo fica para a página do próprio módulo, com
  `--include-groups`):

  ```text
  output/
    00-managing-business-processes-with-sap-signavio-solutions/
      20261008-150524/
        manifest.json
        01-exploring-the-foundations-of-business-processes/
          01-starting-your-journey.md
          02-defining-the-core-elements-of-a-process.md
        02-introducing-business-process-management/
          01-defining-business-process-management.md
    01-<proximo-curso>/
      <data-hora>/
  ```

  Títulos repetidos ("Resumo", "Quiz") em módulos diferentes ficam cada um na pasta do seu módulo. Com
  `--include-groups`, a página do próprio módulo vira `00-<modulo>.md` dentro da pasta dele.
- Um item é grupo (pasta) quando o menu o marca (`aria-expanded`, `data-state` de abrir/fechar, `<details>`, classes
  `collapsed`/`expanded`), quando tem uma sublista no mesmo `<li>` (mesmo oculta), quando é o cabeçalho de uma sanfona
  sem lista (`<h3><button>` + painel) ou quando, ao ser clicado, **revela subitens** — nesse caso o arquivo dele sai do
  resultado e os subitens vão para a pasta. O `map` também clica em cada tópico para mostrar essa estrutura. Se um
  módulo ainda virar arquivo, acrescente a classe do cabeçalho (ou do ícone dele) em `selectors.expanders`.
- Âncoras para seções da própria lição (o sumário que alguns players mostram embaixo da lição aberta) não viram
  tópicos.

### robots.txt

O extrator respeita o `robots.txt`: se o site proíbe robôs, ele para com uma mensagem. Para um site seu ou com
permissão por escrito que bloqueia robôs, cadastre o host e a autorização em `authorized_hosts` no `extractor.toml`.

### Ritmo

Uma aba, uma ação por vez, pausas aleatórias de 1,5 a 4 s entre itens. É para não sobrecarregar o servidor do alvo —
não há técnicas de evasão de detecção. Use só em conteúdo que você tem direito de acessar e extrair (respeitando o
`robots.txt` e os termos de uso do site).

## SAP Help Portal (`spa-extract help`)

Comando próprio para os documentos do help.sap.com, separado do fluxo dos cursos:

```bash
uv run spa-extract help https://help.sap.com/docs/sap-ai-core/sap-ai-core-service-guide/initial-setup --group ai-core
```

- Aceita a URL de qualquer tópico do documento (ou só `…/docs/<produto>/<documento>`); `?version=` e `?locale=` são
  respeitados (padrão `LATEST` e `en-US`).
- Não abre navegador nem clica no menu: lê o sumário da coluna da esquerda e o HTML de cada tópico pelas mesmas chamadas
  JSON que a própria página usa (`/http.svc/deliverableMetadata` e `/http.svc/pagecontent`), com o mesmo ritmo
  educado entre páginas.
- O sumário é percorrido em profundidade, do primeiro item. Item com filhos vira pasta e a página dele fica como
  `00-<item>.md` dentro dela (no Help Portal os grupos também têm conteúdo):
  `output/NN-<grupo>/NN-<documento>/<data-hora>/03-initial-setup/00-initial-setup.md`, `…/01-enabling-…/01-….md`.
- `--only REGEX` (no caminho do sumário), `--limit N`, `--name` e `--group` como no `extract`. No lote
  (`scripts/lote.py`), URLs `help.sap.com/docs/…` usam este comando sozinhas.
- O `robots.txt` do help.sap.com proíbe robôs: só roda com o host em `authorized_hosts` no `extractor.toml`.

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
