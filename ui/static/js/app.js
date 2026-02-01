// Глобальное состояние
let currentPreviewData = null;

// --- EXPOSED FUNCTIONS (Вызываются из Python) ---
// ВАЖНО: Функции должны быть глобальными, чтобы Python мог их вызвать
window.addLog = View.addLog;
window.updateProgress = View.updateProgress;

// --- MAIN INIT ---
window.addEventListener('pywebviewready', async function () {
    View.addLog("Интерфейс инициализирован.", "info");

    // Проверка статуса при запуске
    try {
        const config = await pywebview.api.get_config();

        if (config.game_path && config.library_path) {
            document.getElementById('status-bar').innerText = `Game: ${config.game_path}`;
            View.showMain();
            loadMods();
        } else {
            document.getElementById('status-bar').innerText = 'Требуется настройка';
            View.showSetup();
        }
    } catch (e) {
        console.error(e);
        View.addLog("Ошибка соединения с API: " + e, "error");
    }
});

// --- EVENT LISTENERS ---

// 1. Настройки (Setup)
document.getElementById('btn-browse-game').onclick = async () => {
    const path = await pywebview.api.browse_folder();
    if (path) document.getElementById('game-path-input').value = path;
};

document.getElementById('btn-browse-lib').onclick = async () => {
    const path = await pywebview.api.browse_folder();
    if (path) document.getElementById('lib-path-input').value = path;
};

document.getElementById('btn-save-settings').onclick = async () => {
    const gamePath = document.getElementById('game-path-input').value;
    const libPath = document.getElementById('lib-path-input').value;

    if (!gamePath || !libPath) {
        alert("Пожалуйста, заполните оба поля.");
        return;
    }

    const resGame = await pywebview.api.set_game_path(gamePath);
    const resLib = await pywebview.api.set_library_path(libPath);

    if (resGame[0] && resLib[0]) {
        location.reload(); // Перезагрузка для чистого старта
    } else {
        alert(`Ошибка: ${resGame[1] || resLib[1]}`);
    }
};

// 2. Главный экран (Main)
document.getElementById('btn-refresh').onclick = loadMods;

async function loadMods() {
    View.setLoading(true); // Можно убрать, если запрос быстрый
    const mods = await pywebview.api.get_mods_list();
    View.renderModList(mods);
    View.setLoading(false);
}

// 3. Импорт мода (Import Flow)
document.getElementById('btn-add-mod').onclick = async () => {
    View.setLoading(true, "Выбор архива..."); // Изменяем текст
    const result = await pywebview.api.import_mod_step1();
    View.setLoading(false); // Скрываем после завершения

    if (result) {
        currentPreviewData = result;
        View.showReviewModal(result);
    } else {
        View.addLog("Операция выбора файла отменена.", "warning");
    }
};

// 4. Окно проверки (Review Modal)
document.getElementById('btn-confirm-import').onclick = async () => {
    View.hideReviewModal();
    if (currentPreviewData) {
        View.setLoading(true);
        // ШАГ 2: Финальная установка
        const success = await pywebview.api.import_mod_step2(currentPreviewData);
        View.setLoading(false);

        if (success) {
            currentPreviewData = null;
            loadMods(); // Обновляем таблицу
        }
    }
};

document.getElementById('btn-cancel-import').onclick = async () => {
    View.hideReviewModal();
    if (currentPreviewData) {
        await pywebview.api.cancel_import(currentPreviewData.temp_id);
        View.addLog("Импорт отменен пользователем.", "warning");
        currentPreviewData = null;
    }
};

// --- ACTIONS ---

window.toggleMod = async (modId) => {
    View.setLoading(true, "Применяем изменения...");
    const result = await pywebview.api.toggle_mod(modId);
    View.setLoading(false);

    if (result.status === 'success') {
        loadMods(); // Перезагружаем таблицу
    } else {
        alert("Ошибка: " + result.message);
    }
};

window.deleteMod = async (modId) => {
    if (!confirm("Вы уверены, что хотите удалить этот мод?")) return;

    // Пока заглушка, реализуем удаление позже
    alert("Функция удаления будет добавлена на следующем этапе.");
};


// Обработчик кнопки
document.getElementById('btn-conflicts').onclick = async () => {
    const mods = await pywebview.api.get_conflicts(); // Возвращает список enabled
    View.renderLoadOrder(mods);
    document.getElementById('load-order-modal').classList.remove('hidden');
};

// Функция перемещения (простая реализация без Drag&Drop библиотек)
window.moveItem = (btn, direction) => {
    const item = btn.closest('div[data-id]');
    const container = document.getElementById('load-order-list');

    if (direction === -1) { // Вверх
        if (item.previousElementSibling) {
            container.insertBefore(item, item.previousElementSibling);
        }
    } else { // Вниз
        if (item.nextElementSibling) {
            container.insertBefore(item.nextElementSibling, item);
        } else {
            // Если последний, но нужно вниз (невозможно), но insertBefore null ставит в конец
            // container.appendChild(item);
        }
    }
    // Пересчитать цифры
    Array.from(container.children).forEach((child, i) => {
        child.querySelector('span').innerText = `${i + 1}.`;
    });
};

document.getElementById('btn-save-order').onclick = async () => {
    const container = document.getElementById('load-order-list');

    // Мы договорились: ВЕРХНИЙ (№1) в UI = ПОБЕДИТЕЛЬ (Highest Priority).
    // База данных работает так: Больше число Priority = Победитель.

    // Значит, список из UI [ModA, ModB, ModC] (где А сверху/главный)
    // Должен превратиться в приоритеты: A=3, B=2, C=1.

    // Собираем ID сверху вниз: [IdA, IdB, IdC]
    const uiIds = Array.from(container.children).map(el => parseInt(el.dataset.id));

    // Чтобы A получил максимальный индекс при переборе enumerate(),
    // массив должен быть [IdC, IdB, IdA].
    const logicIds = uiIds.reverse();

    View.setLoading(true, "Синхронизация файлов...");

    // Отправляем на сервер
    const res = await pywebview.api.save_load_order(logicIds);

    View.setLoading(false);

    if (res.status === 'success') {
        document.getElementById('load-order-modal').classList.add('hidden');
        View.addLog(`Порядок обновлен. Результат: ${res.message}`, "success");
        // Обновим таблицу, вдруг статусы поменялись
        loadMods();
    } else {
        alert("Ошибка: " + res.message);
    }
};

// --- HOF MANAGER ---

let foundHofsCache = []; // Для хранения результата сканирования

document.getElementById('btn-hof-manager').onclick = async () => {
    View.setLoading(true, "Загрузка списка автобусов...");
    const data = await pywebview.api.get_hof_data();
    View.setLoading(false);

    renderHofManager(data);
    document.getElementById('hof-modal').classList.remove('hidden');
};

function renderHofManager(data) {
    // 1. Рендер HOF файлов (без изменений)
    const hofContainer = document.getElementById('hof-list-container');
    hofContainer.innerHTML = '';
    document.getElementById('hof-count').innerText = `${data.library_hofs.length} шт.`;

    data.library_hofs.forEach(hof => {
        const div = document.createElement('label');
        div.className = 'flex items-start gap-2 p-2 hover:bg-gray-700 rounded cursor-pointer select-none';
        div.innerHTML = `
            <input type="checkbox" class="mt-1 accent-purple-500 hof-checkbox" value="${hof.id}">
            <div>
                <div class="font-bold text-sm text-purple-100">${hof.name}</div>
                <div class="text-[10px] text-gray-500 line-clamp-1">${hof.desc || 'Нет описания'}</div>
            </div>
        `;
        hofContainer.appendChild(div);
    });

    // 2. Рендер Автобусов (ОБНОВЛЕНО)
    const busContainer = document.getElementById('bus-list-container');
    busContainer.innerHTML = '';

    if (data.buses.length === 0) {
        busContainer.innerHTML = '<div class="text-xs text-gray-500 text-center p-4">Автобусов с [friendlyname] не найдено</div>';
    }

    data.buses.forEach(bus => {
        // bus теперь объект: { folder: "MAN_SD200", name: "MAN SD200" }
        const div = document.createElement('label');
        div.className = 'flex items-center gap-2 p-2 hover:bg-gray-700 rounded cursor-pointer select-none border-b border-gray-800';
        div.innerHTML = `
            <!-- value хранит имя папки для копирования -->
            <input type="checkbox" class="accent-blue-500 bus-checkbox" value="${bus.folder}">
            <div class="overflow-hidden">
                <div class="text-sm font-bold text-gray-200 truncate">${bus.name}</div>
                <div class="text-[10px] font-mono text-gray-500 truncate">📁 ${bus.folder}</div>
            </div>
        `;
        busContainer.appendChild(div);
    });

    setupFilter('hof-search', 'hof-checkbox');
    setupFilter('bus-search', 'bus-checkbox');
}

function setupFilter(inputId, checkboxClass) {
    document.getElementById(inputId).oninput = (e) => {
        const val = e.target.value.toLowerCase();
        const checks = document.querySelectorAll(`.${checkboxClass}`);
        checks.forEach(chk => {
            const text = chk.parentElement.innerText.toLowerCase();
            chk.parentElement.classList.toggle('hidden', !text.includes(val));
        });
    };
}

// Выбрать все автобусы
document.getElementById('btn-select-all-buses').onclick = () => {
    const checks = document.querySelectorAll('.bus-checkbox');
    const allChecked = Array.from(checks).every(c => c.checked);
    checks.forEach(c => {
        if (!c.parentElement.classList.contains('hidden')) c.checked = !allChecked;
    });
};

// Кнопка Установить
document.getElementById('btn-install-hofs').onclick = async () => {
    const hofIds = Array.from(document.querySelectorAll('.hof-checkbox:checked')).map(c => parseInt(c.value));
    const busNames = Array.from(document.querySelectorAll('.bus-checkbox:checked')).map(c => c.value);

    if (hofIds.length === 0 || busNames.length === 0) {
        alert("Выберите хотя бы один HOF файл и один автобус.");
        return;
    }

    if (!confirm(`Вы собираетесь скопировать ${hofIds.length} HOF файлов в ${busNames.length} автобусов.\nПродолжить?`)) return;

    View.setLoading(true, "Копирование файлов...");
    const res = await pywebview.api.install_hofs(hofIds, busNames);
    View.setLoading(false);

    if (res.status === 'success') {
        View.addLog(res.message, 'success');
        document.getElementById('hof-modal').classList.add('hidden');
    } else {
        alert(res.message);
    }
};

// Сканирование из игры
document.getElementById('btn-scan-game-hof').onclick = async () => {
    View.setLoading(true, "Поиск HOF файлов в Vehicles...");
    const newHofs = await pywebview.api.scan_game_hofs();
    View.setLoading(false);

    if (newHofs.length === 0) {
        alert("Новых HOF файлов не найдено (или все уже есть в библиотеке).");
        return;
    }

    foundHofsCache = newHofs;
    document.getElementById('found-hof-count').innerText = newHofs.length;

    const list = document.getElementById('found-hof-list');
    list.innerHTML = newHofs.map(h => `<div>${h.name} <span class="text-gray-500 text-[10px]">(${h.path})</span></div>`).join('');

    document.getElementById('hof-import-modal').classList.remove('hidden');
};

document.getElementById('btn-confirm-hof-import').onclick = async () => {
    document.getElementById('hof-import-modal').classList.add('hidden');
    View.setLoading(true, "Импорт...");
    const res = await pywebview.api.import_game_hofs(foundHofsCache);
    View.setLoading(false);

    View.addLog(res.message, 'success');

    // Обновляем список HOF в окне
    const data = await pywebview.api.get_hof_data();
    renderHofManager(data);
};