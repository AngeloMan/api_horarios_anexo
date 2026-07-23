# API de Horários FET (Projeto Anexo)

API RESTful e motor assíncrono dockerizado para geração e gestão de horários escolares utilizando a engrenagem **FET (`fet-cl`)**.

## 🚀 Arquitetura

O projeto utiliza um padrão de **Fila de Tarefas Assíncronas (Task Queue / Job Pattern)** para processar a geração de horários sem bloquear requisições HTTP:

- **FastAPI** (`web`): Servidor de API RESTful com documentação OpenAPI (`/docs`).
- **Celery** (`worker`): Worker em segundo plano contendo o binário `fet-cl` compilado para resolver as grades de horário em diretórios temporários isolados.
- **Redis** (`redis`): Broker de mensagens e cache para o Celery.
- **PostgreSQL** (`db`): Banco de dados relacional para persistência de registros, status, metadados e artefatos de saída (`activities_xml`, `data_and_timetable.fet`, `soft_conflicts` e `solver_log`).

---

## 📂 Estrutura do Repositório

```text
api_horarios_anexo/
├── app/
│   ├── api/
│   │   └── endpoints/
│   │       └── horarios.py      # Endpoints RESTful (POST, GET, download, cancel, etc.)
│   ├── services/
│   │   ├── fet_runner.py        # Runner isolado do fet-cl com duplo timeout
│   │   └── visualizer.py        # Parser de alocações e renderizador HTML
│   ├── config.py                # Configurações via variáveis de ambiente
│   ├── database.py              # Conexão SQLAlchemy
│   ├── main.py                  # Ponto de entrada FastAPI
│   ├── models.py                # Modelo ORM "Horario" com índices operacionais
│   ├── schemas.py               # Schemas Pydantic v2
│   └── worker.py                # Tarefas assíncronas do Celery
├── scripts/
│   └── import_horario.py        # CLI de importação direta para o PostgreSQL (sem passar pela fila)
├── tests/                       # Suíte de testes automatizados (pytest)
├── Brazil.fet                   # Dataset real de testes (16 turmas, 400 atividades)
├── Dockerfile                   # Build multi-stage (fet-cl 7.8.5 + Python runtime)
├── docker-compose.yml           # Orquestração dos containers (web, worker, redis, db)
└── requirements.txt             # Dependências Python
```

---

## ⚡ Início Rápido (Docker)

Para subir todos os serviços (`web`, `worker`, `redis`, `db`):

```powershell
docker compose up --build -d
```

### URLs Principais:

- **Swagger UI (Documentação Interativa)**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **Health Check**: `http://localhost:8000/`

---

## 📥 Importação Direta via CLI (`scripts/import_horario.py`)

Para testar ou importar arquivos `.fet` e relatórios de saída diretamente para o banco de dados PostgreSQL sem passar pela fila do Celery/Redis:

### 1. Execução via Docker (Recomendado)

**Linux / macOS / PowerShell (Linha única):**

```bash
docker compose exec web python3 scripts/import_horario.py --input-fet Brazil.fet --nome "Teste Direto Brazil"
```

**PowerShell (Comando multilinha):**

```powershell
docker compose exec web python3 scripts/import_horario.py `
  --input-fet Brazil.fet `
  --nome "Teste Direto Brazil"
```

Se você possuir os arquivos de saída gerados (`_activities.xml` ou `_data_and_timetable.fet`):

```bash
docker compose exec web python3 scripts/import_horario.py --input-fet Brazil.fet --activities-xml out/timetables/Brazil/Brazil_activities.xml --timetable-fet out/timetables/Brazil/Brazil_data_and_timetable.fet --nome "Importação Completa Brazil"
```

### 2. Execução em Ambiente Local (Python)

```bash
python scripts/import_horario.py --input-fet Brazil.fet --nome "Teste Local"
```

O script retornará o `ID` do registro inserido e as URLs para acesso imediato no navegador:
```text
============================================================
  HORÁRIO IMPORTADO COM SUCESSO NO BANCO DE DADOS!
============================================================
  ID do Registro: 4b29c991-88f5-4d32-b7a4-56fa2b0a1d48
  Nome:          Teste Direto Brazil
  Status:        SUCCESS
------------------------------------------------------------
  Endpoints de Acesso:
  - Detalhes (JSON):   http://localhost:8000/api/v1/horarios/4b29c991-88f5-4d32-b7a4-56fa2b0a1d48
  - Grade HTML:        http://localhost:8000/api/v1/horarios/4b29c991-88f5-4d32-b7a4-56fa2b0a1d48/view
  - Alocações (JSON):  http://localhost:8000/api/v1/horarios/4b29c991-88f5-4d32-b7a4-56fa2b0a1d48/timetable
============================================================
```

---

## 🔌 Principais Endpoints

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `POST` | `/api/v1/horarios` | Cria um job a partir de JSON ou upload de arquivo `.fet` (retorna `202 Accepted`). |
| `POST` | `/api/v1/horarios/{id}/solve` | Re-executa o cálculo para um horário cadastrado. |
| `POST` | `/api/v1/horarios/{id}/cancel` | Cancela o cálculo de um job (`CANCELLED`). |
| `GET` | `/api/v1/horarios` | Lista horários com paginação (`page`, `limit`) e filtro por `status`. |
| `GET` | `/api/v1/horarios/{id}` | Retorna o status, etapa atual (`current_step`) e métricas. |
| `GET` | `/api/v1/horarios/{id}/xml` | Retorna o arquivo `activities.xml` gravado no banco. |
| `GET` | `/api/v1/horarios/{id}/timetable` | Retorna as alocações da grade formatadas em JSON. |
| `GET` | `/api/v1/horarios/{id}/view` | Renderiza a página HTML interativa da grade horária. |
| `GET` | `/api/v1/horarios/{id}/download` | Baixa os arquivos (`format=xml` para `activities.xml` ou `format=fet` para `data_and_timetable.fet`). |

---

## 🧪 Rodando os Testes

Para executar a suíte de testes dentro do container Docker:

```powershell
docker compose exec web pytest -v
```