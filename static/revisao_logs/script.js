// static/script.js

// Pega os dados JSON embutidos no HTML de forma segura
const appDataElement = document.getElementById('app-data');
const appData = appDataElement ? JSON.parse(appDataElement.textContent) : {};
const { reviewData, chartData, tiposErro, detalhesCompleto, detalhesRestrito } = appData;

document.addEventListener('DOMContentLoaded', function() {
    // Se reviewData existe, estamos na página de revisão diária
    if (reviewData) {
        initializeDailyReviewPage();
    }
    // Se chartData existe, estamos na página de desempenho do analista
    if (chartData) {
        initializePerformanceChart();
    }
});

function initializeDailyReviewPage() {
    initializeRevisorMode();
    initializeDetalhesDropdowns();
    initializeGraveErrorCounter();
    calculateError();

    document.getElementById('revisorModeCheckbox').addEventListener('change', toggleRevisorMode);
    document.getElementById('filterErrorsCheckbox').addEventListener('change', filterTableRows);
    document.querySelectorAll('.grave-checkbox').forEach(cb => cb.addEventListener('change', updateGraveErrorCount));
    
    document.querySelectorAll('select[name^="tipo_erro_"]').forEach(select => {
        select.addEventListener('change', () => handleTipoErroChange(select));
    });
}

function initializeRevisorMode() { toggleRevisorMode(); }

function toggleRevisorMode() {
    const isRevisorMode = document.getElementById('revisorModeCheckbox').checked;
    document.body.classList.toggle('revisor-mode-active', isRevisorMode);
    filterTableRows();
}

function filterTableRows() {
    const isFilterActive = document.getElementById('filterErrorsCheckbox').checked;
    const isRevisorMode = document.getElementById('revisorModeCheckbox').checked;
    
    if (!isFilterActive || !isRevisorMode) {
        document.querySelectorAll('#reviewTable tbody tr').forEach(row => row.style.display = '');
        return;
    }

    document.querySelectorAll('#reviewTable tbody tr').forEach((row) => {
        const tipoSelect = row.querySelector('select[name^="tipo_erro_"]');
        row.style.display = (tipoSelect && tipoSelect.selectedIndex > 0) ? '' : 'none';
    });
}

function handleTipoErroChange(tipoSelect) {
    updateDetalhes(tipoSelect);
    filterTableRows();
}

function initializeDetalhesDropdowns() {
    const tableRows = document.getElementById('reviewTable').querySelectorAll('tbody tr');
    tableRows.forEach((tr, index) => {
        const tipoSelect = tr.querySelector(`select[name="tipo_erro_${index}"]`);
        if (tipoSelect) updateDetalhes(tipoSelect);
    });
}

function updateDetalhes(tipoSelect) {
    const rowIndex = tipoSelect.dataset.rowIndex;
    const detalhesSelect = document.getElementById(`detalhes_${rowIndex}`);
    const tipoSelecionado = tipoSelect.options[tipoSelect.selectedIndex].text;
    const valorAnterior = reviewData.table_data[rowIndex].detalhes_erro_txt;
    
    detalhesSelect.innerHTML = '';
    let options = (tipoSelecionado === "Ofertas misturadas") ? detalhesCompleto : detalhesRestrito;
    
    options.forEach(optionText => {
        const option = document.createElement('option');
        option.value = optionText;
        option.textContent = optionText;
        if (optionText === valorAnterior) { option.selected = true; }
        detalhesSelect.appendChild(option);
    });
}

function calculateError() {
    const revisadosInput = document.getElementById('revisadosInput');
    const errosInput = document.getElementById('errosInput');
    if (!revisadosInput || !errosInput) return; // Sai se não estiver na página de revisão

    const revisados = parseInt(revisadosInput.value) || 0;
    const erros = parseInt(errosInput.value) || 0;
    const resultLabel = document.getElementById('resultLabel');
    resultLabel.textContent = (revisados === 0) ? `% Erro: ${erros > 0 ? '>100%' : '0.0%'}` : `% Erro: ${((erros / revisados) * 100).toFixed(1)}%`;
}

function initializeGraveErrorCounter() { updateGraveErrorCount(); }

function updateGraveErrorCount() {
    const count = document.querySelectorAll('.grave-checkbox:checked').length;
    const label = document.getElementById('graveErrorLabel');
    if(label) label.textContent = `- ${count} Graves`;
}

// CORREÇÃO #2: Lógica do gráfico agora é dinâmica
function initializePerformanceChart() {
    const ctx = document.getElementById('performanceChart').getContext('2d');
    
    // Gera os rótulos dinamicamente com base no número de dias com dados
    const labels = Array.from({ length: chartData.length }, (_, i) => `Dia ${i + 1}`);
    
    const data = {
        labels: labels,
        datasets: [{
            label: '% de Erro',
            data: chartData,
            borderColor: '#007bff',
            backgroundColor: 'rgba(0, 123, 255, 0.1)',
            fill: true,
            tension: 0.1
        }]
    };
    new Chart(ctx, {
        type: 'line', data: data, options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
    });
}