from flask import Flask, request, redirect, url_for, session, flash, render_template, jsonify, send_file
from bs4 import BeautifulSoup
import pandas as pd
import os
from werkzeug.utils import secure_filename
import math
import json
from collections import OrderedDict
from datetime import datetime
import numpy as np
import unicodedata

from urllib.parse import unquote

def _norm_key(text) -> str:
    if text is None:
        return ""
    s = str(text).strip().lower()
    s = unicodedata.normalize('NFD', s)  # separa acentos
    return ''.join(ch for ch in s if not unicodedata.combining(ch))  # remove acentos

def _norm_code(value) -> str:
    """
    Normaliza c��digos de categoria para uso como chave interna (min��sculo/strip).
    Mantemos o c��digo original no payload salvo para exibi����o.
    """
    if value is None:
        return ""
    return str(value).strip().lower()

# --- Código Python da Aplicação ---

app = Flask(__name__)
app.secret_key = "uma_chave_secreta_muito_boa_agora_com_mais_seguranca"
UPLOAD_FOLDER = 'uploads_single_file'
ALLOWED_EXTENSIONS = {'html'}
CATEGORY_FILE = 'category_groups.json'
ANALYST_STATE_FILE = 'analyst_state.json'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Register Blueprints
from modules.revisao_logs.routes import revisao_logs_bp
from modules.gestao_projetos.routes import gestao_projetos_bp

app.register_blueprint(revisao_logs_bp, url_for_label='logs', url_prefix='/logs')
app.register_blueprint(gestao_projetos_bp, url_for_label='projetos', url_prefix='/projetos')

# --- Inicialização Supabase (via import) ---
from supabase_client import supabase
if not supabase:
    print("Aviso: Cliente Supabase não pôde ser inicializado (verifique variáveis de ambiente).")
else:
    print("Sucesso: Cliente Supabase inicializado.")



def an_is_nan(value):
    return isinstance(value, float) and math.isnan(value)

app.jinja_env.globals.update(an_is_nan=an_is_nan)

# --- Utilidades ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Funções de Carga/Salva Configuração (Supabase) ---

def load_config_from_supabase(table_name, key="main", default_value=None):
    if default_value is None: default_value = {}
    if not supabase: return default_value
    try:
        response = supabase.table(table_name).select('data').eq('key', key).execute()
        if response.data:
            return response.data[0]['data']
        return default_value
    except Exception as e:
        print(f"Erro ao carregar {table_name}: {e}")
        return default_value

def save_config_to_supabase(table_name, data, key="main"):
    if not supabase: return
    try:
        # Garante que as chaves sejam strings minúsculas (compatibilidade)
        processed_data = {str(k).lower().strip(): v for k, v in data.items()}
        # Ordenamos apenas para consistência, embora JSONB não garanta ordem
        sorted_data = OrderedDict(sorted(processed_data.items(), key=lambda x: x[0].lower()))
        
        supabase.table(table_name).upsert({
            "key": key,
            "data": sorted_data
        }).execute()
    except Exception as e:
        print(f"Erro ao salvar {table_name}: {e}")

def load_category_map():
    raw_map = load_config_from_supabase('config_categorias', default_value={})
    normalized = {}
    for key, value in raw_map.items():
        if isinstance(value, dict):
            code = value.get('code', key)
            name = value.get('name', value.get('Nome', code))
            group = value.get('group', value.get('Grupo', "Grupo Desconhecido"))
            placeholder = value.get('placeholder', False) or ('placeholder' in str(code))
        else:
            code = key
            name = key
            group = value
            placeholder = 'placeholder' in str(code)

        norm_key = _norm_code(code)
        normalized[norm_key] = {
            "code": str(code).strip(),
            "name": str(name).strip() if name else str(code).strip(),
            "group": group if group else "Grupo Desconhecido"
        }
        if placeholder:
            normalized[norm_key]["placeholder"] = True
    return normalized

def save_category_map(data):
    payload = {}
    for key, value in data.items():
        code = value.get('code', key)
        name = value.get('name', value.get('Nome', code))
        group = value.get('group', value.get('Grupo', "Grupo Desconhecido"))
        placeholder = value.get('placeholder', False) or ('placeholder' in str(code))

        norm_key = _norm_code(code)
        payload[norm_key] = {
            "code": str(code).strip(),
            "name": str(name).strip() if name else str(code).strip(),
            "group": group if group else "Grupo Desconhecido"
        }
        if placeholder:
            payload[norm_key]["placeholder"] = True

    save_config_to_supabase('config_categorias', payload)

def load_analyst_state():
    return load_config_from_supabase('config_analistas', default_value={})

def save_analyst_state(data):
    save_config_to_supabase('config_analistas', data)

# --- Parsing do HTML para DataFrame ---

def parse_html_to_df(html_content, category_map):
    normalized_category_map = {}
    for k, v in category_map.items():
        if isinstance(v, dict):
            entry = {
                "code": v.get('code', k),
                "name": v.get('name', v.get('Nome', v.get('code', k))),
                "group": v.get('group', v.get('Grupo', "Grupo Desconhecido")),
                "placeholder": v.get('placeholder', False)
            }
        else:
            entry = {"code": k, "name": k, "group": v}
        if 'placeholder' in str(entry.get('code')):
            entry['placeholder'] = True
        normalized_category_map[_norm_code(entry['code'])] = entry

    map_changed = False

    def resolve_group(row):
        nonlocal map_changed
        code = str(row.get('Categorias', '') or '').strip()
        name = str(row.get('Nome', '') or '').strip()
        code_key = _norm_code(code)
        
        # 1. Tenta encontrar pelo CÓDIGO (Prioridade Absoluta)
        if code_key:
            entry = normalized_category_map.get(code_key)
            if entry:
                # Encontrou pelo código! Verifica se o nome mudou.
                current_name = entry.get('name')
                if name and current_name != name:
                    entry['name'] = name
                    normalized_category_map[code_key] = entry
                    map_changed = True
                return entry.get('group', "Grupo Desconhecido")

        # 2. Tenta encontrar pelo NOME (Fallback / Migração)
        name_key = _norm_key(name)
        if name_key:
            matched_key, matched_entry = None, None
            for ck, data in normalized_category_map.items():
                stored_name = _norm_key(data.get('name', data.get('code', '')))
                # Verifica também se a chave em si é o nome (legado)
                stored_key_as_name = _norm_key(ck)
                
                if (stored_name == name_key or stored_key_as_name == name_key) and not data.get('placeholder'):
                    matched_key, matched_entry = ck, data
                    break

            if matched_entry is not None:
                # Encontrou pelo nome!
                # Se temos um código novo, MIGRAMOS a chave para o código.
                if code_key and code_key != matched_key:
                    normalized_category_map.pop(matched_key, None)
                    new_entry = {
                        **matched_entry,
                        "code": code,
                        "name": name or matched_entry.get('name', name)
                    }
                    normalized_category_map[code_key] = new_entry
                    map_changed = True
                    return new_entry.get('group', "Grupo Desconhecido")
                
                # Se não tem código ou já é a mesma chave (mas sem 'Categorias' no CSV?), retorna o grupo
                return matched_entry.get('group', "Grupo Desconhecido")

        return "Grupo Desconhecido"

    soup = BeautifulSoup(html_content, 'html.parser')
    table = soup.find('table')
    if not table:
        return None, []
    header_row = table.find('tr')
    if not header_row:
        return None, []
    headers = [th.text.strip() for th in header_row.find_all(['th', 'td'])]
    if not headers or len(headers) < 5:
        headers = ["Categorias", "Loja", "Marca", "Proc", "Relv.", "Nome", "AutoMatch C.", "Tokens C.", "PI", "P2C Agrup.", "Disponíveis", "Total P.Site", "%", "Responsável"]

    rows_data = []
    data_rows = table.find_all('tr')[1:]
    for row_html in data_rows:
        cells = row_html.find_all('td')
        if len(cells) > 0 and "Total" in cells[0].text and len(cells) < len(headers) - 2:
            continue
        cell_texts = [cell.text.strip() for cell in cells]
        row_dict = dict(zip(headers, cell_texts))
        if row_dict:
            rows_data.append(row_dict)

    if not rows_data:
        return pd.DataFrame(), []

    df = pd.DataFrame(rows_data)
    if 'Responsável' not in df.columns:
        return pd.DataFrame(), []

    df.dropna(subset=['Responsável'], inplace=True)
    df = df[df['Responsável'].astype(str).str.strip() != '']
    df['Responsável'] = df['Responsável'].astype(str).str.strip()
    if df.empty:
        return pd.DataFrame(), []

    cols_to_convert = ["AutoMatch C.", "Tokens C.", "PI", "P2C Agrup.", "Disponíveis", "Total P.Site"]
    for col in cols_to_convert:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce')

    unmapped_category_names = []
    if 'Nome' in df.columns or 'Categorias' in df.columns:
        df['Grupo'] = df.apply(resolve_group, axis=1)
        unmapped_df = df[df['Grupo'] == 'Grupo Desconhecido']
        if not unmapped_df.empty:
            seen_codes = set()
            for _, row in unmapped_df.iterrows():
                code = str(row.get('Categorias', '') or '').strip()
                name = str(row.get('Nome', '') or '').strip()
                code_key = _norm_code(code)
                if code_key and code_key not in normalized_category_map and code_key not in seen_codes:
                    unmapped_category_names.append({"code": code, "name": name or code})
                    seen_codes.add(code_key)
    else:
        df['Grupo'] = "Grupo Desconhecido"

    if 'PI' in df.columns:
        df['PI'] = df['PI'].fillna(0)
    else:
        df['PI'] = 0

    if map_changed:
        save_category_map(normalized_category_map)

    df.reset_index(drop=True, inplace=True)
    df['id'] = df.index
    return df, unmapped_category_names

# --- Resumos por analista, carga, disponibilidade ---

def get_analyst_data(df, analyst_state):
    if df is None or df.empty or 'Responsável' not in df.columns:
        return [], pd.DataFrame(), []
    all_analyst_names_from_df = [name.lower().strip() for name in df['Responsável'].unique()]
    new_analysts_to_add = {}
    registered_analysts = list(analyst_state.keys())
    for name in all_analyst_names_from_df:
        if name not in registered_analysts:
            new_analysts_to_add[name] = {
                "display": df[df['Responsável'].str.lower().str.strip() == name]['Responsável'].iloc[0],
                "indisponivel": False,
                "updated_at": datetime.utcnow().isoformat() + 'Z'
            }
    if new_analysts_to_add:
        flash(f"{len(new_analysts_to_add)} novo(s) analista(s) detectado(s) e adicionado(s) ao registro: {', '.join(v['display'] for v in new_analysts_to_add.values())}", "info")
        analyst_state.update(new_analysts_to_add)
        save_analyst_state(analyst_state)

    pi_col = 'PI' if 'PI' in df.columns else None
    name_col = 'Nome' if 'Nome' in df.columns else 'Categorias'
    agg_dict = {'num_categories': (name_col, 'count')}
    if pi_col:
        agg_dict['total_pi'] = (pi_col, 'sum')
    analyst_summary = df.groupby('Responsável').agg(**agg_dict).reset_index()
    for col in ['total_pi', 'num_categories']:
        if col not in analyst_summary.columns:
            analyst_summary[col] = 0
    summary_list = analyst_summary.to_dict(orient='records')

    for analyst in summary_list:
        analyst_key = analyst['Responsável'].lower().strip()
        state_info = analyst_state.get(analyst_key, {"indisponivel": False})
        analyst['indisponivel'] = state_info.get('indisponivel', False)

        analyst_cats_df = df[df['Responsável'] == analyst['Responsável']]
        if not analyst_cats_df.empty and 'Grupo' in analyst_cats_df.columns:
            group_counts = analyst_cats_df['Grupo'].value_counts()
            group_counts = group_counts[group_counts >= 3]
            if not group_counts.empty:
                max_count = group_counts.max()
                dominant_groups = group_counts[group_counts == max_count].index.tolist()
                analyst['predominant_group'] = ", ".join(dominant_groups)
            else:
                analyst['predominant_group'] = "Sem grupo principal"
        else:
            analyst['predominant_group'] = "Sem grupo principal"

    return summary_list, df

def calculate_pi_distribution(df):
    if df is None or df.empty or 'Responsável' not in df.columns or 'PI' not in df.columns:
        return {}
    return df.groupby('Responsável')['PI'].sum().fillna(0).to_dict()

def get_available_recipients(df_full, source_analyst_name=None):
    analyst_state = load_analyst_state()
    all_recipients = df_full['Responsável'].unique()
    available = []
    for name in all_recipients:
        if name == source_analyst_name or pd.isna(name) or str(name).strip() == "":
            continue
        analyst_key = str(name).lower().strip()
        if not analyst_state.get(analyst_key, {}).get('indisponivel', False):
            available.append(name)
    return available

# --- Métrica: Gini ---

def gini(values):
    xs = [float(v) for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return 0.0
    xs.sort()
    s = sum(xs)
    if s == 0:
        return 0.0
    weighted = sum((i + 1) * x for i, x in enumerate(xs))
    return 1 + 1 / n - 2 * weighted / (n * s)

# --- Tela de Detalhes: histórico e ordenação sem acentos ---

def build_redistribution_details(df, results):
    # Histórico ordenado alfabeticamente sem acento
    cargas_atual = calculate_pi_distribution(df)
    cargas_sugerida = results.get('carga_final_por_analista', {}) or {}
    todos = sorted(set(list(cargas_atual.keys()) + list(cargas_sugerida.keys())), key=_norm_key)
    historico = []
    for nome in todos:
        historico.append({
            'analista': nome,
            'pi_atual': int(cargas_atual.get(nome, 0)),
            'pi_sugerido': int(cargas_sugerida.get(nome, 0)),
        })
    max_total = max(([h['pi_atual'] for h in historico] + [h['pi_sugerido'] for h in historico]) or [1])
    for h in historico:
        h['pct_atual'] = round((h['pi_atual'] / max_total * 100) if max_total else 0.0, 1)
        h['pct_sugerido'] = round((h['pi_sugerido'] / max_total * 100) if max_total else 0.0, 1)

    # Top 5 especialidade
    analyst_state = load_analyst_state()
    analyst_summary, _ = get_analyst_data(df.copy(), analyst_state)
    dominantes = {}
    for a in analyst_summary:
        pg = a.get('predominant_group')
        if pg and pg != "Sem grupo principal":
            dominantes[a['Responsável']] = [g.strip() for g in str(pg).split(',')]

    contagem = {}
    for r in results.get('sugestoes', []):
        an = r['Responsável_Sugerido']
        g = r.get('Grupo')
        contagem.setdefault(an, {'match': 0, 'total': 0})
        contagem[an]['total'] += 1
        if an in dominantes and g in dominantes[an]:
            contagem[an]['match'] += 1

    ranking = []
    for an, v in contagem.items():
        pct = (v['match'] / v['total']) if v['total'] else 0.0
        ranking.append({
            'analista': an,
            'match_pct': round(pct * 100, 1),
            'match': v['match'],
            'total': v['total']
        })
    ranking.sort(key=lambda x: (-x['match_pct'], -x['match'], _norm_key(x['analista'])))
    top5 = ranking[:5]

    # Saúde por grupo
    from collections import defaultdict
    por_grupo = defaultdict(lambda: defaultdict(float))
    for r in results.get('sugestoes', []):
        por_grupo[r['Grupo']][r['Responsável_Sugerido']] += float(r['PI'])
    saude = []
    for g, loads in por_grupo.items():
        total = sum(loads.values())
        top_analista = max(loads.items(), key=lambda kv: kv[1])[0] if loads else None
        saude.append({
            'grupo': g,
            'total_pi': int(total),
            'num_analistas': len(loads),
            'top_analista': top_analista
        })
    saude.sort(key=lambda x: (-x['total_pi'], x['grupo']))

    return {'historico': historico, 'max_total': int(max_total), 'top_especialidade': top5, 'saude_grupos': saude}

# ---------- COMPARAÇÃO SIMPLES (2–3 snapshots) ----------

def _dominant_group_for(adf):
    if adf.empty or 'Grupo' not in adf.columns:
        return "Sem grupo principal"
    counts = adf['Grupo'].value_counts()
    if counts.empty or counts.iloc[0] < 3:
        return "Sem grupo principal"
    top_count = counts.iloc[0]
    tops = counts[counts == top_count].index.tolist()
    if len(tops) == 1:
        return tops[0]
    group_pi = {g: adf[adf['Grupo'] == g]['PI'].sum() for g in tops}
    return max(group_pi, key=group_pi.get) if group_pi else "Sem grupo principal"

def _snapshot_stats(df):
    out = {}
    if df is None or df.empty:
        return out
    for analyst, adf in df.groupby('Responsável'):
        k = _norm_key(analyst)
        out[k] = {
            "display": analyst,
            "pi": float(adf['PI'].sum()),
            "cnt": int(adf['Nome'].count()) if 'Nome' in adf.columns else int(len(adf)),
            "group": _dominant_group_for(adf)
        }
    return out

def build_simple_compare(label_df_pairs):
    stats_list = []
    labels = []
    all_keys = set()
    for label, df in label_df_pairs:
        labels.append(label)
        stats = _snapshot_stats(df)
        stats_list.append(stats)
        all_keys.update(stats.keys())

    # ordenar por nome (sem acento)
    def display_for_key(k):
        for stats in reversed(stats_list):
            if k in stats:
                return stats[k]['display']
        return k

    rows = []
    for key in sorted(all_keys, key=lambda k: _norm_key(display_for_key(k))):
        display = display_for_key(key)
        pi_list, cnt_list, grp_list = [], [], []
        for stats in stats_list:
            if key in stats:
                pi_list.append(int(stats[key]['pi']))
                cnt_list.append(int(stats[key]['cnt']))
                grp_list.append(stats[key]['group'])
            else:
                pi_list.append(0); cnt_list.append(0); grp_list.append('—')

        rows.append({"analista": display, "pi": pi_list, "cnt": cnt_list, "grp": grp_list})

    return {"labels": labels, "rows": rows}

# --- Sugestões e redistribuições (mantido) ---

def suggest_recipients_for_category(category_id, source_analyst_name, df_full):
    if df_full is None or df_full.empty:
        return []
    try:
        category_to_move = df_full[df_full['id'] == category_id].iloc[0]
    except IndexError:
        return []
    category_group = category_to_move.get('Grupo', 'Grupo Desconhecido')
    potential_recipients = get_available_recipients(df_full, source_analyst_name)
    if not potential_recipients:
        return []
    current_pi_loads, suggestions = calculate_pi_distribution(df_full), []
    for analyst_name in potential_recipients:
        analyst_cats = df_full[df_full['Responsável'] == analyst_name]
        similar_cats_df = analyst_cats[analyst_cats['Grupo'] == category_group]
        suggestions.append({
            'name': analyst_name,
            'similarity_count': len(similar_cats_df),
            'current_pi': current_pi_loads.get(analyst_name, 0),
            'similar_categories': similar_cats_df['Nome'].tolist()
        })
    return suggestions

def suggest_distribution_for_leaving_analyst(leaving_analyst_name, df_full):
    if df_full is None or df_full.empty or 'Responsável' not in df_full.columns:
        return {"error": "Dados incompletos para processar."}
    categories_to_move = df_full[df_full['Responsável'] == leaving_analyst_name]
    if categories_to_move.empty:
        return {"info": "Analista não possui categorias para redistribuir."}
    potential_recipients = get_available_recipients(df_full, leaving_analyst_name)
    if not potential_recipients:
        return {"error": "Nenhum analista DISPONÍVEL para receber as categorias. Verifique as marcações de indisponibilidade."}
    analyst_cat_cache = {name: df_full[df_full['Responsável'] == name] for name in potential_recipients}
    current_pi_loads = calculate_pi_distribution(df_full)
    assignments = {}
    categories_to_move = categories_to_move.sort_values(by=['PI'], ascending=False)
    for _, cat_row in categories_to_move.iterrows():
        cat_id = cat_row['id']
        cat_group = cat_row.get('Grupo', 'Grupo Desconhecido')
        cat_pi = cat_row.get('PI', 0)
        if math.isnan(cat_pi):
            cat_pi = 0
        recipient_options = []
        for r_name in potential_recipients:
            similarity_count = len(analyst_cat_cache[r_name][analyst_cat_cache[r_name]['Grupo'] == cat_group])
            recipient_options.append({
                'name': r_name,
                'similarity_count': similarity_count,
                'current_pi': current_pi_loads.get(r_name, 0)
            })
        recipient_options.sort(key=lambda x: (-x['similarity_count'], x['current_pi']))
        top_suggestions = recipient_options[:4]
        assignments[cat_id] = {
            'category_name': cat_row.get('Nome', 'N/A'),
            'category_pi': cat_pi,
            'suggested_analysts': top_suggestions
        }
    return assignments

def suggest_recipients_for_new_category(category_group, df_full):
    if df_full is None or df_full.empty:
        return {"error": "Dados não disponíveis para simulação."}
    potential_recipients = get_available_recipients(df_full)
    if not potential_recipients:
        return {"error": "Nenhum analista DISPONÍvel para receber a categoria."}
    current_pi_loads, suggestions = calculate_pi_distribution(df_full), []
    for analyst_name in potential_recipients:
        analyst_cats = df_full[df_full['Responsável'] == analyst_name]
        similar_cats_df = analyst_cats[analyst_cats['Grupo'] == category_group]
        suggestions.append({
            'name': analyst_name,
            'similarity_count': len(similar_cats_df),
            'current_pi': current_pi_loads.get(analyst_name, 0),
            'similar_categories': similar_cats_df['Nome'].tolist()
        })
    suggestions.sort(key=lambda x: (-x['similarity_count'], x['current_pi']))
    return {"suggestions": suggestions[:5]}

def suggest_category_capture(target_analyst_name, df_full):
    if df_full is None or df_full.empty:
        return {"error": "Dados não disponíveis."}
    
    target_analyst_name = target_analyst_name.strip()
    
    # Calculate Team Stats
    pi_dist = calculate_pi_distribution(df_full)
    if not pi_dist:
        return {"error": "Não foi possível calcular dist PI."}
    
    # Filter only available analysts for stats
    # (Assuming we want to balance against the active team)
    available_analysts = get_available_recipients(df_full) 
    if not available_analysts:
         # Fallback if everyone is unavailable? Use all.
         available_analysts = list(pi_dist.keys())

    team_pis = [pi for name, pi in pi_dist.items() if name in available_analysts]
    team_avg = sum(team_pis) / len(team_pis) if team_pis else 0
    
    # Target Status
    target_pi = pi_dist.get(target_analyst_name, 0)
    
    # Target Predominant Group
    analyst_cats = df_full[df_full['Responsável'] == target_analyst_name]
    start_group = "Sem grupo principal"
    dominant_groups = []
    if not analyst_cats.empty and 'Grupo' in analyst_cats.columns:
        group_counts = analyst_cats['Grupo'].value_counts()
        if not group_counts.empty and group_counts.iloc[0] >= 3:
             max_c = group_counts.iloc[0]
             dominant_groups = group_counts[group_counts == max_c].index.tolist()
             start_group = ", ".join(dominant_groups)

    # Find Candidates
    candidates = []
    
    # Iterate all categories NOT owned by target
    # Only from available owners? Or any owner? Usually available owners logic applies to recipients.
    # But for "taking", maybe we can take from anyone, or maybe only active people.
    # Let's assume we can take from anyone who is in the dataframe, 
    # but maybe give preference or only allow taking from 'available' people if that's the rule.
    # The prompt doesn't specify constraint on source availability, but usually 'available' means 'can receive'.
    # A leaving analyst (unavailable) is a prime target for 'saindo', but here is 'captar'.
    # If someone is unavailable/vacation, we might not want to touch their stuff?
    # Let's stick to ALL categories for now, but maybe flag if owner is unavailable.
    
    # Optimization: pre-calculate owner stats
    owner_stats = {}
    for name in pi_dist:
        owner_stats[name] = {'pi': pi_dist[name], 'overloaded': pi_dist[name] > team_avg * 1.1}

    for idx, row in df_full.iterrows():
        owner = row['Responsável']
        if owner == target_analyst_name:
            continue
            
        cat_group = row.get('Grupo', 'Grupo Desconhecido')
        cat_pi = row.get('PI', 0)
        if math.isnan(cat_pi): cat_pi = 0
        
        # Scoring Logic
        # Priority 1: Predominant Group Match (Absolute)
        # Priority 2: PI Proximity (Closer to team_avg is better)
        
        is_predominant = (cat_group in dominant_groups)
        
        # Define owner_pi
        owner_pi = owner_stats.get(owner, {'pi': 0})['pi']
        
        # Calculate impact on target
        # We want the NEW PI (current + cat) to be close to team_avg.
        # Ideally, we want to FILL the gap.
        # Let's measure how much this category helps reduce the deficit.
        # Or simply: minimize abs(new_pi - target_mean).
        
        new_target_pi = target_pi + cat_pi
        dist_current = abs(target_pi - team_avg)
        dist_new = abs(new_target_pi - team_avg)
        
        # Improvement: 
        # If I am below avg, adding PI reduces distance -> positive improvement.
        # If I am above avg, adding PI increases distance -> negative improvement.
        # We generally expect "Captar" to be used by those below average.
        improvement = dist_current - dist_new
        
        # Candidates list
        # We will sort by (is_predominant, improvement) descending.
        
        candidates.append({
            'category_name': row.get('Nome', 'N/A'),
            'category_group': cat_group,
            'category_pi': cat_pi,
            'current_owner': owner,
            'owner_current_pi': owner_pi,
            'owner_is_overloaded': (owner_pi > team_avg),
            'owner_first_name': owner.split()[0] if owner else "",
            'is_predominant': is_predominant,
            'improvement': improvement
        })
        
    # Sort:
    # 1. is_predominant (True > False, so Reverse=True puts True first)
    # 2. improvement (Higher is better, Reverse=True puts High first)
    candidates.sort(key=lambda x: (x['is_predominant'], x['improvement']), reverse=True)
    
    # Extract first name for display
    first_name = target_analyst_name.split()[0] if target_analyst_name else ""
    
    return {
        'analyst_stats': {
            'name': target_analyst_name,
            'first_name': first_name,
            'current_pi': target_pi,
            'team_avg': team_avg,
            'predominant_group': start_group
        },
        'suggestions': candidates[:5] # Return top 5
    }


def suggest_general_redistribution(df):
    # FASE 0: PREPARAÇÃO E MÉTRICAS
    analistas_disponiveis = get_available_recipients(df)
    if not analistas_disponiveis:
        return {"error": "Nenhum analista disponível para a redistribuição."}

    pi_total = df['PI'].sum()
    pi_alvo = pi_total / len(analistas_disponiveis)
    pi_max = pi_alvo * 2

    carga_sugerida = {analista: 0 for analista in analistas_disponiveis}
    atribuicoes = []
    categorias_a_atribuir = df.copy()
    avisos = []

    # FASE 1: MEGA-CATEGORIAS
    mega_categorias_idx = categorias_a_atribuir[categorias_a_atribuir['PI'] > pi_max].index
    for idx in mega_categorias_idx:
        cat = categorias_a_atribuir.loc[idx]
        analista_atual = cat['Responsável']
        atribuicoes.append({'id': cat['id'], 'Nome': cat['Nome'], 'Grupo': cat['Grupo'], 'PI': cat['PI'], 'Responsável_Atual': analista_atual, 'Responsável_Sugerido': analista_atual})
        if analista_atual in carga_sugerida:
            carga_sugerida[analista_atual] += cat['PI']
            if analista_atual in analistas_disponiveis:
                analistas_disponiveis.remove(analista_atual)
        categorias_a_atribuir.drop(idx, inplace=True)
        avisos.append(f"O analista {analista_atual} foi fixado com a categoria '{cat['Nome']}' (PI: {int(cat['PI'])}) por exceder o limite máximo de carga e não participará do balanceamento.")

    # FASE 2: ANCORAGEM POR ESPECIALIZAÇÃO
    especialidades = {}
    for analista in analistas_disponiveis:
        analyst_cats = df[df['Responsável'] == analista]
        if analyst_cats.empty:
            especialidades[analista] = None
            continue
        group_counts = analyst_cats['Grupo'].value_counts()
        if not group_counts.empty and group_counts.iloc[0] >= 3:
            max_count = group_counts.iloc[0]
            dominant_groups = group_counts[group_counts == max_count].index.tolist()
            if len(dominant_groups) == 1:
                especialidades[analista] = dominant_groups[0]
            else:
                group_pi = {group: analyst_cats[analyst_cats['Grupo'] == group]['PI'].sum() for group in dominant_groups}
                especialidades[analista] = max(group_pi, key=group_pi.get)
        else:
            especialidades[analista] = None

    # FASE 3: ATRIBUIÇÃO POR ESPECIALIDADE
    for analista in sorted(analistas_disponiveis):
        esp = especialidades.get(analista)
        if not esp:
            continue
        cats_do_grupo = categorias_a_atribuir[categorias_a_atribuir['Grupo'] == esp]
        cats_do_grupo = cats_do_grupo.sort_values(by='PI', ascending=False)
        for _, cat_row in cats_do_grupo.iterrows():
            if cat_row['PI'] + carga_sugerida[analista] <= pi_max:
                atribuicoes.append({'id': cat_row['id'], 'Nome': cat_row['Nome'], 'Grupo': cat_row['Grupo'], 'PI': cat_row['PI'], 'Responsável_Atual': cat_row['Responsável'], 'Responsável_Sugerido': analista})
                carga_sugerida[analista] += cat_row['PI']
                categorias_a_atribuir = categorias_a_atribuir.drop(cat_row.name)

    # FASE 4: BALANCEAMENTO GERAL
    for _, cat_row in categorias_a_atribuir.sort_values(by='PI', ascending=False).iterrows():
        analista_menos = min(carga_sugerida, key=carga_sugerida.get) if carga_sugerida else None
        if analista_menos is None:
            continue
        if cat_row['PI'] + carga_sugerida[analista_menos] <= pi_max:
            atribuicoes.append({'id': cat_row['id'], 'Nome': cat_row['Nome'], 'Grupo': cat_row['Grupo'], 'PI': cat_row['PI'], 'Responsável_Atual': cat_row['Responsável'], 'Responsável_Sugerido': analista_menos})
            carga_sugerida[analista_menos] += cat_row['PI']
        else:
            atribuicoes.append({'id': cat_row['id'], 'Nome': cat_row['Nome'], 'Grupo': cat_row['Grupo'], 'PI': cat_row['PI'], 'Responsável_Atual': cat_row['Responsável'], 'Responsável_Sugerido': analista_menos})
            carga_sugerida[analista_menos] += cat_row['PI']
            avisos.append(f"A categoria '{cat_row['Nome']}' não pôde ser alocada sem exceder o limite de PI. Como sugestão delicada, foi atribuída ao analista com a menor carga atual: {analista_menos}.")

    # --- MÉTRICAS FINAIS ---
    carga_atual = calculate_pi_distribution(df)
    cargas_atuais_np = np.array(list(carga_atual.values())) if carga_atual else np.array([0])
    cargas_sugeridas_np = np.array(list(carga_sugerida.values())) if carga_sugerida else np.array([0])

    movidas = sum(1 for a in atribuicoes if a['Responsável_Atual'] != a['Responsável_Sugerido'])

    resultado = {
        "sugestoes": atribuicoes,
        "metricas_antes": {
            "pi_medio": float(np.mean(cargas_atuais_np)),
            "desvio_padrao": float(np.std(cargas_atuais_np)),
            "max_carga": float(np.max(cargas_atuais_np)),
            "min_carga": float(np.min(cargas_atuais_np))
        },
        "metricas_depois": {
            "pi_medio": float(np.mean(cargas_sugeridas_np)),
            "desvio_padrao": float(np.std(cargas_sugeridas_np)),
            "max_carga": float(np.max(cargas_sugeridas_np)),
            "min_carga": float(np.min(cargas_sugeridas_np))
        },
        "gini_antes": round(gini(list(carga_atual.values())), 3),
        "gini_depois": round(gini(list(carga_sugerida.values())), 3),
        "churn_total_movidas": int(movidas),
        "carga_final_por_analista": {k: float(v) for k, v in carga_sugerida.items()},
        "avisos": avisos
    }
    return resultado

# --- Sessão / utilitários de DF ---

def get_df_from_session():
    upload_id = session.get('upload_id')
    if not upload_id:
        flash('Sessão expirada. Faça o upload novamente.', 'danger')
        return None
        
    try:
        # Busca o conteúdo HTML do Supabase
        if not supabase:
             flash('Erro de conexão com banco de dados.', 'danger')
             return None
             
        response = supabase.table('temp_uploads').select('content').eq('id', upload_id).execute()
        
        if not response.data:
             flash('Arquivo não encontrado no banco. Faça upload novamente.', 'warning')
             return None
             
        html_content = response.data[0]['content']
        
        # Carrega configurações (agora do banco também)
        category_map = load_category_map()
        
        # Processa
        df, unmapped_names = parse_html_to_df(html_content, category_map)
        
        if df is None or df.empty:
            flash('Falha ao processar o arquivo da sessão ou o arquivo não contém dados válidos.', 'danger')
            return None
            
        session['unmapped_categories'] = unmapped_names
        if unmapped_names and not session.get('diagnostic_shown'):
            flash(f"{len(unmapped_names)} categorias não mapeadas foram encontradas. Vá para a aba 'Editar Grupos' para associá-las a um grupo.", "warning")
            session['diagnostic_shown'] = True
        return df
        
    except Exception as e:
        flash(f'Erro ao recuperar dados: {e}', 'danger')
        return None

# --- Rotas ---
@app.route('/toggle-analyst-availability', methods=['POST'])
def toggle_analyst_availability():
    """
    Alterna indisponibilidade do analista.
    - Cria a entrada no analyst_state.json se não existir (usa display do DF atual se possível).
    - Sempre responde JSON para evitar quebra no front.
    """
    try:
        analyst_name = (request.form.get('analyst_name') or '').strip()
        if not analyst_name:
            return jsonify(success=False, message="Nome do analista não fornecido."), 400

        key = analyst_name.lower().strip()
        state = load_analyst_state()

        # Se não existir no arquivo, cria automaticamente
        if key not in state:
            display = analyst_name
            df = None
            try:
                df = get_df_from_session()
            except Exception:
                df = None
            if df is not None and 'Responsável' in df.columns:
                match = df[df['Responsável'].str.lower().str.strip() == key]
                if not match.empty:
                    display = match['Responsável'].iloc[0]
            state[key] = {
                "display": display,
                "indisponivel": False,
                "updated_at": datetime.utcnow().isoformat() + 'Z'
            }

        # Alterna e salva
        state[key]['indisponivel'] = not bool(state[key].get('indisponivel', False))
        state[key]['updated_at'] = datetime.utcnow().isoformat() + 'Z'
        save_analyst_state(state)

        return jsonify(success=True,
                       newState=state[key]['indisponivel'],
                       display=state[key].get('display', analyst_name))

    except Exception as e:
        # Garante JSON mesmo em erro inesperado
        return jsonify(success=False, message=f"Erro interno: {e}"), 500


@app.route('/reset')
def reset_session():
    upload_id = session.get('upload_id')
    if upload_id and supabase:
        try:
            supabase.table('temp_uploads').delete().eq('id', upload_id).execute()
        except Exception as e:
            print(f"Erro ao deletar upload temporário: {e}")
            
    session.pop('upload_id', None)
    session.pop('uploaded_filepath', None) # Limpeza legado
    session.pop('diagnostic_shown', None)
    session.pop('unmapped_categories', None)
    flash("Sessão limpa. Carregue um novo arquivo.", "info")
    return redirect(url_for('upload_page'))

@app.route('/', methods=['GET', 'POST'])
def upload_page():
    # Verifica se existe um ID de upload na sessão
    if request.method == 'GET' and 'upload_id' in session:
        # (Opcional) Poderíamos verificar se o ID ainda existe no banco
        return redirect(url_for('analyst_list_page'))
        
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Nenhum arquivo selecionado', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename):
            flash('Selecione um arquivo .html válido', 'warning')
            return redirect(request.url)
            
        session.pop('diagnostic_shown', None)
        session.pop('unmapped_categories', None)
        
        # Leitura em memória e envio para Supabase
        try:
            content = file.read().decode('utf-8', errors='replace')
            
            if not supabase:
                 flash("Erro: Conexão com Supabase indisponível.", "danger")
                 return redirect(request.url)

            # Salva na tabela temporária
            response = supabase.table('temp_uploads').insert({"content": content}).execute()
            
            if response.data:
                upload_id = response.data[0]['id']
                session['upload_id'] = upload_id
                flash('Arquivo processado e salvo na nuvem temporariamente!', 'success')
                return redirect(url_for('analyst_list_page'))
            else:
                 flash("Erro ao salvar arquivo no Supabase.", "danger")

        except Exception as e:
            flash(f"Erro ao processar upload: {e}", "danger")
            return redirect(request.url)

    return render_template("upload.html")

@app.route('/analysts')
def analyst_list_page():
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    analyst_state = load_analyst_state()
    analyst_summary, _ = get_analyst_data(df.copy(), analyst_state)

    total_pi_sum = sum(a['total_pi'] for a in analyst_summary)
    average_pi = total_pi_sum / len(analyst_summary) if analyst_summary else 0
    for analyst in analyst_summary:
        analyst['pi_color'] = 'text-dark'
        if average_pi > 0:
            if analyst['total_pi'] >= average_pi * 2:
                analyst['pi_color'] = 'textdanger'
            elif analyst['total_pi'] <= average_pi * 0.5:
                analyst['pi_color'] = 'text-success'

    sort_by = request.args.get('sort_by')
    if sort_by == 'pi':
        analyst_summary.sort(key=lambda x: x['total_pi'], reverse=True)
    else:
        analyst_summary.sort(key=lambda x: _norm_key(x['Responsável']))

    return render_template("analyst_list.html", analysts=analyst_summary, average_pi=average_pi)

@app.route('/redistribute')
def suggest_general_redistribution_page():
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))

    results = suggest_general_redistribution(df)

    current_filters = request.args.getlist('analyst_filter')
    if "sugestoes" in results:
        if current_filters:
            results['sugestoes'] = [s for s in results['sugestoes'] if s['Responsável_Sugerido'] in current_filters]
        sort_by = request.args.get('sort_by')
        if sort_by == 'novo_analista':
            results['sugestoes'].sort(key=lambda x: _norm_key(x['Responsável_Sugerido']))
        else:
            results['sugestoes'].sort(key=lambda x: _norm_key(x['Nome']))

    all_suggested_analysts = sorted(list(set(
        s['Responsável_Sugerido'] for s in suggest_general_redistribution(df).get('sugestoes', [])
    )))

    return render_template(
        "redistribute_suggestion.html",
        results=results,
        all_suggested_analysts=all_suggested_analysts,
        current_filters=current_filters
    )

@app.route('/redistribute/details')
def redistribute_details_page():
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    results = suggest_general_redistribution(df)
    details = build_redistribution_details(df, results)
    return render_template("redistribute_details.html", results=results, details=details)

# --- Exportar apenas a tabela de redistribuição (5 colunas) ---
@app.route('/export/sugestao.xlsx')
def export_sugestao_xlsx():
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))

    results = suggest_general_redistribution(df)
    sug = results.get('sugestoes', [])[:]

    # Respeita filtros e ordenação atuais
    current_filters = request.args.getlist('analyst_filter')
    if current_filters:
        sug = [s for s in sug if s['Responsável_Sugerido'] in current_filters]

    sort_by = request.args.get('sort_by')
    if sort_by == 'novo_analista':
        sug.sort(key=lambda x: _norm_key(x['Responsável_Sugerido']))
    else:
        sug.sort(key=lambda x: _norm_key(x['Nome']))

    cols = ['Nome', 'Grupo', 'PI', 'Responsável_Atual', 'Responsável_Sugerido']
    df_sug = pd.DataFrame(sug)[cols] if sug else pd.DataFrame(columns=cols)

    output = io.BytesIO()
    with pd.ExcelWriter(output) as writer:
        df_sug.to_excel(writer, index=False, sheet_name='Sugestoes')
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name='sugestao_redistribuicao.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ---------- NOVA ROTA: COMPARAR (3 inputs fixos) ----------

@app.route('/compare', methods=['GET', 'POST'])
def compare_page():
    if request.method == 'GET':
        return render_template("compare.html", report=None)

    # arquivos nomeados (ordem instrutiva: 1ª, 2ª, 3ª)
    f1 = request.files.get('file1')
    f2 = request.files.get('file2')
    f3 = request.files.get('file3')

    provided = [f for f in [f1, f2, f3] if f and f.filename and allowed_file(f.filename)]
    if len(provided) < 2:
        flash('Envie pelo menos 2 arquivos .html (1ª e 2ª exportação).', 'warning')
        return redirect(url_for('compare_page'))

    category_map = load_category_map()
    items = []
    for f in [f1, f2, f3]:
        if not f or not f.filename or not allowed_file(f.filename):
            continue
        label = os.path.splitext(f.filename)[0]
        html = f.read().decode('utf-8', errors='replace')
        df, _ = parse_html_to_df(html, category_map)
        items.append((label, df))

    report = build_simple_compare(items)
    return render_template("compare.html", report=report)

@app.route('/analyst/<path:analyst_name>/options')
def analyst_options_page(analyst_name):
    analyst_name = unquote(analyst_name)
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    return render_template("analyst_options.html", analyst_name=analyst_name)

@app.route('/analyst/<path:analyst_name>/saindo')
def saindo_page(analyst_name):
    analyst_name = unquote(analyst_name)
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    suggestions = suggest_distribution_for_leaving_analyst(analyst_name, df)
    return render_template("saindo_sugestions.html", analyst_name=analyst_name, suggestions=suggestions)

@app.route('/analyst/<path:analyst_name>/alterar')
def alterar_categorias_page(analyst_name):
    analyst_name = unquote(analyst_name)
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    
    # Filter categories for this analyst
    analyst_cats = df[df['Responsável'] == analyst_name].to_dict(orient='records')
    return render_template("alterar_categorias.html", analyst_name=analyst_name, categories=analyst_cats)


@app.route('/analyst/<path:analyst_name>/captar')
def captar_page(analyst_name):
    analyst_name = unquote(analyst_name)
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    
    result = suggest_category_capture(analyst_name, df)
    if "error" in result:
        flash(result["error"], "danger")
        return redirect(url_for('analyst_options_page', analyst_name=analyst_name))
        
    return render_template("captar_suggestion.html", 
                           analyst_name=analyst_name,
                           analyst_stats=result['analyst_stats'],
                           suggestions=result['suggestions'])


@app.route('/analyst/<path:analyst_name>/repassar/<int:category_id>')
def repassar_page(analyst_name, category_id):
    analyst_name = unquote(analyst_name)
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    sort_by = request.args.get('sort_by', 'similarity')
    category_info_series = df.loc[df['id'] == category_id].iloc[0] if not df[df['id'] == category_id].empty else None
    if category_info_series is None:
        flash(f"Categoria com ID {category_id} não encontrada.", "error")
        return redirect(url_for('alterar_categorias_page', analyst_name=analyst_name))
    suggestions = suggest_recipients_for_category(category_id, analyst_name, df)
    if sort_by == 'pi':
        suggestions.sort(key=lambda x: (x['current_pi'], -x['similarity_count']))
    else:
        suggestions.sort(key=lambda x: (-x['similarity_count'], x['current_pi']))
    final_suggestions = suggestions[:4]
    return render_template("repassar_suggestion.html",
                           analyst_name=analyst_name,
                           category_info=category_info_series.to_dict(),
                           suggestions=final_suggestions,
                           current_sort=sort_by)

@app.route('/categories', methods=['GET', 'POST'])
def categories_list_page():
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))

    search_query = request.args.get('search', '').strip()
    sort_by = (request.args.get('sort_by') or '').lower()
    order = (request.args.get('order') or ('desc' if sort_by == 'pi' else 'asc')).lower()

    simulation_results, sim_data = None, None
    if request.method == 'POST':
        sim_nome = request.form.get('sim_nome')
        sim_grupo = request.form.get('sim_grupo')
        sim_pi = int(request.form.get('sim_pi', 0))
        simulation_results = suggest_recipients_for_new_category(sim_grupo, df)
        sim_data = {'nome': sim_nome, 'grupo': sim_grupo, 'pi': sim_pi}

    filtered_df = df[df['Nome'].str.contains(search_query, case=False, na=False)] if search_query else df

    if sort_by == 'pi':
        filtered_df = filtered_df.sort_values(by='PI', ascending=(order == 'asc'))
    elif sort_by == 'responsavel':
        filtered_df = filtered_df.sort_values(
            by='Responsável',
            ascending=(order == 'asc'),
            key=lambda s: s.map(_norm_key)
        )

    categories = filtered_df.to_dict(orient='records')
    unique_groups = sorted(df['Grupo'].unique().tolist(), key=_norm_key)

    return render_template(
        "categories_list.html",
        categories=categories,
        unique_groups=unique_groups,
        search_query=search_query,
        simulation_results=simulation_results,
        sim_data=sim_data,
        current_sort=sort_by,
        current_order=order
    )

@app.route('/group/<path:group_name>')
def group_categories_page(group_name):
    group_name = unquote(group_name)
    df = get_df_from_session()
    if df is None:
        return redirect(url_for('upload_page'))
    categories = df[df['Grupo'] == group_name].to_dict(orient='records')
    return render_template("group_categories.html", categories=categories, group_name=group_name)

@app.route('/edit-groups', methods=['GET', 'POST'])
def edit_groups_page():
    if request.method == 'POST':
        action = request.form.get('action')
        current_map = load_category_map()

        if action == 'save_main_list':
            # 1. Atualiza categorias existentes
            for i in range(1, len(request.form) + 1):
                key_field = f'category_key_{i}'
                if key_field in request.form:
                    cat_key = request.form[key_field]
                    new_group = request.form[f'category_value_{i}']
                    if cat_key in current_map:
                        current_map[cat_key]['group'] = new_group

            # 2. Processa não mapeadas
            remaining_unmapped = []
            idx = 1
            while True:
                key_param = f'unmapped_key_{idx}'
                code_param = f'unmapped_code_{idx}'
                
                if key_param not in request.form and code_param not in request.form:
                    # Se não achou nem chave antiga nem código novo, e idx > 1, pode ser fim.
                    # Mas o form pode ter gaps se for dinâmico? No jinja loop.index é sequencial.
                    # Então se falhar um, acabou.
                    if idx > len(request.form): # Heurística de segurança
                        break
                    idx += 1
                    continue

                if code_param in request.form:
                    code = request.form[code_param]
                    name = request.form.get(f'unmapped_name_{idx}', code)
                    new_group = request.form[f'unmapped_value_{idx}']
                    
                    if new_group and new_group != "Grupo Desconhecido":
                        norm_key = _norm_code(code)
                        current_map[norm_key] = {
                            "code": code,
                            "name": name,
                            "group": new_group
                        }
                        flash(f"Categoria '{name}' mapeada.", "info")
                    else:
                         remaining_unmapped.append({"code": code, "name": name})
                
                elif key_param in request.form:
                    cat_name = request.form[key_param]
                    new_group = request.form[f'unmapped_value_{idx}']
                    if new_group and new_group != "Grupo Desconhecido":
                        norm_key = _norm_code(cat_name)
                        current_map[norm_key] = {
                            "code": cat_name,
                            "name": cat_name,
                            "group": new_group
                        }
                        flash(f"Categoria '{cat_name}' mapeada.", "info")
                    else:
                        remaining_unmapped.append(cat_name)
                
                idx += 1
                if idx > 10000: break # prevent infinite

            # 3. Processa "Ungrouped" (Realocar)
            idx = 1
            while True:
                code_param = f'ungrouped_code_{idx}'
                if code_param not in request.form:
                    if idx > len(request.form) + 100: 
                        break
                    idx += 1
                    continue
                
                code = request.form[code_param]
                new_group = request.form[f'ungrouped_value_{idx}']
                
                if new_group and new_group != "Grupo Desconhecido":
                    norm_key = _norm_code(code)
                    if norm_key in current_map:
                        current_map[norm_key]['group'] = new_group
                        flash(f"Categoria '{current_map[norm_key]['name']}' realocada.", "info")
                
                idx += 1
                if idx > 10000: break

            session['unmapped_categories'] = remaining_unmapped
            save_category_map(current_map)
            flash('Alterações salvas com sucesso!', 'success')

        elif action == 'add_group':
            new_group_name = request.form.get('new_group_name', '').strip()
            existing_groups = {d.get('group') for d in current_map.values()}
            if not new_group_name or len(new_group_name) < 5:
                flash("Nome do grupo deve ter no mínimo 5 caracteres.", "danger")
            elif new_group_name in existing_groups:
                flash(f"O grupo '{new_group_name}' já existe.", "warning")
            else:
                dummy_key = f"__placeholder_for_{new_group_name.replace(' ', '_')}__"
                current_map[dummy_key] = {
                    "code": dummy_key,
                    "name": new_group_name,
                    "group": new_group_name,
                    "placeholder": True
                }
                save_category_map(current_map)
                flash(f"Novo grupo '{new_group_name}' adicionado com sucesso.", "success")

        elif action == 'edit_group_name':
            old_group_name = request.form.get('old_group_name')
            new_group_name = request.form.get('edited_group_name', '').strip()
            if not old_group_name or not new_group_name or len(new_group_name) < 5:
                flash("Para editar, selecione um grupo e forneça um novo nome com no mínimo 5 caracteres.", "danger")
            elif old_group_name == new_group_name:
                flash("O novo nome do grupo é igual ao antigo.", "info")
            else:
                for data in current_map.values():
                    if data.get('group') == old_group_name:
                        data['group'] = new_group_name
                        if data.get('placeholder'):
                            data['name'] = new_group_name
                save_category_map(current_map)
                flash(f"Grupo '{old_group_name}' renomeado para '{new_group_name}' em todas as categorias associadas.", "success")

        elif action == 'delete_group':
            group_to_delete = request.form.get('group_to_delete')
            if not group_to_delete:
                flash("Nenhum grupo selecionado para exclusão.", "warning")
            else:
                keys_to_remove = []
                for key, data in current_map.items():
                    if data.get('group') == group_to_delete:
                        if data.get('placeholder'):
                            keys_to_remove.append(key)
                        else:
                            data['group'] = "Grupo Desconhecido"
                for k in keys_to_remove:
                    del current_map[k]
                save_category_map(current_map)
                flash(f"Grupo '{group_to_delete}' excluído. Todas as categorias associadas foram movidas para 'Grupo Desconhecido'.", "success")

        return redirect(url_for('edit_groups_page'))

    category_map = load_category_map()
    unmapped_categories = session.get('unmapped_categories', [])
    ungrouped_categories = []
    for key, data in category_map.items():
        if data.get('group') == "Grupo Desconhecido" and not data.get('placeholder'):
             ungrouped_categories.append(data)

    all_groups = set()
    for data in category_map.values():
        g = data.get('group')
        if g: all_groups.add(g)
    unique_groups = sorted(list(all_groups))
    return render_template("edit_groups.html", category_map=category_map, unmapped_categories=unmapped_categories, ungrouped_categories=ungrouped_categories, unique_groups=unique_groups)

@app.route('/new-upload')
def new_upload_page():
    session.pop('uploaded_filepath', None)
    session.pop('unmapped_categories', None)
    session.pop('diagnostic_shown', None)
    flash('Sessão anterior encerrada. Por favor, carregue um novo arquivo.', 'info')
    return redirect(url_for('upload_page'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)




