# Motor de Otimização de Rotas - Malha Nacional (Brasil)

API de alta performance desenvolvida com **FastAPI** e **Google OR-Tools**, integrada a um servidor local do **OSRM (Open Source Routing Machine)**. Este ecossistema foi projetado para calcular matrizes de distância e tempo em milissegundos e gerar rotas comerciais otimizadas utilizando a malha rodoviária completa do Brasil.

---

## 🎯 Requisitos do Projeto & Escopo

Conforme detalhado no [contexto.md](file:///c:/Users/angel/Documents/teste_rotas_brasil/contexto.md):

* **Objetivo Principal**: Criar um motor logístico local capaz de receber uma lista arbitrária de coordenadas geográficas (latitude/longitude), calcular a matriz de custo (tempo e distância) em milissegundos e determinar a sequência ótima de visitação, resolvendo o Problema do Caixeiro Viajante (TSP).
* **Escopo Geográfico**: Cobertura completa do território nacional brasileiro utilizando dados atualizados do OpenStreetMap (OSM).
* **Desempenho**: Resolução de malhas interestaduais e intermunicipais complexas em tempo real (tempo de processamento algorítmico inferior a 1 segundo).
* **Segurança**: Camada de autenticação baseada em tokens (API Keys) dinâmicos com gerenciamento em memória.

---

## 🏗️ Arquitetura do Sistema e Stack Tecnológico

A arquitetura e infraestrutura são compostas por:

* **Back-End (FastAPI)**: Interface HTTP moderna escolhida pela alta velocidade de execução, tipagem estrita de dados com o Pydantic e geração nativa de documentação interativa via Swagger UI. Veja mais em [app.py](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py).
* **Motor de Otimização (Google OR-Tools)**: Resolvedor de restrições e otimização encarregado de calcular a rota ótima via a estratégia de busca inicial `PATH_CHEAPEST_ARC`.
* **Servidor de Roteamento (OSRM)**: Executável de alto desempenho em C++ configurado com o algoritmo MLD (Multi-Level Dijkstra) consumindo grafos binários de aproximadamente 12 GB gerados a partir do extrato nacional do Geofabrik. Configurado via [docker-compose.yml](file:///c:/Users/angel/Documents/teste_rotas_brasil/docker-compose.yml).

> [!IMPORTANT]
> **Uso da Tag Estável `ghcr.io/project-osrm/osrm-backend:v5.27.1`**
> O ambiente dockerizado foi travado rigidamente na tag estável `v5.27.1`. Versões mais recentes (como `v26.7.2` ou `latest`) apresentam erros de incompatibilidade de cabeçalhos binários estruturados (erro de *Fingerprint* no arquivo `.osrm.cells`) quando executadas com grafos gerados externamente (ex. via Google Colab).

---

## 🛠️ Pré-requisitos de Hardware (WSL2 / Windows)

Devido ao tamanho da malha rodoviária do Brasil, o servidor OSRM exige cerca de **12 GB estáticos de RAM** na inicialização. Como o subsistema do Windows para Linux (WSL2) limita por padrão o uso de hardware a 50% da máquina hospedeira, é necessário ajustar os limites globais para evitar encerramentos silenciosos por falta de memória (*Out of Memory*).

### Passo a Passo de Configuração do WSL2:

1. Pressione `Windows + R`, digite `%USERPROFILE%` e pressione **Enter**.
2. Crie ou edite o arquivo chamado `.wslconfig` (remova a extensão `.txt` se criar um novo).
3. Insira as seguintes linhas para configurar a RAM e a memória swap:
   ```ini
   [wsl2]
   memory=14GB
   swap=4GB
   ```
4. Abra o PowerShell como Administrador e execute o comando abaixo para reiniciar o subsistema e aplicar os novos limites:
   ```powershell
   wsl --shutdown
   ```

---

## 🚀 Como Inicializar o Ambiente

1. Certifique-se de que os arquivos estruturados do mapa do Brasil (`brazil-latest.osrm*`) estão no diretório `./osrm-local`.
2. No diretório raiz do projeto, execute o comando para construir e inicializar os contêineres definidos no [Dockerfile](file:///c:/Users/angel/Documents/teste_rotas_brasil/Dockerfile) e [docker-compose.yml](file:///c:/Users/angel/Documents/teste_rotas_brasil/docker-compose.yml):
   ```powershell
   docker compose up -d --build
   ```

> [!NOTE]
> O contêiner `osrm_matriz` leva entre 1 e 2 minutos para carregar todo o mapa na memória RAM. Você pode monitorar a inicialização via `docker logs -f osrm_matriz`. O sistema estará operacional quando visualizar a mensagem `[info] running and waiting for requests`.

### 📓 Processamento da Malha Rodoviária via Google Colab

Como a compilação e preparação da malha rodoviária nacional exige alto consumo de hardware (cerca de 50 GB de RAM para extração de dados do Brasil completo), disponibilizamos no repositório o notebook do Google Colab:
👉 [processar_osrm_brasil_colab.ipynb](file:///c:/Users/angel/Documents/teste_rotas_brasil/processar_osrm_brasil_colab.ipynb)

#### O que o notebook realiza:
1. **Instalação do OSRM:** Clona o OSRM Backend na mesma tag compatível (`v5.27.1`) e compila suas ferramentas nativas.
2. **Download e Processamento:** Realiza a compilação matemática da malha nacional (`brazil-latest.osm.pbf`) executando as etapas sequenciais de extração, partição e customização (`osrm-extract`, `osrm-partition` e `osrm-customize`).
3. **Persistência em Nuvem:** Compacta os arquivos compilados (`brazil-latest.osrm*`) em um arquivo `brazil-latest.tar` e salva-o diretamente no seu Google Drive conectado em `/MyDrive/OSRM_Brasil_Compilado`.

#### Como usar as saídas geradas:
1. Abra e execute o notebook [processar_osrm_brasil_colab.ipynb](file:///c:/Users/angel/Documents/teste_rotas_brasil/processar_osrm_brasil_colab.ipynb) no Google Colab (recomenda-se ambiente com RAM estendida, como Colab Pro).
2. Após o término da execução bem-sucedida, baixe o arquivo `brazil-latest.tar` gerado no seu Google Drive.
3. Extraia o conteúdo deste arquivo `.tar` diretamente na pasta `./osrm-local` na raiz deste projeto.


---

## ⚙️ Regras de Negócio e Limitações

### 1. Validação de Payload
Cada ponto de parada enviado para a API é validado estritamente por meio do modelo [Localidade](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py#L37) (Pydantic), exigindo:
* `nome`: identificador do ponto (string)
* `lat`: latitude em ponto flutuante (float)
* `lon`: longitude em ponto flutuante (float)

### 2. Limitações de Links de Despacho GPS
Ao gerar os links de despacho de rotas para os motoristas no retorno da API:
* **Google Maps**: Possui limite estrito de **10 paradas** (1 origem + até 9 destinos intermediários). Links que excedem essa quantidade removem pontos finais silenciosamente.
* **Apple Maps**: Oferece suporte nativo para até **15 paradas** em links universais.
* **Abordagem de Escala**: Para frotas que visitem mais de 10 localidades, a interface deve fracionar a rota consolidada em sub-rotas/pernas menores de ponto a ponto.

---

## 🔐 Segurança e Autenticação

A API utiliza autenticação por meio do cabeçalho customizado `X-API-Key` ou através de `Authorization: Bearer <API_KEY>` avaliados por [get_usuario_autenticado](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py#L133). Se a chave estiver incorreta, inativa ou expirada, o sistema retornará `403 Forbidden`.

### 1. Hashing SHA-256 e Segurança
Por motivos de segurança, o servidor **nunca** armazena a chave de API em texto puro. Armazena-se apenas o hash SHA-256 da chave. O segredo em texto puro (ex: `sk_live_...`) é retornado uma única vez no momento da criação da chave.

### 2. Chave Mestre de Testes (In-Memory)
Ao inicializar o [app.py](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py), o sistema pré-carrega uma chave mestre estável:
* **Segredo (para autenticação):** `sk_test_user1`
* **ID:** `master_01`
* **Escopos:** `["admin", "otimizar"]`
* **Ativa:** Sim (protegida contra desativação)
* **Expiração:** Vitalícia (None)

---

## 🗺️ Endpoints da API

A documentação interativa Swagger pode ser acessada localmente em:
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

### 1. Otimização de Rotas (`POST /otimizar-rota`)
Chama [otimizar_rota](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py#L362) para ordenar a sequência ideal de visitas minimizando o tempo total de viagem através do algoritmo do OR-Tools alimentado por OSRM.

* **Payload Exemplo (Caso de Teste Interestadual - 10 Localidades)**:
```json
{
  "pontos": [
    { "nome": "Deposito_Sao_Paulo", "lat": -23.5505, "lon": -46.6333 },
    { "nome": "Campinas", "lat": -22.9056, "lon": -47.0608 },
    { "nome": "Sao_Carlos", "lat": -22.0081, "lon": -47.8908 },
    { "nome": "Curitiba", "lat": -25.4290, "lon": -49.2671 },
    { "nome": "Londrina", "lat": -23.3106, "lon": -51.1628 },
    { "nome": "Guarapuava", "lat": -25.3954, "lon": -51.4578 },
    { "nome": "Pato_Branco", "lat": -26.2295, "lon": -52.6712 },
    { "nome": "Cascavel", "lat": -24.9578, "lon": -53.4597 },
    { "nome": "Toledo", "lat": -24.7115, "lon": -53.7427 },
    { "nome": "Foz_do_Iguacu", "lat": -25.5478, "lon": -54.5882 }
  ]
}
```

* **Resposta Exemplo (JSON)**:
```json
{
  "status": "sucesso",
  "usuario_autenticado": {
    "id": "master_01",
    "name": "Chave de Testes",
    "scopes": ["admin", "otimizar"],
    "active": true,
    "expires_at": null,
    "created_at": "2026-07-10T13:30:00.000000",
    "last_used_at": "2026-07-10T13:32:00.000000"
  },
  "tempo_total_minutos": 1987.47,
  "distancia_total_km": 2445.93,
  "ordem_entrega": [
    { "nome": "Deposito_Sao_Paulo", "lon": -46.6333, "lat": -23.5505 },
    { "nome": "Curitiba", "lon": -49.2671, "lat": -25.429 },
    ...
    { "nome": "Deposito_Sao_Paulo", "lon": -46.6333, "lat": -23.5505 }
  ],
  "links_navegacao": {
    "google_maps": "https://www.google.com/maps/dir/?api=1...",
    "apple_maps": "https://maps.apple.com/directions?source=..."
  }
}
```

### 2. Gerenciamento de API Keys (`/api-keys`)
Estes endpoints requerem autenticação administrativa com o componente nativo de segurança `HTTPBearer` do FastAPI (que exibe o botão **Authorize** e o ícone de cadeado no Swagger UI). Para homologação local, clique no cadeado da rota e insira qualquer string não vazia.

* **`POST /api-keys`**: Cria uma nova chave de API através de [criar_api_key](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py#L206). Retorna a chave em texto puro apenas uma vez na resposta.
* **`GET /api-keys`**: Lista os metadados (sem expor a chave ou o hash) de todas as chaves cadastradas via [listar_api_keys](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py#L219).
* **`PATCH /api-keys/{id}`**: Realiza atualizações parciais (nome, escopos, ativo) em uma chave de API através de [atualizar_api_key](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py#L228). Bloqueia a desativação de `master_01`.
* **`DELETE /api-keys/{id}`**: Realiza soft delete da chave (active=False) via [remover_api_key](file:///c:/Users/angel/Documents/teste_rotas_brasil/app.py#L249). Bloqueia a desativação da chave master.

---

## 🧪 Teste Rápido via PowerShell

Valide o funcionamento executando o bloco abaixo no PowerShell da sua máquina:

```powershell
# 1. Configura a chave de autenticação logística (X-API-Key ou Bearer)
$headers = @{ "X-API-Key" = "sk_test_user1" }

# 2. Prepara o payload de 10 localidades
$body = @{
    pontos = @(
        @{ nome = "Deposito_Sao_Paulo"; lat = -23.5505; lon = -46.6333 },
        @{ nome = "Campinas"; lat = -22.9056; lon = -47.0608 },
        @{ nome = "Sao_Carlos"; lat = -22.0081; lon = -47.8908 },
        @{ nome = "Curitiba"; lat = -25.4290; lon = -49.2671 },
        @{ nome = "Londrina"; lat = -23.3106; lon = -51.1628 },
        @{ nome = "Guarapuava"; lat = -25.3954; lon = -51.4578 },
        @{ nome = "Pato_Branco"; lat = -26.2295; lon = -52.6712 },
        @{ nome = "Cascavel"; lat = -24.9578; lon = -53.4597 },
        @{ nome = "Toledo"; lat = -24.7115; lon = -53.7427 },
        @{ nome = "Foz_do_Iguacu"; lat = -25.5478; lon = -54.5882 }
    )
} | ConvertTo-Json -Depth 5

# 3. Dispara a requisição
Invoke-RestMethod -Uri "http://localhost:8000/otimizar-rota" -Method Post -Headers $headers -ContentType "application/json" -Body $body
```
icado` será atualizado para validar a data de expiração da chave em tempo real comparando a propriedade `data_expiracao` contra a hora atual (`datetime.now()`), retornando `403 Forbidden` se expirada.
