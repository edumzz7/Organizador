import os
import json
import re
import io
import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, send_file, jsonify, flash
from bs4 import BeautifulSoup
from datetime import datetime

revisao_logs_bp = Blueprint('logs', __name__, 
                           template_folder='../../templates',
                           static_folder='../../static/revisao_logs')

# --- CONFIGURAÇÃO INICIAL ---
REVISIONS_DIR = 'revisoes' # Mantido na raiz do projeto principal

# --- DADOS CONSTANTES ---
TIPOS_ERRO = ["--- Selecione ---", "Ofertas misturadas", "Categoria errada", "Nome duplicado", "Imagem incorreta", "Outro"]
DETALHES_ERRO_COMPLETO = ["--- Detalhe ---", "Voltagem", "Cor", "Modelo", "Outro"]
DETALHES_ERRO_RESTRITO = ["--- Detalhe ---"]

# --- FUNÇÕES AUXILIARES ---

def sanitize_filename(name):
    name = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')
    return name

def parse_html_table(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    table = soup.find('table')
    data, extracted_date_str = [], None
    if not table: return data, None
        
    for i, row in enumerate(table.find_all('tr')[1:]):
        cols = row.find_all('td')
        if len(cols) > 9:
            local_text = cols[6].text.strip()
            if "Justificativa Pular Produto" in local_text: continue
            
            if not extracted_date_str:
                date_from_html = cols[1].text.strip()
                try:
                    extracted_date_str = datetime.strptime(date_from_html, '%d/%m/%Y').strftime('%Y-%m-%d')
                except ValueError:
                    extracted_date_str = datetime.now().strftime('%Y-%m-%d')

            ligacao = cols[5].text.strip()
            p3 = cols[9].text.strip()
            if p3: data.append({'p3': p3, 'ligacao': ligacao, 'local': local_text})
    return data, extracted_date_str

# --- ROTAS DA APLICAÇÃO ---

@revisao_logs_bp.route('/')
def dashboard():
    try:
        if not os.path.exists(REVISIONS_DIR):
            os.makedirs(REVISIONS_DIR)
            
        review_files = sorted([f for f in os.listdir(REVISIONS_DIR) if f.endswith('.json')], reverse=True)
        employees = {}
        for filename in review_files:
            with open(os.path.join(REVISIONS_DIR, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
                employee_name = data['header']['employee']
                if employee_name not in employees:
                    employees[employee_name] = []
                employees[employee_name].append({'filename': filename, 'category': data['header']['category'], 'date': data['header']['date']})
        
        return render_template('revisao_logs/dashboard.html', employees=employees)
    except Exception as e:
        flash(f"Erro ao carregar o dashboard: {e}", "danger")
        return render_template('revisao_logs/dashboard.html', employees={})

@revisao_logs_bp.route('/analista/<employee_name>')
def analyst_dashboard(employee_name):
    try:
        all_files = sorted([f for f in os.listdir(REVISIONS_DIR) if f.endswith('.json')])
        employee_reviews = []
        for filename in all_files:
            with open(os.path.join(REVISIONS_DIR, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data['header']['employee'] == employee_name:
                    employee_reviews.append({
                        'filename': filename, 'category': data['header']['category'],
                        'date': data['header']['date'],
                        'error_percentage': data.get('calculator', {}).get('error_percentage', 0.0)
                    })
        
        error_percentages = [review['error_percentage'] for review in employee_reviews]
        chart_data = error_percentages[-15:] 

        return render_template('revisao_logs/analyst_performance.html', 
                               employee_name=employee_name, 
                               employee_reviews=employee_reviews, 
                               chart_data=chart_data)
    except Exception as e:
        flash(f"Erro ao carregar dados do analista: {e}", "danger")
        return redirect(url_for('revisao_logs.dashboard'))

@revisao_logs_bp.route('/criar_revisao', methods=['POST'])
def criar_revisao():
    if 'file' not in request.files or request.files['file'].filename == '':
        flash("Nenhum arquivo HTML selecionado!", "warning")
        return redirect(url_for('logs.dashboard'))

    file = request.files['file']
    employee = request.form.get('employee')
    category = request.form.get('category')
    
    if not all([employee, category]):
        flash("Nome do funcionário e categoria são obrigatórios!", "warning")
        return redirect(url_for('logs.dashboard'))

    html_content = file.read()
    parsed_data, file_date_str = parse_html_table(html_content)
    
    if not file_date_str:
        flash("Não foi possível encontrar uma data válida no arquivo HTML.", "danger")
        return redirect(url_for('logs.dashboard'))
    
    filename = f"{file_date_str}_{sanitize_filename(employee)}_{sanitize_filename(category)}.json"
    filepath = os.path.join(REVISIONS_DIR, filename)
    
    if os.path.exists(filepath):
        flash(f"Uma revisão para este funcionário, categoria e data ({file_date_str}) já existe.", "info")
        return redirect(url_for('logs.view_revisao', filename=filename))

    if not parsed_data:
        flash("Nenhum dado válido encontrado no arquivo HTML.", "danger")
        return redirect(url_for('logs.dashboard'))

    review_data = {
        "header": {"employee": employee, "category": category, "date": file_date_str},
        "analyst_mode": True,
        "calculator": {"revisados": len(parsed_data), "erros": 0, "error_percentage": 0.0},
        "table_data": [
            {"ligacao": row['ligacao'], "local": row['local'], "p3": row['p3'], "tipo_erro_idx": 0, 
             "detalhes_erro_txt": "--- Detalhe ---", "infos": "", "grave": False, "corrigido": False, "obs_analista": ""}
            for row in parsed_data
        ]
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(review_data, f, indent=4, ensure_ascii=False)

    flash("Nova revisão criada com sucesso!", "success")
    return redirect(url_for('logs.view_revisao', filename=filename))

@revisao_logs_bp.route('/revisao/<filename>', methods=['GET', 'POST'])
def view_revisao(filename):
    filepath = os.path.join(REVISIONS_DIR, filename)
    if not os.path.exists(filepath):
        flash("Arquivo de revisão não encontrado.", "danger")
        return redirect(url_for('logs.dashboard'))

    with open(filepath, 'r', encoding='utf-8') as f:
        review_data = json.load(f)

    if request.method == 'POST':
        revisados = int(request.form.get('revisados', 0))
        erros = int(request.form.get('erros', 0))
        review_data['calculator']['revisados'] = revisados
        review_data['calculator']['erros'] = erros
        
        if revisados > 0:
            review_data['calculator']['error_percentage'] = round((erros / revisados) * 100, 1)
        else:
            review_data['calculator']['error_percentage'] = 0.0

        review_data['analyst_mode'] = 'analyst_mode' in request.form
        for i in range(len(review_data['table_data'])):
            row = review_data['table_data'][i]
            row['tipo_erro_idx'] = int(request.form.get(f'tipo_erro_{i}', 0))
            row['detalhes_erro_txt'] = request.form.get(f'detalhes_erro_{i}', '')
            row['infos'] = request.form.get(f'infos_{i}', '')
            row['grave'] = f'grave_{i}' in request.form
            row['corrigido'] = f'corrigido_{i}' in request.form
            row['obs_analista'] = request.form.get(f'obs_analista_{i}', '')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(review_data, f, indent=4, ensure_ascii=False)
        
        flash("Alterações salvas com sucesso!", "success")
        return redirect(url_for('logs.view_revisao', filename=filename))
    
    return render_template('revisao_logs/review_detail.html', review_data=review_data, filename=filename,
                           tipos_erro=TIPOS_ERRO, detalhes_completo=DETALHES_ERRO_COMPLETO,
                           detalhes_restrito=DETALHES_ERRO_RESTRITO)

@revisao_logs_bp.route('/excluir_revisao/<filename>', methods=['POST'])
def excluir_revisao(filename):
    try:
        filepath = os.path.join(REVISIONS_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            flash('Revisão excluída com sucesso!', 'success')
        else:
            flash('Arquivo de revisão não encontrado.', 'warning')
    except Exception as e:
        flash(f'Erro ao excluir revisão: {e}', 'danger')
    return redirect(url_for('revisao_logs.dashboard'))

@revisao_logs_bp.route('/exportar_xlsx/<filename>')
def exportar_xlsx(filename):
    filepath = os.path.join(REVISIONS_DIR, filename)
    if not os.path.exists(filepath): return redirect(url_for('logs.dashboard'))
    with open(filepath, 'r', encoding='utf-8') as f: review_data = json.load(f)
    export_data = []
    for row in review_data['table_data']:
        if row['tipo_erro_idx'] > 0:
            export_data.append({
                'P3': row['p3'], 'Ligação': row['ligacao'], 'Local': row['local'],
                'Tipo de Erro': TIPOS_ERRO[row['tipo_erro_idx']], 'Detalhes': row['detalhes_erro_txt'],
                'Infos': row['infos'], 'Grave': 'Sim' if row['grave'] else 'Não'
            })
    if not export_data:
        flash("Nenhuma linha com erro para exportar.", "info")
        return redirect(url_for('logs.view_revisao', filename=filename))
    df = pd.DataFrame(export_data)
    output = io.BytesIO()
    df.to_excel(output, index=False, sheet_name='Erros Reportados')
    output.seek(0)
    return send_file(output, download_name=f'revisao_erros_{filename.replace(".json", ".xlsx")}', as_attachment=True)
