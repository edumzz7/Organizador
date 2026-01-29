import sqlite3
import pandas as pd
from supabase import create_client, Client

# --- CONFIGURAÇÕES (PREENCHA AQUI) ---
SUPABASE_URL = "https://lwdorclkdagqvggvkldb.supabase.co"
SUPABASE_KEY = "sb_publishable_lJy8xsZAJfupTw4y88xQzg_DL0M6ILa"
# -------------------------------------

def migrar_dados():
    print("1. Conectando ao banco local (SQLite)...")
    try:
        # Conecta ao seu arquivo .db antigo
        conexao_sqlite = sqlite3.connect('projetos.db')
        
        # Lê todos os dados da tabela 'projetos'
        # Dica: O Pandas já lê tudo e organiza em colunas certinho
        df = pd.read_sql_query("SELECT * FROM projetos", conexao_sqlite)
        conexao_sqlite.close()
        print(f"   > Sucesso! {len(df)} projetos encontrados no arquivo local.")
    except Exception as e:
        print(f"   ❌ Erro ao ler SQLite: {e}")
        return

    print("\n2. Preparando dados para viagem...")
    # Converte os dados para o formato de lista de dicionários que o Supabase aceita
    # Exemplo: [{'id': '1', 'cliente_nome': 'Edu', ...}, {'id': '2', ...}]
    dados_para_enviar = df.to_dict(orient='records')

    print("\n3. Conectando ao Supabase...")
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        print("4. Enviando dados...")
        # Insere os dados na tabela 'projetos' do Supabase
        response = supabase.table('projetos').insert(dados_para_enviar).execute()
        
        print("\n✅ SUCESSO TOTAL! Os dados foram migrados.")
        print("   Agora atualize a página do seu site na Vercel e veja a mágica.")
        
    except Exception as e:
        print(f"\n❌ Erro ao enviar para o Supabase: {e}")
        print("   Dica: Verifique se a tabela 'projetos' já foi criada no Supabase e se está vazia.")

if __name__ == "__main__":
    migrar_dados()