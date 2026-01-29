from flask import Blueprint, render_template, request, redirect, url_for, jsonify, send_file, flash
import json
import io
import os
from .models import init_db, list_projects, create_project, get_project, update_project, delete_project, import_project

gestao_projetos_bp = Blueprint('gestao_projetos', __name__,
                               template_folder='../../templates',
                               static_folder='../../static/gestao_projetos')

# Inicializa o banco ao carregar o módulo
init_db()

@gestao_projetos_bp.route('/')
def dashboard():
    projects = list_projects()
    return render_template('gestao_projetos/dashboard.html', projects=projects)

@gestao_projetos_bp.route('/novo', methods=['POST'])
def novo_projeto():
    nome = request.form.get('cliente_nome')
    if nome:
        p_id = create_project(nome)
        flash(f"Projeto '{nome}' criado com sucesso!", "success")
        return redirect(url_for('gestao_projetos.workspace', project_id=p_id))
    flash("Nome do cliente é obrigatório.", "danger")
    return redirect(url_for('gestao_projetos.dashboard'))

@gestao_projetos_bp.route('/workspace/<project_id>')
def workspace(project_id):
    project = get_project(project_id)
    if not project:
        flash("Projeto não encontrado.", "danger")
        return redirect(url_for('gestao_projetos.dashboard'))
    return render_template('gestao_projetos/workspace.html', project=project)


@gestao_projetos_bp.route('/save/<project_id>', methods=['POST'])
def save_project(project_id):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Sem dados"}), 400
    
    project = get_project(project_id)
    if not project:
        return jsonify({"success": False, "message": "Projeto não encontrado"}), 404
    
    # Atualiza campos
    cliente_nome = data.get('cliente_nome', project['cliente_nome'])
    status = data.get('status', project['status'])
    # O dados_json é o objeto completo que vem do JS
    dados = data.get('dados', project['dados'])
    
    update_project(project_id, cliente_nome, status, dados)
    return jsonify({"success": True})

@gestao_projetos_bp.route('/export/<project_id>')
def export_project(project_id):
    project = get_project(project_id)
    if not project:
        flash("Projeto não encontrado.", "danger")
        return redirect(url_for('gestao_projetos.dashboard'))
    
    # Remove o row object e deixa limpo para JSON
    output = json.dumps(project, indent=4, ensure_ascii=False)
    buffer = io.BytesIO()
    buffer.write(output.encode('utf-8'))
    buffer.seek(0)
    
    filename = f"projeto_{project['cliente_nome'].replace(' ', '_')}.json"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/json')

@gestao_projetos_bp.route('/import', methods=['POST'])
def import_project_route():
    if 'file' not in request.files:
        flash("Nenhum arquivo enviado.", "danger")
        return redirect(url_for('gestao_projetos.dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash("Arquivo inválido.", "danger")
        return redirect(url_for('gestao_projetos.dashboard'))
    
    try:
        content = file.read().decode('utf-8')
        if import_project(content):
            flash("Projeto importado com sucesso!", "success")
        else:
            flash("Erro ao processar o formato do JSON.", "danger")
    except Exception as e:
        flash(f"Erro na importação: {e}", "danger")
        
    return redirect(url_for('gestao_projetos.dashboard'))

@gestao_projetos_bp.route('/delete/<project_id>', methods=['POST'])
def delete_project_route(project_id):
    delete_project(project_id)
    flash("Projeto excluído.", "success")
    return redirect(url_for('gestao_projetos.dashboard'))
