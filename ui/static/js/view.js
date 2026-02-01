const View = {
    // --- Экраны ---
    showSetup: () => {
        document.getElementById('main-screen').classList.add('hidden');
        document.getElementById('setup-screen').classList.remove('hidden');
    },

    showMain: () => {
        document.getElementById('setup-screen').classList.add('hidden');
        document.getElementById('main-screen').classList.remove('hidden');
    },

    setLoading: (isLoading) => {
        const el = document.getElementById('loading-modal');
        if (isLoading) el.classList.remove('hidden');
        else el.classList.add('hidden');
    },

    // --- Логи ---
    addLog: (msg, level) => {
        const container = document.getElementById('log-container');
        const line = document.createElement('div');

        const time = new Date().toLocaleTimeString('ru-RU');
        let colorClass = 'text-gray-300';
        let prefix = 'INFO';

        if (level === 'error') { colorClass = 'text-red-400 font-bold'; prefix = 'ERR'; }
        if (level === 'warning') { colorClass = 'text-yellow-400'; prefix = 'WARN'; }
        if (level === 'success') { colorClass = 'text-green-400'; prefix = 'OK'; }

        line.innerHTML = `<span class="text-gray-600 select-none mr-2">[${time}]</span><span class="text-xs font-bold w-8 inline-block opacity-50">${prefix}</span> <span class="${colorClass}">${msg}</span>`;
        container.appendChild(line);
        container.scrollTop = container.scrollHeight;
    },

    // --- Таблица модов ---
    renderModList: (mods) => {
        const tbody = document.getElementById('mod-table-body');
        const emptyState = document.getElementById('empty-state');
        tbody.innerHTML = '';

        if (!mods || mods.length === 0) {
            emptyState.classList.remove('hidden');
            return;
        }
        emptyState.classList.add('hidden');

        mods.forEach(mod => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-700/50 transition duration-150 border-b border-gray-700/50 new-row';

            // Цвет бейджика типа
            let typeColor = 'bg-gray-600';
            if (mod.type === 'bus') typeColor = 'bg-yellow-600 text-yellow-100';
            if (mod.type === 'map') typeColor = 'bg-purple-600 text-purple-100';
            if (mod.type === 'mixed') typeColor = 'bg-blue-600 text-blue-100';

            tr.innerHTML = `
                <td class="p-4 font-medium text-white flex items-center gap-2">
                    <span class="w-2 h-2 rounded-full ${mod.is_enabled ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'}"></span>
                    ${mod.name}
                </td>
                <td class="p-4"><span class="px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider ${typeColor}">${mod.type}</span></td>
                <td class="p-4 text-gray-400 font-mono text-xs">${mod.date}</td>
                <td class="p-4 text-xs font-semibold ${mod.is_enabled ? 'text-green-400' : 'text-gray-500'}">
                    ${mod.is_enabled ? 'АКТИВЕН' : 'ОТКЛЮЧЕН'}
                </td>
                <td class="p-4 text-right space-x-2">
                    <button class="text-gray-400 hover:text-white transition" title="Включить/Выключить">⏯</button>
                    <button class="text-red-400 hover:text-red-300 transition" title="Удалить">🗑</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    },

    // --- Окно проверки (Review Modal) ---
    showReviewModal: (data) => {
        document.getElementById('review-mod-name').innerText = data.mod_name;
        document.getElementById('review-mod-type').innerText = data.type;

        // Рендер файлов для установки
        const mappedContainer = document.getElementById('mapped-rows');
        mappedContainer.innerHTML = data.mapped_files.map(f => `
            <div class="flex p-2 hover:bg-gray-700/30">
                <div class="w-1/2 break-all pr-2 text-gray-400">${f.source}</div>
                <div class="w-1/2 break-all text-green-400 font-mono">→ ${f.target}</div>
            </div>
        `).join('');

        // Рендер мусора
        const unmappedList = document.getElementById('unmapped-list');
        const unmappedPanel = document.getElementById('unmapped-panel');

        if (data.unmapped_files.length > 0) {
            unmappedPanel.classList.remove('hidden');
            unmappedList.innerHTML = data.unmapped_files.map(f => `
                <div class="break-all border-b border-red-900/20 pb-1 mb-1">${f.source}</div>
            `).join('');
        } else {
            unmappedPanel.classList.add('hidden');
        }

        document.getElementById('review-modal').classList.remove('hidden');
    },

    hideReviewModal: () => {
        document.getElementById('review-modal').classList.add('hidden');
    }
};