from fastapi import FastAPI, HTTPException, Security, Depends, status, Header
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Dict, Optional
import requests
import urllib.parse
import os
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

app = FastAPI(
    title="Motor de Otimização de Rotas - Brasil (Homologação)",
    description="API integrada com OSRM Nacional e gerenciamento dinâmico de credenciais."
)

# 1. Classe de Gerenciamento de Chaves de API
class ApiKeyManager:
    def __init__(self):
        self._by_id: Dict[str, dict] = {}
        self._by_hash: Dict[str, dict] = {}
        self._inicializar_chave_mestre()

    def _inicializar_chave_mestre(self):
        # Hashing estático da string "sk_test_user1"
        master_key = "sk_test_user1"
        master_hash = hashlib.sha256(master_key.encode()).hexdigest()
        
        registro = {
            "id": "master_01",
            "name": "Chave de Testes",
            "active": True,
            "scopes": ["admin", "otimizar"],
            "expires_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used_at": None
        }
        
        self._by_id["master_01"] = registro
        self._by_hash[master_hash] = registro

    def create_key(self, name: str, scopes: List[str], expires_in_days: Optional[int] = None) -> tuple[dict, str]:
        plain_key = f"sk_live_{secrets.token_hex(32)}"
        key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
        
        key_id = str(uuid.uuid4())
        
        expires_at = None
        if expires_in_days is not None:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()
            
        registro = {
            "id": key_id,
            "name": name,
            "scopes": scopes,
            "active": True,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used_at": None
        }
        
        self._by_id[key_id] = registro
        self._by_hash[key_hash] = registro
        
        return registro, plain_key

    def update_key(self, key_id: str, name: Optional[str] = None, scopes: Optional[List[str]] = None, active: Optional[bool] = None) -> Optional[dict]:
        registro = self._by_id.get(key_id)
        if not registro:
            return None
            
        if name is not None:
            registro["name"] = name
        if scopes is not None:
            registro["scopes"] = scopes
        if active is not None:
            if key_id == "master_01" and active is False:
                raise ValueError("Não é permitido desativar a chave mestre de testes.")
            registro["active"] = active
            
        return registro

    def get_by_hash(self, key_hash: str) -> Optional[dict]:
        return self._by_hash.get(key_hash)

    def list_keys(self) -> List[dict]:
        return list(self._by_id.values())

# Instancia o gerenciador global
api_key_manager = ApiKeyManager()

# --- MODELOS PYDANTIC ---
class Localidade(BaseModel):
    nome: str
    lon: float
    lat: float

class RequisicaoRota(BaseModel):
    pontos: List[Localidade]

class CriarApiKey(BaseModel):
    name: str
    scopes: List[str] = ["otimizar"]
    expires_in_days: Optional[int] = None

class AtualizarApiKey(BaseModel):
    name: Optional[str] = None
    scopes: Optional[List[str]] = None
    active: Optional[bool] = None

class RespostaApiKey(BaseModel):
    id: str
    name: str
    scopes: List[str]
    active: bool
    expires_at: Optional[str] = None
    created_at: str
    last_used_at: Optional[str] = None

class RespostaCriacaoApiKey(RespostaApiKey):
    api_key: str

# --- DEPENDÊNCIAS DE AUTENTICAÇÃO E AUTORIZAÇÃO ---

# Esquema de segurança nativo para Bearer Token
security_admin = HTTPBearer(auto_error=False)

# Cabeçalho customizado para autenticação simples
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_admin_usuario(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_admin)):
    """
    Dependência nativa para validar o token de Administrador.
    O Swagger agora gerará o cadeado correto para esta rota.
    """
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de administrador inválido ou ausente"
        )
        
    token = credentials.credentials
    if not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de administrador não pode ser vazio"
        )
        
    return token

def get_usuario_autenticado(
    x_api_key: Optional[str] = Security(api_key_header),
    authorization: Optional[str] = Header(None)
):
    """
    Dependência de autenticação para as rotas logísticas da API.
    Aceita chaves de API tanto via header X-API-Key quanto via Authorization: Bearer <API_KEY>.
    """
    api_key = None
    if x_api_key:
        api_key = x_api_key
    elif authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
        else:
            api_key = authorization
            
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API inválida ou ausente"
        )
        
    # Calcule o hash SHA-256
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    # Busca a chave pelo hash
    registro = api_key_manager.get_by_hash(key_hash)
    if not registro:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API inválida ou ausente"
        )
        
    # Validações de status e expiração
    if not registro.get("active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API inativa"
        )
        
    expires_at_str = registro.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chave de API expirada"
            )

    # Validação estrita de escopo para otimização de rotas
    if "otimizar" not in registro.get("scopes", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta chave de API não possui permissão para otimizar rotas"
        )
            
    # Atualiza o timestamp de último uso direto no objeto em memória (com timezone)
    registro["last_used_at"] = datetime.now(timezone.utc).isoformat()
    return registro

# --- ENDPOINTS DE GERENCIAMENTO DE API KEYS ---

@app.post("/api-keys", response_model=RespostaCriacaoApiKey, status_code=status.HTTP_201_CREATED, tags=["Gerenciamento de API Keys"])
def criar_api_key(payload: CriarApiKey, admin_token: str = Depends(get_admin_usuario)):
    """
    Gera uma nova API key. Apenas chaves com permissão de administrador podem invocar este fluxo.
    Retorna a chave em texto puro uma única vez na resposta de criação.
    """
    registro, plain_key = api_key_manager.create_key(
        name=payload.name,
        scopes=payload.scopes,
        expires_in_days=payload.expires_in_days
    )
    return RespostaCriacaoApiKey(**registro, api_key=plain_key)

@app.get("/api-keys", response_model=List[RespostaApiKey], tags=["Gerenciamento de API Keys"])
def listar_api_keys(admin_token: str = Depends(get_admin_usuario)):
    """
    Lista os metadados de todas as API keys cadastradas no sistema.
    Por motivos de segurança, o segredo da chave e seu hash SHA-256 nunca são expostos.
    """
    keys = api_key_manager.list_keys()
    return [RespostaApiKey(**k) for k in keys]

@app.patch("/api-keys/{key_id}", response_model=RespostaApiKey, tags=["Gerenciamento de API Keys"])
def atualizar_api_key(key_id: str, payload: AtualizarApiKey, admin_token: str = Depends(get_admin_usuario)):
    """
    Realiza uma modificação parcial nas propriedades de uma chave de API identificada pelo ID.
    Trava de segurança impede a desativação da chave master de testes.
    """
    try:
        registro = api_key_manager.update_key(
            key_id=key_id,
            name=payload.name,
            scopes=payload.scopes,
            active=payload.active
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if not registro:
        raise HTTPException(status_code=404, detail="Chave de API não encontrada")
        
    return RespostaApiKey(**registro)

@app.delete("/api-keys/{key_id}", tags=["Gerenciamento de API Keys"])
def remover_api_key(key_id: str, admin_token: str = Depends(get_admin_usuario)):
    """
    Desativa permanentemente uma chave de API (Soft Delete) referenciada por seu ID.
    Bloqueia explicitamente a remoção da chave master de homologação ("master_01").
    """
    try:
        registro = api_key_manager.update_key(
            key_id=key_id,
            active=False
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if not registro:
        raise HTTPException(status_code=404, detail="Chave de API não encontrada")
        
    return {"status": "sucesso", "mensagem": f"Chave {key_id} desativada com sucesso (soft delete)."}



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