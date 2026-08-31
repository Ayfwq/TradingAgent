/* 首页模块切换器：股票分析 / AI 资讯在同一页面切换。
 *
 * 点「AI 资讯」时惰性加载 /news 页面主体（fetch + DOMParser 提取），
 * 注入容器后按需挂载 news.css 与 news.js。/news 独立地址仍可直接访问。
 */
(function () {
  "use strict";

  // 股票模块的 section：切换时整体隐藏/恢复（process/report 恢复为默认隐藏）
  var STOCK_SECTIONS = ["module-hub", "hero", "history-center", "process", "report"];
  var DEFAULT_VISIBLE = { "module-hub": true, hero: true, "history-center": true, process: false, report: false };

  var loaded = false;
  var loading = false;

  function $(id) { return document.getElementById(id); }

  function setMode(mode, push) {
    var root = $("news-module-root");
    var trigger = $("news-tab-trigger");
    if (mode === "news") {
      document.body.classList.add("news-mode");
      STOCK_SECTIONS.forEach(function (id) { $(id).classList.add("hidden"); });
      root.classList.remove("hidden");
      trigger.classList.add("active");
      trigger.setAttribute("aria-pressed", "true");
      ensureLoaded();
    } else {
      document.body.classList.remove("news-mode");
      STOCK_SECTIONS.forEach(function (id) {
        $(id).classList.toggle("hidden", !DEFAULT_VISIBLE[id]);
      });
      root.classList.add("hidden");
      trigger.classList.remove("active");
      trigger.setAttribute("aria-pressed", "false");
    }
    if (push) {
      history.pushState({ mode: mode }, "", mode === "news" ? "/news" : "/");
    }
  }

  function ensureLoaded() {
    if (loaded || loading) return;
    loading = true;
    fetch("/news", { headers: { Accept: "text/html" } })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.text();
      })
      .then(function (html) {
        var root = $("news-module-root");
        var doc = new DOMParser().parseFromString(html, "text/html");
        var mainEl = doc.querySelector("main");
        if (!mainEl) throw new Error("页面结构异常");

        // news.js 需要 topbar 里的状态指示灯 ID；首页已有自己的，放一个隐藏占位
        var pill = document.createElement("span");
        pill.id = "news-status-pill";
        pill.className = "status-pill hidden";
        root.appendChild(pill);

        Array.prototype.forEach.call(mainEl.children, function (node) {
          // 复制 main 下全部子节点（含 news-sources-entry 等非 section 元素），
          // news.js 的 init() 需要 news-sources-toggle 等全部元素存在，缺一个就会中断
          root.appendChild(document.importNode(node, true));
        });

        if (!document.querySelector('link[href*="news.css"]')) {
          var link = document.createElement("link");
          link.rel = "stylesheet";
          link.href = "/static/news.css?v=7";
          document.head.appendChild(link);
        }
        var script = document.createElement("script");
        script.src = "/static/news.js?v=7";
        document.body.appendChild(script);
        loaded = true;
      })
      .catch(function () {
        loading = false;
        $("news-module-root").innerHTML =
          '<div class="news-empty"><strong>资讯模块加载失败</strong><p>请刷新页面重试，或直接访问 <a href="/news">独立资讯页</a>。</p></div>';
      });
  }

  function init() {
    var trigger = $("news-tab-trigger");
    trigger.addEventListener("click", function () {
      var inNews = document.body.classList.contains("news-mode");
      setMode(inNews ? "stock" : "news", true);
    });

    // news 模式下点品牌图标回到股票模块（同一页面内，不整页刷新）
    var brand = document.querySelector(".brand");
    brand.addEventListener("click", function (event) {
      if (document.body.classList.contains("news-mode") && location.pathname === "/news") {
        event.preventDefault();
        setMode("stock", true);
      }
    });

    window.addEventListener("popstate", function () {
      setMode(location.pathname === "/news" ? "news" : "stock", false);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
