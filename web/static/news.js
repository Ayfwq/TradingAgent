/* AI 资讯日报：按准确日期回溯，精选单独展示；所有外部内容使用 textContent 渲染。 */
(function () {
  "use strict";

  var state = {
    view: "digest",
    digestDay: null,
    digestPayload: null,
    digestCategory: "",
    digestQuery: "",
    featuredCategory: "",
    featuredQuery: "",
    featuredItems: [],
    categories: [],
    loading: false,
  };

  var REFRESH_MS = 60000;
  var CATEGORY_COLORS = {
    model_tech: "#81f0bd",
    product_open_source: "#c9ff7f",
    chips_compute: "#ffd479",
    company_capital: "#8ab8ff",
    policy_security: "#ff8b83",
    other: "#91a89e",
  };
  var CATEGORY_ORDER = ["model_tech", "product_open_source", "chips_compute", "company_capital", "policy_security", "other"];
  var CATEGORY_LABELS = {
    model_tech: "模型与技术",
    product_open_source: "产品与开源",
    chips_compute: "芯片与算力",
    company_capital: "公司与资本",
    policy_security: "政策与安全",
    other: "其他",
  };

  var els = {};
  var dateFormatter = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "long",
  });
  var timeFormatter = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  function $(id) { return document.getElementById(id); }

  function fetchJson(url) {
    return fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }

  function safeUrl(url) {
    return typeof url === "string" && /^https:\/\//i.test(url) ? url : null;
  }

  function dayKey(iso) {
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(date).reduce(function (result, part) {
      result[part.type] = part.value;
      return result;
    }, {});
    return parts.year + "-" + parts.month + "-" + parts.day;
  }

  function dayTitle(day) {
    var parts = String(day || "").split("-");
    if (parts.length !== 3) return "日期未知";
    var date = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 4));
    return parts[0] + "年" + Number(parts[1]) + "月" + Number(parts[2]) + "日 · "
      + ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"][date.getUTCDay()];
  }

  function dateChipTitle(day) {
    var parts = String(day || "").split("-");
    if (parts.length !== 3) return day || "日期未知";
    return parts[0] + "/" + parts[1] + "/" + parts[2];
  }

  function formatTime(iso) {
    var date = new Date(iso);
    return isNaN(date.getTime()) ? "--:--" : timeFormatter.format(date);
  }

  function formatFullTime(iso) {
    var date = new Date(iso);
    return isNaN(date.getTime()) ? "时间未知" : dateFormatter.format(date) + " " + formatTime(iso);
  }

  function relativeTime(iso) {
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "时间未知";
    var minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
    if (minutes < 1) return "刚刚";
    if (minutes < 60) return minutes + " 分钟前";
    if (minutes < 1440) return Math.round(minutes / 60) + " 小时前";
    return Math.round(minutes / 1440) + " 天前";
  }

  function setText(id, value) {
    var element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function setCategoryOptions(select, selected) {
    if (!select) return;
    select.textContent = "";
    var all = document.createElement("option");
    all.value = "";
    all.textContent = "全部分类";
    select.appendChild(all);
    state.categories.forEach(function (category) {
      var option = document.createElement("option");
      option.value = category.key;
      option.textContent = category.label + (category.count ? "  ·  " + category.count : "");
      select.appendChild(option);
    });
    select.value = selected || "";
  }

  function loadCategories() {
    return fetchJson("/api/news/categories").then(function (payload) {
      state.categories = (payload.categories || []).filter(function (item) { return item.key !== "other" || item.count; });
      setCategoryOptions(els.digestCategory, state.digestCategory);
      setCategoryOptions(els.featuredCategory, state.featuredCategory);
      var total = state.categories.reduce(function (sum, item) { return sum + (item.count || 0); }, 0);
      setText("news-item-count", total ? String(total) : "—");
    }).catch(function () {
      setCategoryOptions(els.digestCategory, state.digestCategory);
      setCategoryOptions(els.featuredCategory, state.featuredCategory);
    });
  }

  function loadDays() {
    return fetchJson("/api/news/days?limit=60").then(function (payload) {
      var days = payload.days || [];
      setText("news-day-count", days.length ? String(days.length) : "—");
      renderDayBar(days);
      if (!days.length) {
        state.digestDay = null;
        renderEmptyDigest("还没有日报数据", "采集器完成首轮运行后，这里会按日期生成日报。");
      } else if (!state.digestDay || !days.some(function (item) { return item.day === state.digestDay; })) {
        selectDay(days[0].day);
      } else {
        markActiveDay();
      }
      return days;
    }).catch(function (error) {
      renderEmptyDigest("日期索引读取失败", error.message);
      return [];
    });
  }

  function renderDayBar(days) {
    els.dayBar.textContent = "";
    days.forEach(function (entry) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "digest-day-chip";
      chip.dataset.day = entry.day;
      chip.setAttribute("role", "tab");
      chip.setAttribute("aria-selected", entry.day === state.digestDay ? "true" : "false");

      var date = document.createElement("strong");
      date.textContent = dateChipTitle(entry.day);
      chip.appendChild(date);
      var meta = document.createElement("small");
      meta.textContent = entry.count + " 条 · " + dayTitle(entry.day).split(" · ")[1];
      chip.appendChild(meta);
      if (entry.top_title) chip.title = entry.top_title;
      chip.addEventListener("click", function () { selectDay(entry.day); });
      els.dayBar.appendChild(chip);
    });
    markActiveDay();
  }

  function markActiveDay() {
    Array.prototype.forEach.call(els.dayBar.querySelectorAll(".digest-day-chip"), function (chip) {
      var active = chip.dataset.day === state.digestDay;
      chip.classList.toggle("active", active);
      chip.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  function selectDay(day) {
    state.digestDay = day;
    state.digestPayload = null;
    markActiveDay();
    loadDigest(day);
  }

  function flattenPayload(payload) {
    var items = [];
    var seen = {};
    Object.keys(payload.by_category || {}).forEach(function (key) {
      (payload.by_category[key] || []).forEach(function (item) {
        if (seen[item.id]) return;
        seen[item.id] = true;
        items.push(item);
      });
    });
    return items.sort(function (a, b) { return new Date(b.published_at) - new Date(a.published_at); });
  }

  function matches(item, category, query) {
    if (category && item.category !== category) return false;
    if (!query) return true;
    var haystack = ((item.title || "") + " " + (item.summary || "") + " " + (item.tags || []).join(" ")).toLowerCase();
    return haystack.indexOf(query.toLowerCase()) >= 0;
  }

  function loadDigest(day) {
    els.digestBody.textContent = "";
    var loading = document.createElement("div");
    loading.className = "news-loading";
    loading.appendChild(document.createElement("span"));
    var loadingText = document.createElement("p");
    loadingText.textContent = "正在读取 " + dateChipTitle(day) + " 日报…";
    loading.appendChild(loadingText);
    els.digestBody.appendChild(loading);
    fetchJson("/api/news/digest?date=" + encodeURIComponent(day)).then(function (payload) {
      state.digestPayload = payload;
      renderDigest(payload);
    }).catch(function (error) {
      renderEmptyDigest("日报读取失败", error.message);
    });
  }

  function renderDigest(payload) {
    els.digestBody.textContent = "";
    var allItems = flattenPayload(payload);
    var visibleItems = allItems.filter(function (item) { return matches(item, state.digestCategory, state.digestQuery); });
    var featured = (payload.featured || []).filter(function (item) { return matches(item, state.digestCategory, state.digestQuery); }).slice(0, 5);

    var header = document.createElement("div");
    header.className = "digest-head";
    var eyebrow = document.createElement("span");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = "DAILY BRIEFING";
    header.appendChild(eyebrow);
    var title = document.createElement("h3");
    title.textContent = "AI 日报 · " + dayTitle(payload.date);
    header.appendChild(title);
    var meta = document.createElement("p");
    meta.textContent = "准确日期：" + payload.date + "  ·  共 " + visibleItems.length + " 条资讯";
    header.appendChild(meta);
    els.digestBody.appendChild(header);

    if (!allItems.length) {
      renderEmptyDigest("这一天还没有采集到资讯", "换一个日期试试；新的日报会随着采集器运行逐日累积。", true);
      return;
    }

    if (featured.length && !state.digestQuery) {
      var featuredSection = document.createElement("section");
      featuredSection.className = "digest-featured-section";
      var featuredTitle = sectionTitle("★", "当日精选", "A股相关的国内政策、产业链与上市公司资讯优先");
      featuredSection.appendChild(featuredTitle);
      var featuredGrid = document.createElement("div");
      featuredGrid.className = "digest-featured-grid";
      featured.forEach(function (item, index) { featuredGrid.appendChild(renderNewsCard(item, { rank: index + 1, featured: true })); });
      featuredSection.appendChild(featuredGrid);
      els.digestBody.appendChild(featuredSection);
    }

    var timelineHead = document.createElement("div");
    timelineHead.className = "timeline-heading";
    timelineHead.appendChild(sectionTitle("", "当日时间线", state.digestQuery || state.digestCategory ? "当前筛选结果" : "按发布时间倒序"));
    els.digestBody.appendChild(timelineHead);

    if (!visibleItems.length) {
      var filteredEmpty = document.createElement("div");
      filteredEmpty.className = "news-empty compact-empty";
      filteredEmpty.textContent = "当前筛选条件下没有内容";
      els.digestBody.appendChild(filteredEmpty);
      return;
    }

    var timeline = document.createElement("div");
    timeline.className = "news-timeline";
    visibleItems.forEach(function (item) {
      var row = document.createElement("article");
      row.className = "timeline-row";
      var time = document.createElement("time");
      time.textContent = formatTime(item.published_at);
      time.title = formatFullTime(item.published_at);
      row.appendChild(time);
      var marker = document.createElement("i");
      marker.className = "timeline-marker";
      row.appendChild(marker);
      row.appendChild(renderNewsCard(item, { timeline: true }));
      timeline.appendChild(row);
    });
    els.digestBody.appendChild(timeline);
  }

  function sectionTitle(symbol, label, note) {
    var heading = document.createElement("div");
    heading.className = "digest-section-title";
    if (symbol) {
      var icon = document.createElement("i");
      icon.textContent = symbol;
      heading.appendChild(icon);
    }
    var text = document.createElement("strong");
    text.textContent = label;
    heading.appendChild(text);
    if (note) {
      var small = document.createElement("small");
      small.textContent = note;
      heading.appendChild(small);
    }
    return heading;
  }

  function renderNewsCard(item, options) {
    options = options || {};
    var card = document.createElement("div");
    card.className = options.featured ? "news-card news-card-featured" : "news-card";
    if (options.timeline) card.classList.add("news-card-timeline");

    var meta = document.createElement("div");
    meta.className = "news-card-meta";
    if (options.rank) {
      var rank = document.createElement("span");
      rank.className = "news-rank";
      rank.textContent = "精选 " + String(options.rank).padStart(2, "0");
      meta.appendChild(rank);
    }
    var category = document.createElement("span");
    category.className = "news-card-category";
    category.style.setProperty("--category-color", CATEGORY_COLORS[item.category] || "#81f0bd");
    category.textContent = item.category_label || CATEGORY_LABELS[item.category] || "其他";
    meta.appendChild(category);
    var source = document.createElement("span");
    source.className = "news-card-source";
    source.textContent = item.source_name || "未知来源";
    meta.appendChild(source);
    if (item.region === "cn") {
      var region = document.createElement("span");
      region.className = "news-card-region";
      region.textContent = "国内来源";
      meta.appendChild(region);
    }
    if (item.authority_label) {
      var authority = document.createElement("span");
      authority.className = "news-card-authority authority-" + (item.source_type || "specialist");
      authority.textContent = item.authority_label;
      authority.title = "来源类型，不代替对具体事实的交叉核对";
      meta.appendChild(authority);
    }
    if (item.source_count > 1) {
      var coverage = document.createElement("span");
      coverage.className = "news-card-coverage";
      coverage.textContent = item.source_count + " 家来源";
      meta.appendChild(coverage);
    }
    card.appendChild(meta);

    var title = document.createElement("h4");
    var link = document.createElement("a");
    link.textContent = item.title || "（无标题）";
    var href = safeUrl(item.url);
    if (href) {
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
    title.appendChild(link);
    card.appendChild(title);

    if (item.summary) {
      var summary = document.createElement("p");
      summary.className = "news-card-summary";
      summary.textContent = item.summary;
      card.appendChild(summary);
    }

    var foot = document.createElement("div");
    foot.className = "news-card-foot";
    var tags = document.createElement("div");
    tags.className = "news-tags";
    (item.tags || []).slice(0, 4).forEach(function (tag) {
      var badge = document.createElement("span");
      badge.className = "news-tag";
      badge.textContent = String(tag);
      tags.appendChild(badge);
    });
    foot.appendChild(tags);
    var action = document.createElement("a");
    action.className = "news-original";
    action.textContent = "查看原文 ↗";
    if (href) {
      action.href = href;
      action.target = "_blank";
      action.rel = "noopener noreferrer";
    } else {
      action.classList.add("hidden");
    }
    foot.appendChild(action);
    card.appendChild(foot);
    return card;
  }

  function renderEmptyDigest(title, message, append) {
    if (!append) els.digestBody.textContent = "";
    var empty = document.createElement("div");
    empty.className = "news-empty";
    var strong = document.createElement("strong");
    strong.textContent = title;
    var text = document.createElement("p");
    text.textContent = message;
    empty.appendChild(strong);
    empty.appendChild(text);
    els.digestBody.appendChild(empty);
  }

  function loadFeatured() {
    els.featuredList.textContent = "";
    var loading = document.createElement("div");
    loading.className = "news-loading";
    loading.appendChild(document.createElement("span"));
    var loadingText = document.createElement("p");
    loadingText.textContent = "正在整理近期精选…";
    loading.appendChild(loadingText);
    els.featuredList.appendChild(loading);
    return fetchJson("/api/news?limit=80").then(function (payload) {
      state.featuredItems = (payload.items || []).sort(function (a, b) {
        return Number((b.source_count || 0) > 1) - Number((a.source_count || 0) > 1)
          || (b.a_share_relevance || 0) - (a.a_share_relevance || 0)
          || (b.authority_score || 0) - (a.authority_score || 0)
          || (b.source_count || 0) - (a.source_count || 0)
          || (b.importance_score || 0) - (a.importance_score || 0)
          || new Date(b.published_at) - new Date(a.published_at);
      });
      renderFeatured();
    }).catch(function (error) {
      els.featuredList.textContent = "精选读取失败：" + error.message;
    });
  }

  function renderFeatured() {
    els.featuredList.textContent = "";
    var filtered = state.featuredItems.filter(function (item) {
      return matches(item, state.featuredCategory, state.featuredQuery);
    });
    var counts = {};
    var visible = filtered.filter(function (item) {
      var sourceId = item.source_id || "unknown";
      if ((counts[sourceId] || 0) >= 3) return false;
      counts[sourceId] = (counts[sourceId] || 0) + 1;
      return true;
    }).slice(0, 18);
    setText("featured-meta", visible.length ? "精选 " + visible.length + " 条" : "暂无精选");
    if (!visible.length) {
      renderFeaturedEmpty();
      return;
    }
    visible.forEach(function (item, index) {
      var wrapper = document.createElement("article");
      wrapper.className = "featured-row";
      var date = document.createElement("div");
      date.className = "featured-date";
      date.textContent = dateChipTitle(dayKey(item.published_at));
      date.appendChild(document.createElement("small"));
      date.lastChild.textContent = formatTime(item.published_at);
      wrapper.appendChild(date);
      wrapper.appendChild(renderNewsCard(item, { rank: index + 1, featured: true }));
      els.featuredList.appendChild(wrapper);
    });
  }

  function renderFeaturedEmpty() {
    var empty = document.createElement("div");
    empty.className = "news-empty";
    var strong = document.createElement("strong");
    strong.textContent = "暂时没有符合条件的精选";
    var text = document.createElement("p");
    text.textContent = "换一个分类或关键词试试。精选会随着采集器运行自动更新。";
    empty.appendChild(strong);
    empty.appendChild(text);
    els.featuredList.appendChild(empty);
  }

  function switchView(view) {
    state.view = view;
    els.digestView.classList.toggle("hidden", view !== "digest");
    els.featuredView.classList.toggle("hidden", view !== "featured");
    els.digestBtn.classList.toggle("active", view === "digest");
    els.featuredBtn.classList.toggle("active", view === "featured");
    els.digestBtn.setAttribute("aria-selected", view === "digest" ? "true" : "false");
    els.featuredBtn.setAttribute("aria-selected", view === "featured" ? "true" : "false");
    if (view === "featured" && !state.featuredItems.length) loadFeatured();
  }

  function loadSources() {
    fetchJson("/api/news/sources").then(function (payload) {
      renderSources(payload.sources || []);
    }).catch(function () { /* 状态面板不是主流程 */ });
  }

  function renderSources(sources) {
    els.sourcesGrid.textContent = "";
    sources.forEach(function (source) {
      var card = document.createElement("article");
      card.className = "source-card";
      var head = document.createElement("div");
      head.className = "source-card-head";
      var name = document.createElement("strong");
      name.textContent = source.name;
      head.appendChild(name);
      var status = document.createElement("span");
      var healthy = !source.consecutive_failures && source.last_success_at;
      status.className = healthy ? "source-ok" : "source-bad";
      status.textContent = healthy ? "正常 · " + relativeTime(source.last_success_at) : "连续失败 " + source.consecutive_failures + " 次";
      head.appendChild(status);
      card.appendChild(head);
      var details = document.createElement("p");
      details.className = "source-card-details";
      details.textContent = (source.region_label ? source.region_label + " · " : "")
        + (source.authority_label ? source.authority_label + " · " : "")
        + (source.last_duration_ms != null ? "最近耗时 " + source.last_duration_ms + " ms" : "尚未运行");
      card.appendChild(details);
      if (source.last_error) {
        var error = document.createElement("p");
        error.className = "source-card-error";
        error.textContent = source.last_error;
        card.appendChild(error);
      }
      els.sourcesGrid.appendChild(card);
    });
  }

  function loadHealth() {
    fetchJson("/api/news/health").then(function (payload) {
      els.statusPill.textContent = "";
      var dot = document.createElement("i");
      els.statusPill.appendChild(dot);
      els.statusPill.appendChild(document.createTextNode(payload.worker_alive ? " 采集器在线" : payload.items_total ? " 展示历史数据" : " 等待首轮采集"));
      setText("news-item-count", payload.items_total ? String(payload.items_total) : "—");
      setText("news-last-update", payload.last_fetched_at ? formatTime(payload.last_fetched_at) : "—");
    }).catch(function () { /* 页面主体不依赖健康接口 */ });
  }

  function bindEvents() {
    els.digestBtn.addEventListener("click", function () { switchView("digest"); });
    els.featuredBtn.addEventListener("click", function () { switchView("featured"); });
    els.digestCategory.addEventListener("change", function () {
      state.digestCategory = els.digestCategory.value;
      if (state.digestPayload) renderDigest(state.digestPayload);
    });
    els.featuredCategory.addEventListener("change", function () {
      state.featuredCategory = els.featuredCategory.value;
      renderFeatured();
    });
    els.digestSearch.addEventListener("input", function () {
      state.digestQuery = els.digestSearch.value.trim();
      if (state.digestPayload) renderDigest(state.digestPayload);
    });
    els.featuredSearch.addEventListener("input", function () {
      state.featuredQuery = els.featuredSearch.value.trim();
      renderFeatured();
    });
    els.sourcesToggle.addEventListener("click", function () {
      els.sourcesPanel.classList.toggle("hidden");
    });
    els.sourcesClose.addEventListener("click", function () {
      els.sourcesPanel.classList.add("hidden");
    });
  }

  function init() {
    var required = ["digest-view", "featured-view", "digest-day-bar", "digest-body", "featured-list", "digest-category-select", "featured-category-select"];
    for (var i = 0; i < required.length; i += 1) {
      if (!$(required[i])) return;
    }
    els.digestView = $("digest-view");
    els.featuredView = $("featured-view");
    els.digestBtn = $("view-digest-btn");
    els.featuredBtn = $("view-featured-btn");
    els.dayBar = $("digest-day-bar");
    els.digestBody = $("digest-body");
    els.digestCategory = $("digest-category-select");
    els.digestSearch = $("digest-search-input");
    els.featuredCategory = $("featured-category-select");
    els.featuredSearch = $("featured-search-input");
    els.featuredList = $("featured-list");
    els.featuredMeta = $("featured-meta");
    els.statusPill = $("news-status-pill");
    els.sourcesPanel = $("news-sources-panel");
    els.sourcesGrid = $("news-sources-grid");
    els.sourcesToggle = $("news-sources-toggle");
    els.sourcesClose = $("news-sources-close");

    bindEvents();
    Promise.all([loadCategories(), loadDays(), loadSources(), loadHealth()]);
    window.setInterval(function () {
      loadCategories();
      loadDays();
      loadSources();
      loadHealth();
      if (state.view === "featured") loadFeatured();
      else if (state.digestDay) loadDigest(state.digestDay);
    }, REFRESH_MS);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
}());
