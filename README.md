# Kit de teste — Motor FET (Projeto Anexo)

Kit de validação de ponta a ponta para a integração com o FET (`fet-cl`):
build da engine, execução contra um arquivo `.fet` real, parsing do
resultado e visualização da grade gerada.

Validado contra `Brazil.fet` (16 turmas, 27 professores, 12 disciplinas,
400 atividades): 400/400 atividades alocadas, status `SUCCESS`, 2
conflitos soft.

## Requisitos

- Docker Desktop (recomendado), **ou**
- Linux/WSL com `qtbase5-dev` e `qt5-qmake` para build local
- Python 3.9+ (para os scripts de teste e visualização)

## Início rápido

**Linux/macOS:**

```bash
docker build -t fet-cl-test .
docker run --rm -v "$(pwd):/data" fet-cl-test --version
docker run --rm -v "$(pwd):/data" --entrypoint python3 fet-cl-test \
    /data/test_fet_pipeline.py /data/Brazil.fet --fet-cl fet-cl
```

**Windows (PowerShell):**

```powershell
docker build -t fet-cl-test .
docker run --rm -v "${PWD}:/data" fet-cl-test --version
docker run --rm -v "${PWD}:/data" --entrypoint python3 fet-cl-test `
    /data/test_fet_pipeline.py /data/Brazil.fet --fet-cl fet-cl
```

> No PowerShell, o volume deve ser passado como uma única string
> (`-v "${PWD}:/data"`) e a continuação de linha usa acento grave
> `` ` ``, não `\`.

## Conteúdo do kit

| Arquivo | Descrição |
|---|---|
| `Dockerfile` | Build multi-stage do `fet-cl` (sem GUI); imagem final com Qt Core + Python 3 |
| `test_fet_pipeline.py` | Smoke test: executa `fet-cl`, parseia o resultado e o diagnóstico de conflitos |
| `visualize_timetable.py` | Gera visualização HTML da grade a partir do `.fet` + saída do `fet-cl` |
| `exemplo_grade_Brazil.html` | Visualização de referência, gerada a partir do `Brazil.fet` |
| `Brazil.fet` | Dataset de teste |

## `test_fet_pipeline.py`

Executa o `fet-cl` em um diretório temporário, valida a alocação das
atividades e o status da geração. Por padrão não persiste nenhum
arquivo — é um smoke test, não um gerador de saída.

```bash
python3 test_fet_pipeline.py Brazil.fet --fet-cl <caminho-do-fet-cl> [opções]
```

| Opção | Descrição | Default |
|---|---|---|
| `--fet-cl` | Caminho do binário `fet-cl` | busca no `PATH` |
| `--timeout` | Timeout da geração, em segundos | `60` |
| `--keep-output <dir>` | Copia a saída completa do `fet-cl` para `<dir>` antes do descarte | não persiste |

Exemplo persistindo a saída (necessário para depois visualizar a grade):

```powershell
docker run --rm -v "${PWD}:/data" --entrypoint python3 fet-cl-test `
    /data/test_fet_pipeline.py /data/Brazil.fet --fet-cl fet-cl --keep-output /data/out
```

## `visualize_timetable.py`

```bash
python3 visualize_timetable.py Brazil.fet out/timetables/Brazil/Brazil_activities.xml -o grade.html
```

Gera um HTML autocontido (sem dependências externas) com duas visões:

- **Por turma** — dias × horários, disciplina + professor por célula
- **Por professor** — dias × horários, disciplina + turma por célula; nas
  células sem aula, distingue **Disponível** (sem restrição) de
  **Indisponível** (bloqueado por `ConstraintTeacherNotAvailableTimes`,
  com o percentual do peso quando a restrição é parcial)

Também aceita o `*_data_and_timetable.fet` (saída do `fet-cl` com o
horário embutido) no lugar do `activities.xml`.

## Notas técnicas

| # | Nota |
|---|---|
| 1 | O mirror `rodolforg/fet` está desatualizado (parado em 5.37.5, 2019) e falha com assertion error ao processar arquivos `.fet` gerados por versões 7.x. Não usar para builds novos. |
| 2 | O `Dockerfile` usa `bhavyasaggi/fet` (versão 7.8.5), compatível com arquivos `.fet` 7.x. Para produção, considerar buildar a partir do tarball oficial em lalescu.ro/liviu/fet/download.html. |
| 3 | A sintaxe de seed aleatória mudou na versão 5.44.0: `--randomseedx`/`--randomseedy` foram substituídos por 6 componentes (`--randomseeds1x`/`--randomseeds2x`). Parâmetros antigos abortam a geração. |
| 4 | O arquivo de saída com as alocações é `{base}_activities.xml`, em `outputdir/timetables/{base}/` — não `activities_timetable.xml`. |
| 5 | O `fet-cl` também grava `{base}_data_and_timetable.fet` (`.fet` original com o horário embutido), útil para exportação/interoperabilidade. |
| 6 | O estágio de build requer `ca-certificates` explicitamente — a imagem `ubuntu:24.04` não o inclui por padrão, o que causa falha de verificação de certificado no `git clone`. |
| 7 | O estágio de runtime inclui `python3` apenas para viabilizar o smoke test dentro do container; pode ser removido em uma imagem de produção que só expõe o `fet-cl`. |

## Próximos testes sugeridos

1. Testes de contrato do `FetXmlMapper` — gerar `.fet` a partir de dados relacionais sintéticos e validar contra um `.fet` de referência
2. Cenário de inviabilidade — dataset deliberadamente impossível, validar tratamento de `status=IMPOSSIBLE`
3. Carga/timeout — dataset sintético grande, validar `--timelimitseconds` e timeout do processo Worker em conjunto
4. Concorrência — múltiplos jobs simultâneos, validar isolamento de diretórios temporários