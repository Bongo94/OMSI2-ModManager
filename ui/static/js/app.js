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