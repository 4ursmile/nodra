// Runs before the first paint: puts the saved theme (light / dark; none = follow the system) on <html data-theme>.
(function () { try { var t = localStorage.getItem("nodra_theme"); if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t); } catch (e) {} })();
