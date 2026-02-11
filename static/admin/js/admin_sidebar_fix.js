document.addEventListener("DOMContentLoaded", function() {
    const sidebar = document.getElementById('nav-sidebar');
    if (!sidebar) return;

    // Восстанавливаем позицию при загрузке
    const scrollPos = sessionStorage.getItem('sidebarScroll');
    if (scrollPos) {
        sidebar.scrollTop = scrollPos;
    }

    // Сохраняем позицию при кликах или перед выгрузкой страницы
    window.addEventListener("beforeunload", function() {
        sessionStorage.setItem('sidebarScroll', sidebar.scrollTop);
    });
});