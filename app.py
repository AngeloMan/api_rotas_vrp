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
    description="API integrada com OSRM Nacional e gerenciamento dinâmico de credenciais."
)

# 1. Banco de Dados em Memória (Dinâmico para homologação)
# Começa com os usuários padrão do README
API_KEYS_DB: Dict[str, dict] = {
    "sk_test_user1": {"user_id": 1, "nome": "user1"},
    "sk_test_user2": {"user_id": 2, "nome": "user2"}
}

# Configurar o cabeçalho X-API-Key
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Dependência de Validação de API Key
def get_usuario_autenticado(api_key: str = Security(api_key_header)):
    if not api_key or api_key not in API_KEYS_DB:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Chave de API inválida ou ausente"
        )
    return API_KEYS_DB[api_key]


# --- MODELOS DE ENTRADA ---
class Localidade(BaseModel):
    nome: str
    lon: float
    lat: float

class RequisicaoRota(BaseModel):
    pontos: List[Localidade]

class NovaChave(BaseModel):
    chave: str
    user_id: int
    nome: str


# --- ENDPOINTS DE GERENCIAMENTO DE CHAVES (PEDIDO 2) ---

@app.post("/admin/chaves", status_code=status.HTTP_201_CREATED, tags=["Admin - Gerenciamento de Chaves"])
def adicionar_chave(payload: NovaChave, usuario_adm: dict = Depends(get_usuario_autenticado)):
    """
    Adiciona uma nova chave autorizada no sistema em tempo de execução.
    Protegido pela própria API Key por segurança nesta fase.
    """
    if payload.chave in API_KEYS_DB:
        raise HTTPException(status_code=400, detail="Esta chave já está cadastrada.")
    
    API_KEYS_DB[payload.chave] = {"user_id": payload.user_id, "nome": payload.nome}
    return {"status": "sucesso", "mensagem": f"Chave para o usuário {payload.nome} ativada."}

@app.delete("/admin/chaves/{chave_para_remover}", tags=["Admin - Gerenciamento de Chaves"])
def remover_chave(chave_para_remover: str, usuario_adm: dict = Depends(get_usuario_autenticado)):
    """
    Revoga uma chave de API imediatamente, impedindo novos cálculos de rota por ela.
    """
    if chave_para_remover == "sk_test_user1":
        raise HTTPException(status_code=400, detail="Não é permitido remover a chave mestre de testes.")
        
    if chave_para_remover not in API_KEYS_DB:
        raise HTTPException(status_code=404, detail="Chave não encontrada ou já revogada.")
        
    del API_KEYS_DB[chave_para_remover]
    return {"status": "sucesso", "mensagem": "Chave revogada com sucesso."}


# --- MOTOR DE ROTAS ---

def otimizar_osrm_ortools(cidades: List[dict], usuario: dict):
    coords_str = ";".join([f"{c['lon']},{c['lat']}" for c in cidades])
    
    # OSR_URL agora pode apontar para o container local ou um OSRM Brasil na nuvem
    osrm_base = os.getenv("OSRM_URL", "http://localhost:5000")
    osrm_url = f"{osrm_base}/table/v1/driving/{coords_str}?annotations=duration,distance"
    
    try:
        response = requests.get(osrm_url, timeout=30) # Timeout estendido para o Brasil
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

    # Geração de Links de Despacho GPS
    origin_lat, origin_lon = ordered_cidades[0]['lat'], ordered_cidades[0]['lon']
    dest_lat, dest_lon = ordered_cidades[-1]['lat'], ordered_cidades[-1]['lon']
    waypoints_list = [f"{c['lat']},{c['lon']}" for c in ordered_cidades[1:-1]]
    waypoints_str = "|".join(waypoints_list)
    
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
            {"nome": c['nome'], "lon": c['lon'], "lat": c['lat']} for c in ordered_cidades
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