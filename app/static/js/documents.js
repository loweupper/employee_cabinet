// ===================================
// documents.js - AJAX-функции для работы с документами
//
// Зависимости:
//   - getCsrfToken()       определена в employee.js (загружается через sidebar.html ДО этого скрипта)
//   - subcategoriesData    определена в employee.js
//   - openEditDocumentModal() переопределяется в этом файле (добавляет поддержку версионирования)
// ===================================

// ===================================
// Создание подкатегории через AJAX
// (Модалка остаётся открытой для загрузки файлов)
// ===================================

async function createSubcategoryViaAjax(e) {
    e.preventDefault();

    const nameInput = document.getElementById('subcategoryName');
    const categoryInput = document.getElementById('subcatCategory');

    if (!nameInput || !categoryInput) {
        console.error('Поля формы не найдены');
        return;
    }

    const name = nameInput.value.trim();
    const category = categoryInput.value;
    const objectId = window.location.pathname.split('/').pop();

    if (!name) {
        alert('Введите имя подкатегории');
        return;
    }

    if (!category) {
        alert('Сначала выберите раздел в форме загрузки');
        return;
    }

    try {
        const response = await fetch(`/objects/${objectId}/subcategories/create`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ name, category })
        });

        if (response.ok) {
            const data = await response.json();

            // ✅ Добавляем в dropdown формы загрузки
            const select = document.getElementById('uploadSubcategory');
            if (select) {
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                select.appendChild(option);
                select.value = data.id;
            }

            // ✅ Обновляем локальные данные подкатегорий (для работы фильтров)
            if (typeof subcategoriesData !== 'undefined' && subcategoriesData[category]) {
                subcategoriesData[category].push({ id: data.id, name: data.name });
            }

            // ✅ Очищаем форму
            nameInput.value = '';

            // ✅ Закрываем модалку создания подкатегории
            const modal = document.getElementById('createSubcategoryModal');
            if (modal) {
                modal.classList.add('hidden');
            }

            // ✅ Показываем уведомление об успехе
            showNotification('✅ Подкатегория создана!', 'success');
        } else {
            const error = await response.json();
            alert('Ошибка: ' + (error.detail || 'Неизвестная ошибка'));
        }
    } catch (err) {
        console.error('Ошибка создания подкатегории:', err);
        alert('Ошибка при создании подкатегории');
    }
}

// ===================================
// Массовое удаление документов
// ===================================

function openBatchDeleteModal() {
    const checkboxes = document.querySelectorAll('.document-checkbox:checked');

    if (checkboxes.length === 0) {
        alert('Выберите документы для удаления');
        return;
    }

    // Заполняем счётчик и список
    document.getElementById('batchDeleteCount').textContent = checkboxes.length;

    const listEl = document.getElementById('batchDeleteList');
    if (listEl) {
        listEl.innerHTML = Array.from(checkboxes).map(cb => {
            const item = cb.closest('.document-item');
            const title = item ? item.querySelector('.font-medium')?.textContent?.trim() : `Документ #${cb.dataset.docId}`;
            return `<div class="text-sm text-gray-700 px-2 py-1 bg-red-50 rounded">🗑️ ${title}</div>`;
        }).join('');
    }

    document.getElementById('batchDeleteModal').classList.remove('hidden');
}

async function confirmBatchDelete() {
    const selected = Array.from(
        document.querySelectorAll('.document-checkbox:checked')
    ).map(cb => parseInt(cb.dataset.docId));

    if (selected.length === 0) {
        return;
    }

    document.getElementById('batchDeleteModal').classList.add('hidden');

    try {
        const response = await fetch('/documents/batch-delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ document_ids: selected })
        });

        if (response.ok) {
            const data = await response.json();
            showNotification(`✅ Удалено ${data.deleted} файл(ов)!`, 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            const error = await response.json();
            alert('Ошибка при удалении файлов: ' + (error.detail || 'Неизвестная ошибка'));
        }
    } catch (err) {
        console.error('Ошибка удаления:', err);
        alert('Ошибка при удалении файлов');
    }
}

// ===================================
// Обновление файла документа (версионирование)
// ===================================

// Хранит ID текущего редактируемого документа
let currentEditDocumentId = null;

// Переопределяем openEditDocumentModal из employee.js, добавляя поддержку версионирования файлов.
// documents.js загружается ПОСЛЕ employee.js (через sidebar.html), поэтому переопределение корректно.
function openEditDocumentModal(docId, title, category, subcategoryId) {
    currentEditDocumentId = docId;

    // Сбрасываем поле загрузки файла
    const fileInput = document.getElementById('editDocFileInput');
    const fileInputName = document.getElementById('editDocFileInputName');
    const updateBtn = document.getElementById('editDocUpdateFileBtn');
    if (fileInput) fileInput.value = '';
    if (fileInputName) fileInputName.textContent = 'Файл не выбран';
    if (updateBtn) updateBtn.classList.add('hidden');

    const modal = document.getElementById('editDocumentModal');
    const form = document.getElementById('editDocumentForm');

    if (!modal || !form) return;

    const objectId = window.location.pathname.split('/').pop();
    form.action = `/documents/objects/${objectId}/${docId}/update`;

    document.getElementById('editDocTitle').value = title;
    document.getElementById('editDocCategory').value = category;

    // Обновляем подкатегории для выбранной категории
    if (typeof updateEditSubcategories === 'function') {
        updateEditSubcategories();
    }

    // Устанавливаем текущую подкатегорию
    setTimeout(() => {
        if (subcategoryId) {
            document.getElementById('editDocSubcategory').value = subcategoryId;
        }
    }, 100);

    modal.classList.remove('hidden');
}

async function updateDocumentFile() {
    const fileInput = document.getElementById('editDocFileInput');
    if (!fileInput || !fileInput.files.length) {
        alert('Выберите новый файл');
        return;
    }

    if (!currentEditDocumentId) {
        alert('Документ не выбран');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    const btn = document.getElementById('editDocUpdateFileBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Загрузка...';
    }

    try {
        const response = await fetch(`/documents/${currentEditDocumentId}/update`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken()
            },
            body: formData
        });

        if (response.ok) {
            const data = await response.json();
            showNotification(`✅ Файл обновлён (версия ${data.version})`, 'success');

            // Закрываем модалку и перезагружаем страницу
            const modal = document.getElementById('editDocumentModal');
            if (modal) modal.classList.add('hidden');
            setTimeout(() => location.reload(), 1000);
        } else {
            const error = await response.json();
            alert('Ошибка при обновлении файла: ' + (error.detail || 'Неизвестная ошибка'));
        }
    } catch (err) {
        console.error('Ошибка обновления:', err);
        alert('Ошибка при обновлении файла');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '⬆️ Загрузить новую версию';
        }
    }
}

// ===================================
// Показать уведомление (toast)
// ===================================

function showNotification(message, type) {
    const notification = document.createElement('div');
    notification.className = [
        'fixed top-4 right-4 px-6 py-3 rounded-lg text-white z-50 shadow-lg transition-opacity',
        type === 'success' ? 'bg-green-500' : 'bg-blue-500'
    ].join(' ');
    notification.textContent = message;
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// ===================================
// Скачивание нескольких документов (batch download)
// ===================================

async function downloadSelectedDocuments() {
    const selected = Array.from(
        document.querySelectorAll('.document-checkbox:checked')
    ).map(cb => parseInt(cb.dataset.docId));

    if (selected.length === 0) {
        alert('Выберите файлы для скачивания');
        return;
    }

    if (selected.length === 1) {
        // Один файл - обычное скачивание
        window.location.href = `/documents/${selected[0]}/download`;
        return;
    }

    // Несколько файлов - скачиваем архив
    try {
        const response = await fetch('/documents/batch-download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ document_ids: selected })
        });

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'documents.zip';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } else {
            alert('Ошибка при скачивании');
        }
    } catch (err) {
        console.error('Ошибка:', err);
        alert('Ошибка при скачивании файлов');
    }
}

console.log('documents.js загружен');
