document.addEventListener('DOMContentLoaded', () => {
  const icons = document.querySelectorAll('.availability-icon');

  icons.forEach(icon => {
    icon.addEventListener('click', (event) => {
      event.preventDefault();

      const analystName = icon.dataset.analystName;
      const formData = new FormData();
      formData.append('analyst_name', analystName);

      fetch('/toggle-analyst-availability', {
        method: 'POST',
        body: formData
      })
      .then(async (res) => {
        const ct = (res.headers.get('content-type') || '').toLowerCase();
        const isJson = ct.includes('application/json');

        const payload = isJson ? await res.json() : { success: false, message: await res.text() };

        if (!res.ok || !payload.success) {
          const msg = payload && payload.message ? payload.message : `Falha ao alternar disponibilidade (${res.status})`;
          throw new Error(msg);
        }

        const indisponivel = !!payload.newState;

        // Alterna classes de cor do ícone (indisponível = vermelho; disponível = cinza)
        // Remove estilos antigos
        icon.classList.remove(
        'text-danger', 'text-secondary',
        'bi-exclamation-triangle', 'bi-exclamation-triangle-fill'
);

// Define novo estado
if (indisponivel) {
  // indisponível: ícone preenchido + vermelho
  icon.classList.add('bi-exclamation-triangle-fill', 'text-danger');
} else {
  // disponível: ícone de contorno + cinza
  icon.classList.add('bi-exclamation-triangle', 'text-secondary');
}


        // Atualiza tooltip/title
        icon.title = `Clique para marcar como ${indisponivel ? 'disponível' : 'indisponível'}`;

        showToast(`Disponibilidade de "${payload.display || analystName}" atualizada.`);
      })
      .catch(err => {
        console.error('Toggle availability error:', err);
        alert('Ocorreu um erro de comunicação com o servidor.');
      });
    });
  });

  function showToast(message) {
    const toastEl = document.createElement('div');
    toastEl.className = 'toast-notification';
    toastEl.textContent = message;
    document.body.appendChild(toastEl);

    setTimeout(() => toastEl.classList.add('show'), 10);
    setTimeout(() => {
      toastEl.classList.remove('show');
      setTimeout(() => document.body.removeChild(toastEl), 500);
    }, 2500);
  }
});
