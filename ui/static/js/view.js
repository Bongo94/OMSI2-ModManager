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

    // --- Логи ---
    addLog: (msg, level) => {
        const container = document.getElementById('log-container');
        const line = document.createElement('div');

        const time = new Date().toLocaleTimeString('ru-RU');
        let colorClass = 'text-gray-300';
        let prefix = 'INFO';

        if (level === 'error') {
            colorClass = 'text-red-400 font-bold';
            prefix = 'ERR';
        }
        if (level === 'warning') {
            colorClass = 'text-yellow-400';
            prefix = 'WARN';
        }
        if (level === 'success') {
            colorClass = 'text-green-400';
            prefix = 'OK';
        }

        line.innerHTML = `<span class="text-gray-600 select-none mr-2">[${time}]</span><span class="text-xs font-bold w-8 inline-block opacity-50">${prefix}</span> <span class="${colorClass}">${msg}</span>`;
        container.appendChild(line);
        container.scrollTop = container.scrollHeight;
    },

    // Добавить в объект View
renderLoadOrder: (mods) => {
        const container = document.getElementById('load-order-list');
        container.innerHTML = '';

        if (!mods || mods.length === 0) {
            container.innerHTML = '<div class="text-gray-500 text-center mt-10">Конфликтов не обнаружено.<br>Моды не пересекаются файлами (кроме Fonts).</div>';
            return;
        }

        // mods приходит отсортированный по приоритету базы (0..99).
        // 99 - это победитель. Мы хотим, чтобы Победитель был ВВЕРХУ списка (№1).
        // Значит, сортируем массив: от большего к меньшему, перед отрисовкой.
        // Но `get_conflicts` возвращает order_by(Mod.priority) -> [0, 1, 2...].
        // Значит последний элемент списка API - это победитель.
        // Нам нужно отобразить его первым.

        const sortedForUI = [...mods].reverse();

        sortedForUI.forEach((mod, index) => {
            const div = document.createElement('div');
            // ... (остальной код создания элемента тот же) ...
            // Добавим подпись "Перезаписывает всех ниже" для первого элемента
            let badge = '';
            if (index === 0 && mods.length > 1) {
                badge = '<span class="text-[10px] bg-green-900 text-green-300 px-1 rounded ml-2">ГЛАВНЫЙ</span>';
            }

            div.innerHTML = `
                <div class="flex items-center gap-3">
                    <span class="text-gray-500 font-mono text-xs w-6">${index + 1}.</span>
                    <span class="font-medium text-gray-200">${mod.name}</span>
                    ${badge}
                </div>
                <div class="flex gap-1 opacity-50 group-hover:opacity-100">
                    <button onclick="moveItem(this, -1)" class="p-1 hover:text-white">⬆️</button>
                    <button onclick="moveItem(this, 1)" class="p-1 hover:text-white">⬇️</button>
                </div>
            `;
            container.appendChild(div);
        });
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
                    <!-- ДОБАВЛЕН ONCLICK -->
                    <button onclick="toggleMod(${mod.id})" class="text-gray-400 hover:text-white transition group" title="Включить/Выключить">
                        <span class="group-active:scale-90 inline-block">⏯</span>
                    </button>
                    <button onclick="deleteMod(${mod.id})" class="text-red-400 hover:text-red-300 transition" title="Удалить">🗑</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    },

    // --- Окно проверки (Review Modal) ---
    showReviewModal: (data) => {
        document.getElementById('review-mod-name').innerText = data.mod_name;
        document.getElementById('review-mod-type').innerText = data.type;

        const mappedContainer = document.getElementById('mapped-rows');
        mappedContainer.innerHTML = '';

        // Скрываем левую панель "Ошибок"
        document.getElementById('unmapped-panel').classList.add('hidden');

        // Расширяем правую панель
        const rightPanel = document.getElementById('mapped-list').parentElement;
        rightPanel.classList.remove('md:w-2/3');
        rightPanel.classList.add('w-full');

        let html = '';
        data.mapped_files.forEach(f => {
            let targetClass = 'text-green-400';
            let icon = '→';
            let targetText = f.target;

            // Стилизация для Addons
            if (f.status === 'addon') {
                targetClass = 'text-yellow-500';
                icon = '📂';
            }

            // Стилизация для HOF
            if (f.status === 'hof') {
                targetClass = 'text-purple-400 font-bold';
                icon = '💾';
                targetText = 'БУДЕТ ИЗВЛЕЧЕН В БИБЛИОТЕКУ';
            }

            html += `
            <div class="flex p-2 hover:bg-gray-700/30 border-b border-gray-700/30 text-xs">
                <div class="w-1/2 break-all pr-2 text-gray-400 flex items-center gap-2">
                   ${f.source}
                </div>
                <div class="w-1/2 break-all font-mono ${targetClass}">
                   <span class="mr-1 opacity-50">${icon}</span> ${targetText}
                </div>
            </div>`;
        });

        mappedContainer.innerHTML = html;
        document.getElementById('review-modal').classList.remove('hidden');
    },

    hideReviewModal: () => {
        document.getElementById('review-modal').classList.add('hidden');
    },

    updateProgress: (percent, message) => {
        const bar = document.getElementById('progress-bar');
        const text = document.getElementById('progress-text');

        bar.style.width = `${percent}%`;
        text.innerText = message || `Прогресс: ${percent}%`;
    },

    setLoading: (isLoading, title = "Обработка...") => {
        const el = document.getElementById('loading-modal');
        const titleEl = document.getElementById('loading-title');

        if (isLoading) {
            titleEl.innerText = title;
            View.updateProgress(0, 'Начинаем...'); // Сбрасываем прогресс-бар
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    },
};