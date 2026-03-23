// ===================================
// УПРАВЛЕНИЕ ПОДКАТЕГОРИЯМИ ДОКУМЕНТОВ
// ===================================

let subcategoriesData = {
  general: [],
  technical: [],
  accounting: [],
  safety: [],
  legal: [],
  hr: [],
};

function markSmartImageLoaded(img) {
  img.classList.add("is-loaded");
}

function initSmartImages(root = document) {
  const images = root.querySelectorAll("img[data-smart-image]");
  images.forEach((img) => {
    const onLoad = () => markSmartImageLoaded(img);
    const onError = () => img.classList.add("is-error");

    img.addEventListener("load", onLoad, { once: true });
    img.addEventListener("error", onError, { once: true });

    if (img.complete && img.naturalWidth > 0) {
      markSmartImageLoaded(img);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initSmartImages(document);
});

function initializeSubcategories(data) {
  subcategoriesData = data;
  console.log("Подкатегории инициализированы:", subcategoriesData);
}

function getUploadCategoryElement() {
  return (
    document.getElementById("uploadCategorySelect") ||
    document.getElementById("uploadCategory")
  );
}

function getUploadSubcategoryElement() {
  return (
    document.getElementById("uploadSubcategorySelect") ||
    document.getElementById("uploadSubcategory")
  );
}

function updateSubcategories() {
  const categorySelect = getUploadCategoryElement();
  const subcategorySelect = getUploadSubcategoryElement();
  const subcatCategoryInput = document.getElementById("subcatCategory");
  const subcatCategoryDisplay = document.getElementById(
    "subcatCategoryDisplay",
  );

  if (!categorySelect) {
    console.warn("Селект раздела загрузки не найден");
    return;
  }

  const category = categorySelect.value;

  console.log("Выбранный раздел:", category);

  if (!subcategorySelect) {
    console.warn("Селект подкатегории загрузки не найден");
    return;
  }

  if (subcatCategoryInput) {
    subcatCategoryInput.value = category;
  }

  const categoryNames = {
    general: "📋 Общие",
    technical: "📐 Технические",
    accounting: "💰 Бухгалтерия",
    safety: "👷 Охрана труда",
    legal: "⚖️ Юридические",
    hr: "👔 Кадровые",
  };

  if (subcatCategoryDisplay) {
    subcatCategoryDisplay.textContent =
      categoryNames[category] || "Выберите раздел";
  }

  subcategorySelect.innerHTML = '<option value="">Без подкатегории</option>';

  if (category && subcategoriesData[category]) {
    console.log("Подкатегории для", category, ":", subcategoriesData[category]);
    subcategoriesData[category].forEach((subcat) => {
      const option = document.createElement("option");
      option.value = subcat.id;
      option.textContent = subcat.name;
      subcategorySelect.appendChild(option);
    });
  }
}

function openCreateSubcategoryModal() {
  const categorySelect = getUploadCategoryElement();
  const category = categorySelect ? categorySelect.value : "";
  const modal = document.getElementById("createSubcategoryModal");

  if (!category) {
    alert("Сначала выберите раздел");
    return;
  }

  if (!modal) {
    console.error("createSubcategoryModal не найден");
    return;
  }

  modal.classList.remove("hidden");
}

function closeCreateSubcategoryModal() {
  const modal = document.getElementById("createSubcategoryModal");
  if (modal) {
    modal.classList.add("hidden");
  }
}

// ===================================
// УДАЛЕНИЕ/РЕДАКТИРОВАНИЕ ПОДКАТЕГОРИЙ
// ===================================

function deleteSubcategory(objectId, subcategoryId, subcategoryName) {
  if (
    confirm(
      `Удалить подкатегорию "${subcategoryName}"?\n\nВсе файлы в ней останутся, но будут без подкатегории.`,
    )
  ) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = `/objects/${objectId}/subcategories/${subcategoryId}/delete`;
    const csrfInput = document.createElement("input");
    csrfInput.type = "hidden";
    csrfInput.name = "csrf_token";
    csrfInput.value = getCsrfToken();
    form.appendChild(csrfInput);
    document.body.appendChild(form);
    form.submit();
  }
}

function openEditSubcategoryModal(
  objectId,
  subcategoryId,
  subcategoryName,
  subcategoryDesc,
) {
  const modal = document.getElementById("editSubcategoryModal");
  if (!modal) {
    console.error("editSubcategoryModal не найден");
    return;
  }

  document.getElementById("editSubcategoryForm").action =
    `/objects/${objectId}/subcategories/${subcategoryId}/update`;

  document.getElementById("editSubcatName").value = subcategoryName;
  document.getElementById("editSubcatDesc").value = subcategoryDesc || "";

  modal.classList.remove("hidden");
}

function closeEditSubcategoryModal() {
  const modal = document.getElementById("editSubcategoryModal");
  if (modal) {
    modal.classList.add("hidden");
  }
}

// ===================================
// CSRF TOKEN HELPER
// ===================================

function getCsrfToken() {
  // Способ 1: Из мета-тега (самый надежный)
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) {
    const token = meta.getAttribute("content");
    console.log("✅ CSRF из мета-тега: длина=" + token.length);
    return token;
  }

  // Способ 2: Из cookies
  const cookie = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrftoken="));
  if (cookie) {
    const token = cookie.split("=").slice(1).join("=");
    console.log("✅ CSRF из cookies: длина=" + token.length);
    return token;
  }

  // Способ 3: Из hidden input в форме
  const input = document.querySelector('input[name="csrf_token"]');
  if (input && input.value) {
    console.log("✅ CSRF из input: длина=" + input.value.length);
    return input.value;
  }

  console.warn("❌ CSRF токен не найден! Доступные способы не сработали.");
  return "";
}

// ===================================
// ЗАГРУЗКА ФАЙЛОВ - НЕМЕДЛЕННАЯ
// ===================================

let uploadedFiles = []; // Массив загруженных файлов на сервере

function openUploadModal() {
  console.log("🔓 Открываем модалку загрузки");

  const modal = document.getElementById("uploadDocModal");
  if (!modal) {
    console.error("❌ modal не найден");
    return;
  }

  console.log("✅ modal найден, открываем");

  modal.classList.remove("hidden");
  uploadedFiles = []; // Сбрасываем при открытии
  updateUploadedFilesList();

  setTimeout(() => {
    setupFileUploadHandlers();
  }, 100);
}

function setupFileUploadHandlers() {
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");

  if (!dropZone || !fileInput) {
    console.error("❌ Элементы не найдены");
    return;
  }

  let isDialogOpening = false;

  // КЛИК
  dropZone.onclick = function (e) {
    if (isDialogOpening) return;
    console.log("📂 Клик по зоне загрузки");

    e.preventDefault();
    e.stopPropagation();

    isDialogOpening = true;
    fileInput.click();
    console.log("📂 Открываем диалог выбора файлов");

    setTimeout(() => {
      isDialogOpening = false;
    }, 1000);
  };
  console.log("✅ Клик обработчик установлен");

  // ВЫБОР
  fileInput.addEventListener(
    "change",
    function (e) {
      isDialogOpening = false;
      console.log("📂 Файлы выбраны:", e.target.files.length);
      if (e.target.files.length > 0) {
        uploadFilesImmediately(e.target.files);
      }
    },
    false,
  );

  // DRAG OVER
  dropZone.addEventListener(
    "dragover",
    function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("bg-indigo-100");
    },
    false,
  );

  // DRAG LEAVE
  dropZone.addEventListener(
    "dragleave",
    function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("bg-indigo-100");
    },
    false,
  );

  // DROP
  dropZone.addEventListener(
    "drop",
    function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("bg-indigo-100");
      console.log("📭 Файлы перетащены:", e.dataTransfer.files.length);
      uploadFilesImmediately(e.dataTransfer.files);
    },
    false,
  );

  console.log("✅ Обработчики установлены");
}

// ✅ НЕМЕДЛЕННАЯ ЗАГРУЗКА ФАЙЛОВ
function uploadFilesImmediately(files) {
  // ✅ Предотвращаем двойную отправку
  if (window.uploadInProgress) return;
  window.uploadInProgress = true;

  const categorySelect = getUploadCategoryElement();
  const subcategorySelect = getUploadSubcategoryElement();

  if (!categorySelect) {
    window.uploadInProgress = false;
    alert("Не найден выбор раздела, обновите страницу");
    return;
  }

  const category = categorySelect.value;
  const subcategoryId = subcategorySelect ? subcategorySelect.value : "";

  if (!category) {
    window.uploadInProgress = false;
    alert("Сначала выберите раздел");
    return;
  }

  console.log("📤 Загружаем", files.length, "файл(ов) сразу");

  // Показываем прогресс
  document.getElementById("uploadProgress").classList.remove("hidden");

  const formData = new FormData();
  formData.append("category", category);
  if (subcategoryId) {
    formData.append("subcategory_id", subcategoryId);
    console.log("📂 Категория:", category, "Подкатегория ID:", subcategoryId);
  }

  // Добавляем файлы
  for (let file of files) {
    formData.append("files", file);
    console.log("📎", file.name);
  }

  // Загружаем
  const objectId = window.location.pathname.split("/").pop();
  console.log("📁 Загружаем файлы для объекта ID:", objectId);

  fetch(`/documents/objects/${objectId}/upload`, {
    method: "POST",
    body: formData,
    headers: {
      "X-CSRFToken": getCsrfToken(),
    },
  })
    .then((response) => {
      console.log("📊 Статус:", response.status);

      if (response.ok || response.status === 303) {
        // Добавляем в список загруженных
        for (let file of files) {
          uploadedFiles.push({
            name: file.name,
            size: file.size,
            type: file.type,
          });
        }

        console.log("✅ Файлы загружены успешно");
        updateUploadedFilesList();

        // ✅ Очищаем input
        document.getElementById("fileInput").value = "";
      } else {
        return response.json().then((data) => {
          console.error("❌ Ошибка:", data);
          alert("Ошибка загрузки: " + (data.detail || "Unknown error"));
        });
      }
    })
    .catch((error) => {
      console.error("❌ Ошибка сети:", error);
      alert("Ошибка: " + error.message);
    })
    .finally(() => {
      document.getElementById("uploadProgress").classList.add("hidden");
      // ✅ Разрешаем новую отправку
      window.uploadInProgress = false;
    });
}

// ✅ ОБНОВИТЬ СПИСОК ЗАГРУЖЕННЫХ
function updateUploadedFilesList() {
  const container = document.getElementById("uploadedFilesContainer");
  const list = document.getElementById("uploadedFilesList");

  if (!container || !list) {
    console.warn("uploadedFilesContainer или uploadedFilesList не найден");
    return;
  }

  if (uploadedFiles.length === 0) {
    container.classList.add("hidden");
    list.innerHTML = "";
    return;
  }

  container.classList.remove("hidden");

  list.innerHTML = uploadedFiles
    .map(
      (file, index) => `
        <div class="flex items-center justify-between p-3 bg-white rounded border border-green-200">
            <div class="flex items-start gap-2 flex-1 min-w-0">
                <span class="text-lg">${getFileIcon(file.name)}</span>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-gray-800 break-words">${file.name}</p>
                    <p class="text-xs text-gray-500">${formatFileSize(file.size)}</p>
                </div>
            </div>
            <span class="text-green-600 font-bold ml-2">✅</span>
        </div>
    `,
    )
    .join("");
}

// ✅ ОТКРЫТЬ ДИАЛОГ
function openFileDialog() {
  document.getElementById("fileInput").click();
}

// ✅ ЗАКРЫТЬ МОДАЛКУ
function closeUploadModal() {
  console.log("🔒 Закрываем модалку");
  const modal = document.getElementById("uploadDocModal");
  if (modal) {
    modal.classList.add("hidden");
  }

  // Перезагружаем страницу чтобы показать новые документы
  if (uploadedFiles.length > 0) {
    setTimeout(() => {
      window.location.reload();
    }, 500);
  }
}

function getFileIcon(filename) {
  const ext = filename.split(".").pop().toLowerCase();
  const icons = {
    pdf: "📄",
    doc: "📝",
    docx: "📝",
    xls: "📊",
    xlsx: "📊",
    png: "🖼️",
    jpg: "🖼️",
    jpeg: "🖼️",
  };
  return icons[ext] || "📎";
}

function formatFileSize(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
}

// ===================================
// УПРАВЛЕНИЕ ДОСТУПОМ К ОБЪЕКТАМ
// ===================================

function openEditAccessModal(buttonElement) {
  const userId = buttonElement.getAttribute("data-user-id");
  const currentRole = buttonElement.getAttribute("data-role");
  const dataContainer = document.getElementById("access-data-" + userId);
  let sectionsStr = dataContainer
    ? dataContainer.textContent.trim()
    : '["general"]';

  let currentSections = ["general"];
  try {
    currentSections = JSON.parse(sectionsStr);
  } catch (e) {
    console.error("Ошибка парсинга sections:", e);
    currentSections = ["general"];
  }

  const objectId = window.location.pathname.split("/").pop();
  const form = document.getElementById("editAccessForm");
  if (form) {
    form.action = `/objects/${objectId}/access/${userId}/update`;
  }

  const editRole = document.getElementById("editRole");
  if (editRole) {
    editRole.value = currentRole;
  }

  const checkboxes = document.querySelectorAll(
    '#editAccessModal input[name="sections"]',
  );
  checkboxes.forEach((checkbox) => {
    checkbox.checked = checkbox.value === "general";
  });

  if (Array.isArray(currentSections)) {
    currentSections.forEach((section) => {
      const checkbox = document.getElementById("edit-section-" + section);
      if (checkbox) {
        checkbox.checked = true;
      }
    });
  }

  const modal = document.getElementById("editAccessModal");
  if (modal) {
    modal.classList.remove("hidden");
  }
}

function closeEditAccessModal() {
  const modal = document.getElementById("editAccessModal");
  if (modal) {
    modal.classList.add("hidden");
  }
}

function showAccessTab(tab) {
  document.querySelectorAll(".access-form").forEach((form) => {
    form.classList.add("hidden");
  });

  const form = document.getElementById("form-" + tab);
  if (form) {
    form.classList.remove("hidden");
  }

  document.querySelectorAll('[id^="tab-"]').forEach((button) => {
    button.classList.remove("border-indigo-600", "text-indigo-600");
    button.classList.add("border-transparent", "text-gray-600");
  });

  const activeTab = document.getElementById("tab-" + tab);
  if (activeTab) {
    activeTab.classList.add("border-indigo-600", "text-indigo-600");
    activeTab.classList.remove("border-transparent", "text-gray-600");
  }
}

// ===================================
// ФИЛЬТРАЦИЯ ДОКУМЕНТОВ ПО КАТЕГОРИЯМ
// ===================================

function showCategory(category) {
  document.querySelectorAll(".category-tab").forEach((tab) => {
    if (tab.dataset.category === category) {
      tab.classList.remove("bg-gray-200", "text-gray-700");
      tab.classList.add("bg-indigo-600", "text-white");
    } else {
      tab.classList.remove("bg-indigo-600", "text-white");
      tab.classList.add("bg-gray-200", "text-gray-700");
    }
  });

  document.querySelectorAll(".document-item").forEach((item) => {
    if (category === "all" || item.dataset.category === category) {
      item.style.display = "flex";
    } else {
      item.style.display = "none";
    }
  });
}

// ===================================
// ИНИЦИАЛИЗАЦИЯ ПРИ ЗАГРУЗКЕ СТРАНИЦЫ
// ===================================

document.addEventListener("DOMContentLoaded", function () {
  console.log("✅ Страница загружена");
});

// ===================================
// Аккордеон подкатегорий
// ===================================
function toggleSubcategoryAccordion(subcategoryId) {
  const content = document.getElementById(
    `subcategory-content-${subcategoryId}`,
  );
  const toggle = document.getElementById(`subcategory-toggle-${subcategoryId}`);

  if (content.style.display === "none") {
    content.style.display = "block";
    toggle.textContent = "▼";
  } else {
    content.style.display = "none";
    toggle.textContent = "▶";
  }

  console.log(`Тоггл подкатегории ${subcategoryId}:`, content.style.display);
}

// ===================================
// Инициализация: свернуть все подкатегории при загрузке
// ===================================
document.addEventListener("DOMContentLoaded", function () {
  // Находим все контейнеры подкатегорий
  const subcategoryContents = document.querySelectorAll(
    '[id^="subcategory-content-"]',
  );

  subcategoryContents.forEach((content) => {
    // Сворачиваем
    content.style.display = "none";

    // Меняем иконку на ▶
    const subcatId = content.id.replace("subcategory-content-", "");
    const toggle = document.getElementById(`subcategory-toggle-${subcatId}`);
    if (toggle) {
      toggle.textContent = "▶";
    }
  });

  console.log("✅ Все подкатегории свернуты при загрузке");
});

// ===================================
// Фильтрация по категориям (табы)
// ===================================
function showCategory(category) {
  const sections = document.querySelectorAll(".category-section");
  const tabs = document.querySelectorAll(".category-tab");

  // Показываем/скрываем секции
  sections.forEach((section) => {
    if (category === "all" || section.dataset.category === category) {
      section.style.display = "block";
    } else {
      section.style.display = "none";
    }
  });

  // Обновляем активный таб
  tabs.forEach((tab) => {
    if (tab.dataset.category === category) {
      tab.classList.remove("bg-gray-200", "text-gray-700");
      tab.classList.add("bg-indigo-600", "text-white");
    } else {
      tab.classList.remove("bg-indigo-600", "text-white");
      tab.classList.add("bg-gray-200", "text-gray-700");
    }
  });
}

// ===================================
// РЕДАКТИРОВАНИЕ ДОКУМЕНТА
// ===================================

function openEditDocumentModal(docId, title, category, subcategoryId) {
  const modal = document.getElementById("editDocumentModal");
  const form = document.getElementById("editDocumentForm");

  if (!modal || !form) return;

  const objectId = window.location.pathname.split("/").pop();
  form.action = `/documents/objects/${objectId}/${docId}/update`;

  document.getElementById("editDocTitle").value = title;
  document.getElementById("editDocCategory").value = category;

  // Обновляем подкатегории для выбранной категории
  updateEditSubcategories();
  console.log("🔄 Обновлены подкатегории для редактирования документа");

  // Устанавливаем текущую подкатегорию
  setTimeout(() => {
    if (subcategoryId) {
      document.getElementById("editDocSubcategory").value = subcategoryId;
    }
  }, 100);

  modal.classList.remove("hidden");
}

function closeEditDocumentModal() {
  const modal = document.getElementById("editDocumentModal");
  if (modal) {
    modal.classList.add("hidden");
  }
}

function updateEditSubcategories() {
  const category = document.getElementById("editDocCategory").value;
  const subcategorySelect = document.getElementById("editDocSubcategory");

  if (!subcategorySelect) return;

  subcategorySelect.innerHTML = '<option value="">Без подкатегории</option>';

  if (category && subcategoriesData[category]) {
    subcategoriesData[category].forEach((subcat) => {
      const option = document.createElement("option");
      option.value = subcat.id;
      option.textContent = subcat.name;
      subcategorySelect.appendChild(option);
    });
  }
}

// ===================================
// УДАЛЕНИЕ ДОКУМЕНТА
// ===================================

function deleteDocument(objectId, documentId, fileName) {
  if (confirm(`Удалить документ "${fileName}"?`)) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = `/documents/objects/${objectId}/${documentId}/delete`;
    const csrfInput = document.createElement("input");
    csrfInput.type = "hidden";
    csrfInput.name = "csrf_token";
    csrfInput.value = getCsrfToken();
    form.appendChild(csrfInput);
    document.body.appendChild(form);
    form.submit();
  }
}

console.log("employee.js загружен");
