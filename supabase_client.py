import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Carrega variáveis do .env (apenas local; no Vercel, as envs já existem)
load_dotenv()

def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        # Em ambiente local sem .env configurado ou erro de config
        print("Aviso: SUPABASE_URL ou SUPABASE_KEY não definidos.")
        return None

    return create_client(url, key)

# Instância global (pode ser importada diretamente)
supabase = get_supabase_client()
