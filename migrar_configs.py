import json
import os
from supabase import create_client, Client

# --- SUAS CHAVES (Copiadas do outro arquivo) ---
SUPABASE_URL = "https://lwdorclkdagqvggvkldb.supabase.co"
SUPABASE_KEY = "sb_publishable_lJy8xsZAJfupTw4y88xQzg_DL0M6ILa"
# -----------------------------------------------

CATEGORY_FILE = 'category_groups.json'
ANALYST_STATE_FILE = 'analyst_state.json'

def load_local_json(filepath):
    if not os.path.exists(filepath):
        print(f"Arquivo local não encontrado: {filepath}")
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def migrar_configs():
    print("--- Migrando Configurações para Supabase ---")
    
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        return

    # 1. Configuração de Categorias
    print(f"\nLendo {CATEGORY_FILE}...")
    cat_data = load_local_json(CATEGORY_FILE)
    if cat_data:
        print(f"Enviando dados para tabela 'config_categorias'...")
        try:
            supabase.table('config_categorias').upsert({
                "key": "main",
                "data": cat_data
            }).execute()
            print("✅ Categorias migradas com sucesso!")
        except Exception as e:
            print(f"❌ Erro ao enviar categorias: {e}")
    else:
        print("⚠️ Arquivo de categorias vazio ou não encontrado.")

    # 2. Estado dos Analistas
    print(f"\nLendo {ANALYST_STATE_FILE}...")
    analyst_data = load_local_json(ANALYST_STATE_FILE)
    if analyst_data:
        print(f"Enviando dados para tabela 'config_analistas'...")
        try:
            supabase.table('config_analistas').upsert({
                "key": "main",
                "data": analyst_data
            }).execute()
            print("✅ Estado de analistas migrado com sucesso!")
        except Exception as e:
            print(f"❌ Erro ao enviar analistas: {e}")
    else:
        print("⚠️ Arquivo de analistas vazio ou não encontrado.")

if __name__ == "__main__":
    migrar_configs()