// --- Переменная для текущего языка ---
let currentLang = 'en';

const View = {
    // --- Локализация ---
    setLanguage: (lang) => {
        if (!Locales[lang]) lang = 'en';
        currentLang = lang;

        // 1. Обновляем все data-i18n элементы
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (Locales[lang][key]) {
                el.innerText = Locales[lang][key];
            }
        });

        // 2. Обновляем плейсхолдеры
        document.querySelectorAll('input[placeholder]').forEach(el => {
            // Простая проверка, можно улучшить data-i18n-placeholder
            if (el.id.includes('path-input')) el.placeholder = Locales[lang]['ph_select'];
        });

        // 3. Активность кнопок языка
        document.querySelectorAll('.lang-btn').forEach(btn => {
            if (btn.dataset.lang === lang) {
                btn.classList.add('text-[#ff8128]', 'bg-[#222]');
                btn.classList.remove('text-[#888]');
            } else {
                btn.classList.remove('text-[#ff8128]', 'bg-[#222]');
                btn.classList.add('text-[#888]');
            }
        });
    },

    // Вспомогательная функция для получения текста в JS
    t: (key) => {
        return Locales[currentLang][key] || key;
    },
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

        let colorClass = 'text-[#aaa]'; // Default gray
        let prefix = 'INFO';
        let prefixColor = 'text-[#555]';

        if (level === 'error') {
            colorClass = 'text-red-400';
            prefix = 'ERR';
            prefixColor = 'text-red-500 font-bold';
        }
        if (level === 'warning') {
            colorClass = 'text-yellow-400';
            prefix = 'WARN';
            prefixColor = 'text-yellow-500';
        }
        if (level === 'success') {
            colorClass = 'text-green-400';
            prefix = 'OK';
            prefixColor = 'text-green-500';
        }

        // Простой, единый формат для всех сообщений
        line.innerHTML = `
            <div>
                <span class="text-[#444] mr-2 font-mono">[${time}]</span>
                <span class="${prefixColor} w-8 inline-block text-[10px]">${prefix}</span> 
                <span class="${colorClass} whitespace-pre-wrap">${msg}</span>
            </div>
        `;

        container.appendChild(line);
        container.scrollTop = container.scrollHeight;
    },

    // --- Таблица модов (Grid Layout) ---
    renderModList: (mods) => {
        const container = document.getElementById('mod-table-body');
        const emptyState = document.getElementById('empty-state');
        container.innerHTML = '';

        if (!mods || mods.length === 0) {
            emptyState.classList.remove('hidden');
            return;
        }
        emptyState.classList.add('hidden');

        mods.forEach(mod => {
            const row = document.createElement('div');
            row.className = 'grid grid-cols-12 gap-4 items-center p-3 bg-[#1a1a1a] border border-[#333] rounded hover:border-[#555] hover:bg-[#202020] transition group animate-fade-in mb-2';

            // Перевод Типов
            let typeKey = 'type_unknown';
            if (mod.type === 'bus') typeKey = 'type_bus';
            if (mod.type === 'map') typeKey = 'type_map';
            if (mod.type === 'scenery') typeKey = 'type_scenery';

            const typeLabel = View.t(typeKey);

            // Badge Colors
            let typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[#333] text-[#888] border border-[#444]">${typeLabel}</span>`;
            if (mod.type === 'bus') typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[#333] text-[#ff8128] border border-[#ff8128]/30">${typeLabel}</span>`;
            if (mod.type === 'map') typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[#333] text-purple-400 border border-purple-500/30">${typeLabel}</span>`;

            // Status Indicator (Translated)
            let statusHtml = mod.is_enabled
                ? `<div class="flex items-center justify-center gap-2 text-[#22c55e] text-xs font-bold tracking-wider"><div class="w-2 h-2 rounded-full bg-[#22c55e] shadow-[0_0_10px_#22c55e]"></div> ${View.t('status_active')}</div>`
                : `<div class="flex items-center justify-center gap-2 text-[#555] text-xs font-bold tracking-wider"><div class="w-2 h-2 rounded-full bg-[#333]"></div> ${View.t('status_off')}</div>`;

            // ... остальное создание HTML остается прежним ...
            // (Кнопки toggleMod, deleteMod)

            row.innerHTML = `
                <div class="col-span-5 font-medium text-white flex items-center gap-3 pl-2 overflow-hidden">
                    <i class="fas ${mod.type === 'bus' ? 'fa-bus' : mod.type === 'map' ? 'fa-map' : 'fa-box'} text-[#444] group-hover:text-[#ff8128] transition"></i>
                    <span class="truncate">${mod.name}</span>
                </div>
                <div class="col-span-2 text-center">${typeBadge}</div>
                <div class="col-span-2 text-center text-[#666] text-xs font-mono">${mod.date}</div>
                <div class="col-span-2 text-center">${statusHtml}</div>
                <div class="col-span-1 text-right flex justify-end gap-2 pr-2">
                    <button onclick="toggleMod(${mod.id})" class="w-8 h-8 rounded flex items-center justify-center transition ${mod.is_enabled ? 'text-[#22c55e] bg-[#22c55e]/10' : 'text-[#888] hover:text-white bg-[#222]'}" title="Toggle">
                        <i class="fas fa-power-off"></i>
                    </button>
                    <button onclick="deleteMod(${mod.id})" class="w-8 h-8 rounded flex items-center justify-center text-[#555] hover:text-red-500 hover:bg-red-500/10 transition" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
            container.appendChild(row);
        });
    },

    // --- Окно проверки (Review Modal) ---
    showReviewModal: (data) => {
        document.getElementById('review-mod-name').innerText = data.mod_name;
        document.getElementById('review-mod-type').innerText = data.type;

        const mappedContainer = document.getElementById('mapped-rows');
        mappedContainer.innerHTML = '';

        document.getElementById('unmapped-panel').classList.add('hidden');

        // Reset styles for full width
        // const rightPanel = document.getElementById('mapped-list').parentElement;
        // rightPanel.parentElement.classList.remove('md:flex-row'); // remove flex row if needed logic

        let html = '';
        data.mapped_files.forEach(f => {
            let color = 'text-[#aaa]'; // Default source
            let targetColor = 'text-[#22c55e]'; // Green
            let icon = '<i class="fas fa-arrow-right text-[10px] mx-2 opacity-30"></i>';
            let targetText = f.target;

            if (f.status === 'addon') {
                targetColor = 'text-yellow-500'; // Addon dir
            }

            if (f.status === 'hof') {
                targetColor = 'text-[#ff8128] font-bold';
                targetText = '[ HOF LIBRARY ]';
            }

            html += `
            <div class="flex items-center p-2 hover:bg-[#222] border-b border-[#222] text-xs font-mono transition">
                <div class="w-1/2 break-all text-[#666] pl-2">${f.source}</div>
                <div class="w-1/2 break-all ${targetColor} flex items-center">
                   ${icon} ${targetText}
                </div>
            </div>`;
        });

        mappedContainer.innerHTML = html;
        document.getElementById('review-modal').classList.remove('hidden');
    },

    hideReviewModal: () => {
        document.getElementById('review-modal').classList.add('hidden');
    },

    // --- Load Order UI ---
    renderLoadOrder: (mods) => {
        const container = document.getElementById('load-order-list');
        container.innerHTML = '';

        if (!mods || mods.length === 0) {
            container.innerHTML = `
                <div class="text-[#555] text-center mt-10 flex flex-col items-center">
                    <i class="fas fa-check-circle text-4xl mb-2 opacity-20"></i>
                    <span>No file conflicts detected.</span>
                </div>`;
            return;
        }

        const sortedForUI = [...mods].reverse();

        sortedForUI.forEach((mod, index) => {
            const div = document.createElement('div');
            div.className = 'flex items-center justify-between bg-[#111] p-3 mb-1 border border-[#333] rounded group';
            div.dataset.id = mod.id;

            let badge = '';
            let orderNum = `<span class="text-[#444] font-mono mr-3 text-sm w-6">${index + 1}.</span>`;

            if (index === 0 && mods.length > 1) {
                badge = '<span class="text-[10px] bg-[#22c55e]/10 text-[#22c55e] px-2 py-0.5 rounded border border-[#22c55e]/30 ml-2">WINNER</span>';
                orderNum = `<span class="text-[#ff8128] font-bold font-mono mr-3 text-sm w-6">1.</span>`;
            }

            div.innerHTML = `
                <div class="flex items-center">
                    ${orderNum}
                    <span class="text-[#e0e0e0] font-medium">${mod.name}</span>
                    ${badge}
                </div>
                <div class="flex gap-1 opacity-30 group-hover:opacity-100 transition">
                    <button onclick="moveItem(this, -1)" class="w-6 h-6 rounded bg-[#222] hover:bg-[#ff8128] hover:text-black flex items-center justify-center text-[#888]"><i class="fas fa-chevron-up text-[10px]"></i></button>
                    <button onclick="moveItem(this, 1)" class="w-6 h-6 rounded bg-[#222] hover:bg-[#ff8128] hover:text-black flex items-center justify-center text-[#888]"><i class="fas fa-chevron-down text-[10px]"></i></button>
                </div>
            `;
            container.appendChild(div);
        });
    },

    updateProgress: (percent, message) => {
        const bar = document.getElementById('progress-bar');
        const text = document.getElementById('progress-text');

        bar.style.width = `${percent}%`;
        text.innerText = message || `${percent}%`;
    },

    setLoading: (isLoading, title = "PROCESSING") => {
        const el = document.getElementById('loading-modal');
        const titleEl = document.getElementById('loading-title');

        if (isLoading) {
            titleEl.innerText = title;
            View.updateProgress(0, 'Initializing...');
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    },
};