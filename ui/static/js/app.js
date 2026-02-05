// Глобальное состояние
let currentPreviewData = null;

// --- EXPOSED FUNCTIONS (Вызываются из Python) ---
// ВАЖНО: Функции должны быть глобальными, чтобы Python мог их вызвать
window.addLog = View.addLog;
window.updateProgress = View.updateProgress;

// --- Global Language Switcher ---
window.changeLang = async (lang) => {
    // 1. Обновляем UI
    View.setLanguage(lang);

    // 2. Сохраняем в Python
    try {
        await pywebview.api.set_language(lang);
    } catch (e) {
        console.error("Failed to save lang", e);
    }

    // 3. Если мы на главном экране, перерисовываем список,
    // чтобы обновились переводы внутри таблицы (Тип, Статус)
    const list = document.getElementById('mod-table-body');
    if (list.innerHTML !== "") {
        loadMods();
    }
};

// --- LOG MANAGEMENT FUNCTIONS ---
window.copyAllLogs = () => {
    const logContainer = document.getElementById('log-container');
    const textToCopy = logContainer.innerText;

    navigator.clipboard.writeText(textToCopy)
        .then(() => alert('Log copied to clipboard!'))
        .catch(err => alert('Failed to copy log: ' + err));
};

window.saveLogsToFile = () => {
    const logContainer = document.getElementById('log-container');
    const textToSave = logContainer.innerText;

    // Создаем невидимый элемент для скачивания
    const blob = new Blob([textToSave], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);

    // Формируем имя файла с датой и временем
    const now = new Date();
    const timestamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}-${String(now.getMinutes()).padStart(2, '0')}`;
    a.download = `omsi-manager-log_${timestamp}.txt`;

    // Симулируем клик для скачивания
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
};

// --- INIT ---
window.addEventListener('pywebviewready', async function () {
    try {
        const config = await pywebview.api.get_config();

        // Устанавливаем язык из конфига (или дефолт)
        if (config.language) {
            View.setLanguage(config.language);
        } else {
            View.setLanguage('en');
        }

        if (config.game_path && config.library_path) {
            document.getElementById('status-bar').innerText = config.game_path;
            document.getElementById('status-bar').title = config.game_path;
            View.showMain();
            loadMods();
        } else {
            View.showSetup();
        }
    } catch (e) {
        console.error(e);
        View.addLog("API Error: " + e, "error");
    }
});

// НОВАЯ ФУНКЦИЯ ДЛЯ КНОПКИ
document.getElementById('btn-change-game').onclick = async () => {
    // Блокируем интерфейс
    View.setLoading(true, "Смена профиля игры...");

    const res = await pywebview.api.switch_game_folder();

    View.setLoading(false);

    if (res.status === 'success') {
        // Обновляем UI
        document.getElementById('status-bar').innerText = res.new_path;
        document.getElementById('status-bar').title = res.new_path;
        View.addLog(res.message, "success");

        // Перезагружаем таблицу модов (они уже имеют новые статусы is_enabled из базы)
        loadMods();
    } else if (res.status === 'error') {
        alert(res.message);
    }
};

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
    try {
        View.setLoading(true, "Загрузка списка автобусов...");
        // Вызов Python
        const data = await pywebview.api.get_hof_data();
        View.setLoading(false);

        // Отрисовка
        renderHofManager(data);

        // Показ окна
        document.getElementById('hof-modal').classList.remove('hidden');
    } catch (error) {
        View.setLoading(false);
        console.error(error);
        alert("Ошибка при открытии HOF менеджера:\n" + error);
        View.addLog("Error opening HOF manager: " + error, "error");
    }
};

function renderHofManager(data) {
    // 1. Рендер HOF файлов
    const hofContainer = document.getElementById('hof-list-container');
    hofContainer.innerHTML = '';
    document.getElementById('hof-count').innerText = `${data.library_hofs.length} шт.`;

    data.library_hofs.forEach(hof => {
        const div = document.createElement('label');
        div.className = 'flex items-start gap-2 p-2 hover:bg-gray-700 rounded cursor-pointer select-none border-b border-gray-800/50';

        div.innerHTML = `
            <input type="checkbox" class="mt-1 accent-purple-500 hof-checkbox" value="${hof.id}">
            <div class="flex-1 overflow-hidden">
                <div class="flex justify-between items-center">
                    <div class="font-bold text-sm text-purple-100 truncate">${hof.name}</div>
                    <!-- ИСТОЧНИК -->
                    <div class="text-[9px] px-1.5 py-0.5 bg-gray-900 text-gray-500 rounded border border-gray-700 uppercase tracking-tighter">
                        ${hof.mod_name}
                    </div>
                </div>
                <div class="text-[10px] text-gray-500 line-clamp-1 italic">
                    ${hof.desc || 'Нет описания'}
                </div>
            </div>
        `;
        hofContainer.appendChild(div);
    });

    // 2. Рендер Автобусов
    const busContainer = document.getElementById('bus-list-container');
    busContainer.innerHTML = '';

    if (data.buses.length === 0) {
        busContainer.innerHTML = '<div class="text-xs text-gray-500 text-center p-4">Управляемых автобусов не найдено</div>';
    }

    data.buses.forEach(bus => {
        const div = document.createElement('label');
        div.className = 'flex items-center gap-2 p-2 hover:bg-gray-700 rounded cursor-pointer select-none border-b border-gray-800';

        // Выбираем иконку
        let icon = '🚌';
        let typeClass = 'text-blue-400';

        if (bus.type === 'car') {
            icon = '🚗';
            typeClass = 'text-green-400';
        }

        div.innerHTML = `
            <input type="checkbox" class="accent-blue-500 bus-checkbox" value="${bus.folder}">
            <div class="overflow-hidden w-full">
                <div class="flex justify-between">
                    <div class="text-sm font-bold text-gray-200 truncate pr-2">${bus.name}</div>
                    <div class="${typeClass} opacity-80" title="${bus.type}">${icon}</div>
                </div>
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

window.deleteMod = async (modId) => {
    if (!confirm("ВНИМАНИЕ! Вы собираетесь полностью удалить этот мод.\n\nЭто действие:\n1. Уберет файлы мода из игры.\n2. Удалит архив и файлы из Библиотеки.\n\nПродолжить?")) return;

    View.setLoading(true, "Удаление мода (это может занять время)...");

    // Вызов нового метода API
    const result = await pywebview.api.delete_mod(modId);

    View.setLoading(false);

    if (result.status === 'success') {
        View.addLog(result.message, 'success');
        loadMods(); // Перезагружаем таблицу, чтобы строка исчезла
    } else {
        alert("Ошибка при удалении: " + result.message);
        View.addLog("Ошибка удаления: " + result.message, 'error');
    }
};

document.getElementById('btn-uninstall-hofs').onclick = async () => {
    if (!confirm("Вы уверены?\nЭто удалит все HOF файлы, добавленные через менеджер, и восстановит оригинальные файлы (если они были).")) {
        return;
    }

    View.setLoading(true, "Восстановление оригинальных HOF...");

    const res = await pywebview.api.uninstall_all_hofs();

    View.setLoading(false);

    if (res.status === 'success') {
        View.addLog(res.message, 'success');
        // Можно закрыть окно или обновить список, но особо обновлять нечего
    } else {
        alert(res.message);
    }
};

// --- НОВАЯ ФУНКЦИЯ КОПИРОВАНИЯ ---
window.copyLog = (button) => {
    // Находим текст ошибки рядом с кнопкой
    const errorContainer = button.previousElementSibling;
    const errorText = errorContainer.querySelector('.text-red-300').innerText;

    navigator.clipboard.writeText(errorText)
        .then(() => {
            // Даем обратную связь пользователю
            const originalText = button.innerText;
            button.innerText = 'Copied!';
            button.disabled = true;
            setTimeout(() => {
                button.innerText = originalText;
                button.disabled = false;
            }, 1500); // Возвращаем текст "Copy" через 1.5 секунды
        })
        .catch(err => console.error('Failed to copy log:', err));
};