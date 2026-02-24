import json
import uuid
from datetime import datetime
import os
from supabase_client import supabase

# Não usamos mais DB_PATH local com Supabase
# DB_PATH = 'projetos.db'

# Funções de DB connection removidas em favor do objeto 'supabase' importado

# init_db não é mais necessário da mesma forma, pois a tabela deve ser criada no Supabase
# Mas podemos manter um placeholder se necessário, ou remover.
def init_db():
    pass

def create_project(cliente_nome, status="Ativo"):
    if not supabase:
        print("Erro: Cliente Supabase não inicializado.")
        return None

    project_id = str(uuid.uuid4())
    data_criacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Estrutura inicial do JSON
    dados_json = {
        "tipo": "entrega única",
        "etapas": [
            {"nome": "Etapa 1", "estudo": False, "desenv": False, "matchs": False, "revisao": False}
        ],
        "data_finalizacao": None,
        "escopo": {
            "lojas": [],
            "marcas": [],
            "categorias": []
        },
        "recursos": {
            "tickets": [],
            "planilhas": [],
            "pastas": [] 
        },
        "notas_adesivas": ""
    }
    
    try:
        response = supabase.table('projetos').insert({
            "id": project_id,
            "cliente_nome": cliente_nome,
            "status": status,
            "data_criacao": data_criacao,
            "dados_json": json.dumps(dados_json)
        }).execute()
        return project_id
    except Exception as e:
        print(f"Erro ao criar projeto no Supabase: {e}")
        return None

def list_projects():
    if not supabase:
        return []

    try:
        response = supabase.table('projetos').select("*").order('data_criacao', desc=True).execute()
        rows = response.data
        
        projects = []
        for row in rows:
            p = dict(row)
            # Supabase pode retornar o JSON já parseado se a coluna for JSONB,
            # mas se for TEXT, precisamos fazer o load. 
            # Assumindo TEXT para compatibilidade com a migração simples.
            if isinstance(p['dados_json'], str):
                p['dados'] = json.loads(p['dados_json'])
            else:
                p['dados'] = p['dados_json']

            # Contagem rápida para o resumo
            recursos = p['dados'].get('recursos', {})
            tickets = 0
            planilhas = 0
            links = 0
            
            if isinstance(recursos.get('tickets'), list): # Formato antigo
                tickets = len(recursos.get('tickets', []))
                planilhas = len(recursos.get('planilhas', []))
            else: # Formato novo (Pastas)
                for pasta in recursos.get('pastas', []):
                    for item in pasta.get('items', []):
                        if item.get('type') == 'ticket': tickets += 1
                        elif item.get('type') == 'planilha': planilhas += 1
                        elif item.get('type') == 'link': links += 1
            
            p['stats'] = {
                'tickets': tickets,
                'planilhas': planilhas,
                'links': links
            }
            projects.append(p)
        return projects
    except Exception as e:
        print(f"Erro ao listar projetos do Supabase: {e}")
        return []

def get_project(project_id):
    if not supabase:
        return None

    try:
        response = supabase.table('projetos').select("*").eq('id', project_id).execute()
        if response.data:
            row = response.data[0]
            p = dict(row)
            if isinstance(p['dados_json'], str):
                p['dados'] = json.loads(p['dados_json'])
            else:
                p['dados'] = p['dados_json']
            return p
        return None
    except Exception as e:
        print(f"Erro ao buscar projeto {project_id}: {e}")
        return None

def update_project(project_id, cliente_nome, status, dados_dict):
    if not supabase:
        return

    try:
        supabase.table('projetos').update({
            "cliente_nome": cliente_nome,
            "status": status,
            "dados_json": json.dumps(dados_dict)
        }).eq('id', project_id).execute()
    except Exception as e:
        print(f"Erro ao atualizar projeto {project_id}: {e}")

def delete_project(project_id):
    if not supabase:
        return

    try:
        supabase.table('projetos').delete().eq('id', project_id).execute()
    except Exception as e:
        print(f"Erro ao deletar projeto {project_id}: {e}")

def import_project(json_data):
    if not supabase:
        return False

    try:
        data = json.loads(json_data)
        # Se não tiver ID ou data, gera novos
        p_id = data.get('id', str(uuid.uuid4()))
        cliente = data.get('cliente_nome', 'Importado')
        status = data.get('status', 'Ativo')
        criacao = data.get('data_criacao', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Garante que os dados do escopo/recursos estejam lá
        dados = data.get('dados', data.get('dados_json'))
        if isinstance(dados, str):
            dados = json.loads(dados)
            
        # Upsert
        supabase.table('projetos').upsert({
            "id": p_id,
            "cliente_nome": cliente,
            "status": status,
            "data_criacao": criacao,
            "dados_json": json.dumps(dados)
        }).execute()
        return True
    except Exception as e:
        print(f"Erro ao importar para Supabase: {e}")
        return False
