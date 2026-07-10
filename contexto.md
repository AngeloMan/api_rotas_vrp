📑 GUIA DE TRANSIÇÃO E CONTEXTO: MOTOR LOGÍSTICO BRASIL
Este documento consolida o estado atual do desenvolvimento de uma API de alto desempenho para otimização de frotas e roteamento comercial com cobertura de malha rodoviária nacional (Brasil).

1. Requisitos do Projeto & Escopo
Objetivo Principal: Criar um motor logístico local capaz de receber uma lista arbitrária de coordenadas geográficas (lat/lon), calcular a matriz de custo (tempo e distância) em milissegundos e determinar a sequência ótima de visitação (Problema do Caixeiro Viajante - TSP).

Escopo Geográfico: Cobertura completa do território nacional brasileiro utilizando dados do OpenStreetMap (OSM).

Desempenho: Resolução de malhas interestaduais e intermunicipais complexas em tempo real (< 1 segundo de processamento algorítmico).

Segurança: Camada de autenticação baseada em tokens dinâmicos gerenciados em memória com escopo de permissões, descrição e expiração temporal.

2. Decisões Técnicas e Arquitetura de Infraestrutura
O Stack Tecnológico
Back-End (FastAPI): Escolhido pela alta velocidade, tipagem estrita via Pydantic e geração nativa de documentação interativa Swagger.

Motor Alométrico (Google OR-Tools): Utilizado para resolver os problemas de restrição e otimização de rotas através do resolvedor de rotas nativo com a estratégia de busca inicial PATH_CHEAPEST_ARC.

Servidor de Roteamento (OSRM): Motor em C++ configurado com o algoritmo MLD (Multi-Level Dijkstra). Ele consome grafos binários pré-compilados de aproximadamente 12 GB gerados a partir do extrato do Brasil do Geofabrik.

Ajustes Críticos de Infraestrutura Efetuados
Correção de Versão (Erro de Fingerprint): O ambiente local foi travado rigidamente na tag estável ghcr.io/project-osrm/osrm-backend:v5.27.1. Versões mais recentes do contêiner (v26.7.2) quebravam ao tentar ler cabeçalhos binários estruturados gerados em compilações externas (como Google Colab).

Gerenciamento de Memória no WSL2 (Windows): O subsistema Linux por padrão limita o consumo de hardware a 50% da máquina hospedeira. Como o mapa do Brasil exige cerca de 12 GB estáticos na inicialização, foi necessário configurar globalmente os limites em %USERPROFILE%\.wslconfig:

Ini, TOML
[wsl2]
memory=14GB
swap=4GB
Isso solucionou o encerramento silencioso dos contêineres por falta de memória (Out of Memory).

3. Regras de Negócio e Limitações
Validação de Payload (Pydantic): Cada ponto de parada enviado deve, obrigatoriamente, conter uma string identificadora no campo nome, além de floats para lat (latitude) e lon (longitude).

Restrições de Provedores de Mapas (Links de Despacho):

Google Maps: Possui um teto rígido de 10 paradas (1 origem + 9 destinos) por link clássico. Payloads maiores resultam em exclusão automática de pontos finais (como Curitiba ou Guarapuava) no carregamento visual.

Apple Maps: Oferece suporte nativo para até 15 paradas via links universais de navegação.

Abordagem de Escala: Para frotas que visitem mais de 10 localidades, a interface do usuário final deve fracionar a rota consolidada em sub-rotas menores de ponto a ponto ("pernas de rota").

4. Estado Atual dos Artefatos de Código Fixos
O ambiente dockerizado está estável e o motor de rotas está acoplado ao FastAPI através das configurações abaixo.

📄 docker-compose.yml
YAML
version: '3.8'

services:
  # Motor de Mapas - Configurado para a malha do Brasil completo com a imagem compatível
  osrm:
    image: ghcr.io/project-osrm/osrm-backend:v5.27.1
    container_name: osrm_matriz
    ports:
      - "5000:5000"
    volumes:
      - ./osrm-local:/data
    command: osrm-routed --algorithm mld --max-table-size 10000 /data/brazil-latest.osrm
    shm_size: '2gb'
    restart: always

  # API FastAPI + OR-Tools para Homologação e Otimização
  api:
    build: .
    container_name: api_otimizacao
    ports:
      - "8000:8000"
    environment:
      - OSRM_URL=http://osrm:5000
    depends_on:
      - osrm
    restart: always
📄 app.py (Base Atual do Motor Logístico)
Python
from fastapi import FastAPI, HTTPException, Security, Depends, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import List, Dict
import requests
import urllib.parse
import os
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

app = FastAPI(
    title="Motor de Otimização de Rotas - Brasil (Homologação)",
    description="API integrada com OSRM Nacional e gerenciamento de credenciais."
)

# Base de chaves atual (Será expandida no próximo passo)
API_KEYS_DB: Dict[str, dict] = {
    "sk_test_user1": {"user_id": 1, "nome": "user1"},
    "sk_test_user2": {"user_id": 2, "nome": "user2"}
}

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_usuario_autenticado(api_key: str = Security(api_key_header)):
    if not api_key or api_key not in API_KEYS_DB:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Chave de API inválida ou ausente"
        )
    return API_KEYS_DB[api_key]

class Localidade(BaseModel):
    nome: str
    lon: float
    lat: float

class RequisicaoRota(BaseModel):
    pontos: List[Localidade]

# --- MOTOR DE ROTAS ---
def otimizar_osrm_ortools(cidades: List[dict], usuario: dict):
    coords_str = ";".join([f"{c['lon']},{c['lat']}" for c in cidades])
    osrm_base = os.getenv("OSRM_URL", "http://localhost:5000")
    osrm_url = f"{osrm_base}/table/v1/driving/{coords_str}?annotations=duration,distance"
    
    try:
        response = requests.get(osrm_url, timeout=30)
        osrm_response = response.json()
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao conectar ao servidor OSRM.")

    if osrm_response.get("code") != "Ok":
        raise HTTPException(status_code=400, detail="OSRM não conseguiu processar as coordenadas continentais.")

    time_matrix = [[int(round(time)) for time in row] for row in osrm_response['durations']]
    manager = pywrapcp.RoutingIndexManager(len(time_matrix), 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        return time_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        raise HTTPException(status_code=422, detail="Não foi possível encontrar uma rota válida.")

    index = routing.Start(0)
    ordered_cidades = []
    route_time = 0
    
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        ordered_cidades.append(cidades[node])
        previous_index = index
        index = solution.Value(routing.NextVar(index))
        route_time += routing.GetArcCostForVehicle(previous_index, index, 0)
    
    node = manager.IndexToNode(index)
    ordered_cidades.append(cidades[node])

    route_distance = 0
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        next_index = solution.Value(routing.NextVar(index))
        next_node = manager.IndexToNode(next_index)
        route_distance += osrm_response['distances'][node][next_node]
        index = next_index

    # Links de Despacho GPS
    origin_lat, origin_lon = ordered_cidades[0]['lat'], ordered_cidades[0]['lon']
    dest_lat, dest_lon = ordered_cidades[-1]['lat'], ordered_cidades[-1]['lon']
    waypoints_str = "|".join([f"{c['lat']},{c['lon']}" for c in ordered_cidades[1:-1]])
    
    query_params = {
        "api": "1",
        "origin": f"{origin_lat},{origin_lon}",
        "destination": f"{dest_lat},{dest_lon}",
        "waypoints": waypoints_str
    }
    link_gmaps = f"https://www.google.com/maps/dir/?{urllib.parse.urlencode(query_params)}"

    apple_base = "https://maps.apple.com/directions?"
    apple_source = f"source={origin_lat},{origin_lon}"
    apple_dest = f"destination={dest_lat},{dest_lon}"
    apple_waypoints = "".join([f"&waypoint={c['lat']},{c['lon']}" for c in ordered_cidades[1:-1]])
    link_apple = f"{apple_base}{apple_source}&{apple_dest}{apple_waypoints}&mode=driving"

    return {
        "status": "sucesso",
        "usuario_autenticado": usuario,
        "tempo_total_minutos": round(route_time / 60, 2),
        "distancia_total_km": round(route_distance / 1000, 2),
        "ordem_entrega": [
            {"name": c['nome'], "lon": c['lon'], "lat": c['lat']} for c in ordered_cidades
        ],
        "links_navegacao": {
            "google_maps": link_gmaps,
            "apple_maps": link_apple
        }
    }

@app.post("/otimizar-rota", tags=["Motor Logístico"])
def otimizar_rota(payload: RequisicaoRota, usuario: dict = Depends(get_usuario_autenticado)):
    cidades_dict = [{"nome": c.nome, "lon": c.lon, "lat": c.lat} for c in payload.pontos]
    if len(cidades_dict) < 2:
        raise HTTPException(status_code=400, detail="Envie pelo menos 2 localidades.")
    return otimizar_osrm_ortools(cidades_dict, usuario)
6. Próximo Passo: Especificação da Nova Camada de Credenciais
O próximo objetivo de desenvolvimento é remover os endpoints rudimentares antigos (/admin/chaves) e substituí-los por um ecossistema RESTful profissional sob o path /api-keys.

Nova Estrutura do Dicionário (API_KEYS_DB)
Para suportar as novas regras, a base em memória passará a conter objetos ricos:

Python
API_KEYS_DB: Dict[str, dict] = {
    "sk_test_user1": {
        "id": "key_master_01",
        "user_id": 1,
        "nome": "user1",
        "descricao": "Chave Mestre de Desenvolvimento",
        "permissoes": ["admin", "otimizar"],
        "data_expiracao": None,  # None = Vitalícia
        "criado_em": "2026-07-10T11:41:00"
    }
}
Contrato dos Novos Endpoints Solicitados
POST /api-keys ➔ Cria uma nova chave

Deve aceitar user_id, nome, descricao, permissoes e expira_em_dias (inteiro opcional para calcular o datetime de expiração futuro).

Deve gerar uma string criptográfica aleatória segura (Ex: prefixada com sk_live_... usando secrets.token_hex(16)).

Proteção: Apenas chaves que contenham a permissão "admin" podem invocar esta rota.

GET /api-keys ➔ Lista as chaves existentes

Retorna os metadados de todas as chaves ativas na base de dados.

Segurança: Por boas práticas de segurança, o token secreto (sk_live_...) nunca deve ser exibido na listagem, retorne apenas o id, nome, descricao, permissoes e datas.

DELETE /api-keys/{id} ➔ Revoga uma chave

Remove permanentemente o token da memória referenciando-o pelo seu id (e nunca passando a string secreta na URL).

Trava de Segurança: Bloquear explicitamente a remoção da chave master de homologação (sk_test_user1) para evitar o travamento do ambiente.

PATCH /api-keys/{id} ➔ Altera permissões, descrição ou data de expiração

Permite modificações parciais (Update Parcial) dos campos associados ao ID fornecido.

Refatoração do Injetor de Dependência (get_usuario_autenticado):

O validador do header HTTP deve ser atualizado para ler o novo dicionário estruturado e lançar um erro 403 Forbidden caso a propriedade data_expiracao da chave correspondente seja menor do que o timestamp do momento atual (datetime.now()).