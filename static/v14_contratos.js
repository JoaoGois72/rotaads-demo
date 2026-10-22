(() => {
  'use strict';
  const vehicle = document.querySelector('#v14-vehicle');
  const type = document.querySelector('#v14-benef-type');
  const beneficiary = document.querySelector('#v14-benef-id');
  if (!vehicle || !type || !beneficiary) return;
  const render = () => {
    const o = vehicle.selectedOptions[0];
    beneficiary.replaceChildren();
    const choice = document.createElement('option');
    choice.value = '';
    choice.textContent = 'Escolha primeiro um veículo';
    beneficiary.append(choice);
    if (!o || !o.value) return;
    const fleet = o.dataset.frotaId;
    const driver = o.dataset.motoristaId;
    if (!fleet && driver) type.value = 'MOTORISTA';
    else if (fleet && !driver) type.value = 'FROTA';
    const id = type.value === 'FROTA' ? fleet : driver;
    const label = type.value === 'FROTA' ? o.dataset.frota : o.dataset.motorista;
    choice.textContent = id ? 'Selecione o beneficiário' : 'Sem beneficiário deste tipo neste veículo';
    if (id) {
      const option = document.createElement('option');
      option.value = id;
      option.textContent = label || `${type.value} #${id}`;
      option.selected = true;
      beneficiary.append(option);
    }
  };
  vehicle.addEventListener('change', render);
  type.addEventListener('change', render);
  render();
})();
