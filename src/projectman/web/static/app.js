/* ProjectMan Web — app initialization */

// ─── Theme Toggle ──────────────────────────────────────
(function initTheme() {
  var saved = localStorage.getItem("pm-theme");
  if (saved) {
    document.documentElement.setAttribute("data-theme", saved);
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
  updateThemeIcon();
})();

function updateThemeIcon() {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  var isDark = document.documentElement.getAttribute("data-theme") === "dark";
  btn.innerHTML = isDark ? "&#9788;" : "&#9790;";
  btn.title = isDark ? "Switch to light mode" : "Switch to dark mode";
}

function toggleTheme() {
  var current = document.documentElement.getAttribute("data-theme");
  var next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("pm-theme", next);
  updateThemeIcon();
}

// Re-set icon after DOM ready (in case script runs before element exists)
document.addEventListener("DOMContentLoaded", updateThemeIcon);

// Toast notification helper
function showToast(message, type) {
  type = type || "success";
  var container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  var toast = document.createElement("div");
  toast.className = "toast toast-" + type;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(function () {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s";
    setTimeout(function () { toast.remove(); }, 300);
  }, 3000);
}

// Listen for HTMX events and show toast on success
document.addEventListener("htmx:afterRequest", function (evt) {
  var trigger = evt.detail.xhr
    ? evt.detail.xhr.getResponseHeader("HX-Trigger")
    : null;
  if (trigger) {
    try {
      var data = JSON.parse(trigger);
      if (data.showToast) {
        showToast(data.showToast.message, data.showToast.type);
      }
    } catch (e) {
      // not JSON, ignore
    }
  }
});

// Show error toast on HTMX errors
document.addEventListener("htmx:responseError", function (evt) {
  showToast("Request failed: " + evt.detail.xhr.status, "error");
});

// Hub mode: project switcher
(function() {
  fetch("/api/config")
    .then(function(r) { return r.json(); })
    .then(function(cfg) {
      var brand = document.querySelector(".pm-brand strong");
      if (brand) brand.textContent = cfg.name || "ProjectMan";

      if (cfg.hub && cfg.projects && cfg.projects.length > 0) {
        var switcher = document.createElement("li");
        var sel = document.createElement("select");
        sel.style.cssText = "margin:0;padding:0.25rem;height:auto;min-width:120px;";
        sel.innerHTML = '<option value="">Hub (all)</option>';
        cfg.projects.forEach(function(p) {
          sel.innerHTML += '<option value="' + p + '">' + p + '</option>';
        });
        var params = new URLSearchParams(window.location.search);
        sel.value = params.get("project") || "";
        sel.addEventListener("change", function() {
          var url = new URL(window.location);
          if (this.value) {
            url.searchParams.set("project", this.value);
          } else {
            url.searchParams.delete("project");
          }
          window.location = url;
        });
        switcher.appendChild(sel);
        var brandUl = document.querySelector("nav ul:first-child");
        brandUl.appendChild(switcher);
      }
    })
    .catch(function() { /* non-critical */ });
})();
