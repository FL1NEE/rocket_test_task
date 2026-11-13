"use strict";

const STATUS = {
  movement: { in_transit: "В пути", confirmed: "Принято", cancelled: "Отменено" },
  fbs: { reserved: "Резерв", shipped: "Отправлен", delivered: "Доставлен", cancelled: "Отменён" },
  fbo: { in_transit: "В пути", received: "Принято МП", cancelled: "Отменено" },
};

const OPERATIONS = {
  receipt: "Приход",
  movement_sent: "Перемещение отправлено",
  movement_received: "Перемещение принято",
  movement_cancelled: "Перемещение отменено",
  fbs_reserved: "Резерв FBS",
  fbs_shipped: "Отправка FBS",
  fbs_delivered: "Доставка FBS",
  fbs_cancelled: "Снятие резерва FBS",
  fbo_shipped: "Отгрузка FBO",
  fbo_received: "Приёмка FBO маркетплейсом",
  fbo_cancelled: "Отмена FBO",
  warehouse_created: "Склад создан",
  warehouse_renamed: "Склад переименован",
  warehouse_deleted: "Склад удалён",
};

const TRANSIT_KIND = { movement: "Между ФФ", fbo: "На склад МП (FBO)", fbs: "К клиенту (FBS)" };
const TABS = ["stock", "warehouses", "movements", "fbs", "fbo", "history"];

const state = { tab: "stock", products: [], warehouses: [], editing: null, armedDelete: null, shortage: null };

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ESCAPES[ch]);

const timeFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" });
const time = (iso) => (iso ? timeFormat.format(new Date(iso)) : "—");
const num = (value) => `<td class="num${value === 0 ? " zero" : ""}">${esc(value)}</td>`;
const badge = (group, status) => `<span class="badge s-${esc(status)}">${esc(STATUS[group][status] ?? status)}</span>`;
const warehouseLabel = (wh) => esc(wh.name) + (wh.is_deleted ? ' <span class="muted">(удалён)</span>' : "");
const button = (action, id, label, kind = "") =>
  `<button type="button" class="btn sm ${kind}" data-action="${esc(action)}" data-id="${esc(id)}">${esc(label)}</button>`;

function table(head, rows, columns) {
  const body = rows.length ? rows.join("") : `<tr><td colspan="${columns}" class="empty">Нет данных</td></tr>`;
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

class ApiError extends Error {
  constructor(status, error) {
    super(error?.message || `Ошибка сервера (${status})`);
    this.status = status;
    this.error = error || {};
  }
}

async function api(method, path, body) {
  const init = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, { message: "Нет связи с сервером" });
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }
  if (!response.ok) throw new ApiError(response.status, data?.error);
  return data;
}

function errorText(err) {
  if (!(err instanceof ApiError)) return "Неожиданная ошибка интерфейса";
  const fields = (err.error.fields || []).map((f) => `${f.field}: ${f.message}`).join("; ");
  return fields ? `${err.message} — ${fields}` : err.message;
}

let toastTimer = 0;
function toast(message, kind = "ok") {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4500);
}

const asInt = (value) => {
  const n = Number(value);
  return Number.isInteger(n) ? n : value;
};

function fillSelect(select, options) {
  const current = select.value;
  select.innerHTML = options.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  if (options.some((o) => String(o.value) === current)) select.value = current;
}

async function loadRefs() {
  const [products, warehouses] = await Promise.all([
    api("GET", "/products"),
    api("GET", "/warehouses?include_deleted=true"),
  ]);
  state.products = products;
  state.warehouses = warehouses;
  const active = warehouses.filter((w) => !w.is_deleted);
  const options = {
    products: products.map((p) => ({ value: p.id, label: `${p.sku} — ${p.name}` })),
    "active-warehouses": active.map((w) => ({ value: w.id, label: w.name })),
    "source-warehouses": warehouses.map((w) => ({ value: w.id, label: w.is_deleted ? `${w.name} (удалён)` : w.name })),
  };
  $$("select[data-ref]").forEach((select) => fillSelect(select, options[select.dataset.ref]));
}

async function loadReconcile() {
  const el = $("#reconcile");
  try {
    const report = await api("GET", "/stock/reconcile");
    el.textContent = report.ok ? "Остатки сходятся" : "Расхождение в учёте";
    el.className = `reconcile ${report.ok ? "ok" : "bad"}`;
  } catch {
    el.textContent = "Сверка недоступна";
    el.className = "reconcile bad";
  }
}

async function renderStock() {
  const [matrix, transit] = await Promise.all([api("GET", "/stock"), api("GET", "/stock/in-transit")]);
  const groups = matrix.warehouses
    .map((w) => `<th colspan="3" class="group${w.is_deleted ? " deleted" : ""}">${warehouseLabel(w)}</th>`)
    .join("");
  const triple = "<th>Физ.</th><th>Дост.</th><th>Резерв FBS</th>";
  const head = `<th rowspan="2">SKU</th><th rowspan="2">Товар</th>${groups}`
    + '<th colspan="3" class="group">Итого на ФФ</th><th colspan="3" class="group">В пути</th></tr><tr>'
    + triple.repeat(matrix.warehouses.length) + triple + "<th>Между ФФ</th><th>На FBO</th><th>К клиенту</th>";
  const rows = matrix.rows.map((r) => "<tr>"
    + `<td class="mono">${esc(r.product.sku)}</td><td>${esc(r.product.name)}</td>`
    + r.cells.map((c) => num(c.physical) + num(c.available) + num(c.reserved_fbs)).join("")
    + num(r.total_physical) + num(r.total_available) + num(r.total_reserved_fbs)
    + num(r.in_transit_between_ff) + num(r.in_transit_to_fbo) + num(r.in_transit_to_client)
    + "</tr>");
  $("#stock-matrix").innerHTML = table(head, rows, 8 + matrix.warehouses.length * 3);

  const transitRows = transit.map((i) => "<tr>"
    + `<td>${esc(TRANSIT_KIND[i.kind])}</td><td class="mono">#${esc(i.document_id)}</td>`
    + `<td class="mono">${esc(i.product.sku)}</td><td>${esc(i.product.name)}</td>${num(i.qty)}`
    + `<td>${esc(i.source)} → ${esc(i.destination)}</td><td>${esc(time(i.since))}</td></tr>`);
  $("#in-transit").innerHTML = table(
    "<th>Куда едет</th><th>Документ</th><th>SKU</th><th>Товар</th><th>Кол-во</th><th>Маршрут</th><th>С</th>",
    transitRows, 7,
  );
}

function renderWarehouses() {
  const rows = state.warehouses.map((w) => {
    const status = w.is_deleted ? '<span class="badge s-deleted">Удалён</span>' : '<span class="badge s-active">Работает</span>';
    let name = warehouseLabel(w);
    let actions = "";
    if (!w.is_deleted && state.editing === w.id) {
      name = `<input class="rename" data-rename="${esc(w.id)}" value="${esc(w.name)}" maxlength="100" aria-label="Новое название">`;
      actions = button("wh-save", w.id, "Сохранить", "ok") + button("wh-edit-cancel", w.id, "Отмена");
    } else if (!w.is_deleted) {
      const armed = state.armedDelete === w.id;
      actions = button("wh-edit", w.id, "Переименовать")
        + button("wh-delete", w.id, armed ? "Точно удалить?" : "Удалить", armed ? "danger armed" : "danger");
    }
    return `<tr><td class="mono">${esc(w.id)}</td><td>${name}</td><td>${status}</td>`
      + `<td>${esc(time(w.created_at))}</td><td>${esc(time(w.deleted_at))}</td><td>${actions}</td></tr>`;
  });
  $("#warehouse-list").innerHTML = table(
    "<th>ID</th><th>Название</th><th>Статус</th><th>Создан</th><th>Удалён</th><th>Действия</th>", rows, 6,
  );
  const input = $("input.rename");
  if (input) { input.focus(); input.select(); }
}

async function renderMovements() {
  const items = await api("GET", "/movements");
  const rows = items.map((m) => {
    const actions = m.status === "in_transit"
      ? button("movement-confirm", m.id, "Принять", "ok") + button("movement-cancel", m.id, "Отменить", "danger")
      : "";
    return `<tr><td class="mono">#${esc(m.id)}</td><td class="mono">${esc(m.product.sku)}</td><td>${esc(m.product.name)}</td>`
      + `<td>${warehouseLabel(m.from_warehouse)}</td><td>${warehouseLabel(m.to_warehouse)}</td>${num(m.qty)}`
      + `<td>${badge("movement", m.status)}</td><td>${esc(time(m.created_at))}</td><td>${actions}</td></tr>`;
  });
  $("#movement-list").innerHTML = table(
    "<th>№</th><th>SKU</th><th>Товар</th><th>Откуда</th><th>Куда</th><th>Кол-во</th><th>Статус</th><th>Создано</th><th>Действия</th>",
    rows, 9,
  );
}

async function renderFbs() {
  const items = await api("GET", "/fbs");
  const rows = items.map((o) => {
    let actions = "";
    if (o.status === "reserved") actions = button("fbs-ship", o.id, "Отправить", "ok") + button("fbs-cancel", o.id, "Снять резерв", "danger");
    if (o.status === "shipped") actions = button("fbs-deliver", o.id, "Доставлен", "ok");
    return `<tr><td class="mono">#${esc(o.id)}</td><td class="mono">${esc(o.product.sku)}</td><td>${esc(o.product.name)}</td>`
      + `<td>${warehouseLabel(o.warehouse)}</td>${num(o.qty)}<td>${badge("fbs", o.status)}</td>`
      + `<td>${esc(time(o.created_at))}</td><td>${actions}</td></tr>`;
  });
  $("#fbs-list").innerHTML = table(
    "<th>№</th><th>SKU</th><th>Товар</th><th>Склад</th><th>Кол-во</th><th>Статус</th><th>Создан</th><th>Действия</th>",
    rows, 8,
  );
}

async function renderFbo() {
  const items = await api("GET", "/fbo");
  const rows = items.map((s) => {
    const actions = s.status === "in_transit"
      ? button("fbo-receive", s.id, "Принято МП", "ok") + button("fbo-cancel", s.id, "Отменить", "danger")
      : "";
    return `<tr><td class="mono">#${esc(s.id)}</td><td class="mono">${esc(s.product.sku)}</td><td>${esc(s.product.name)}</td>`
      + `<td>${warehouseLabel(s.warehouse)}</td>${num(s.qty)}<td>${badge("fbo", s.status)}</td>`
      + `<td>${esc(time(s.created_at))}</td><td>${actions}</td></tr>`;
  });
  $("#fbo-list").innerHTML = table(
    "<th>№</th><th>SKU</th><th>Товар</th><th>Склад</th><th>Кол-во</th><th>Статус</th><th>Создана</th><th>Действия</th>",
    rows, 8,
  );
}

async function renderHistory() {
  const items = await api("GET", "/operations?limit=300");
  const rows = items.map((e) => {
    const route = e.source || e.destination ? `${esc(e.source ?? "—")} → ${esc(e.destination ?? "—")}` : "—";
    const doc = e.document_type ? `${esc(e.document_type)} #${esc(e.document_id)}` : "—";
    return `<tr><td>${esc(time(e.created_at))}</td><td>${esc(OPERATIONS[e.operation] ?? e.operation)}</td>`
      + `<td class="mono">${esc(e.product_sku ?? "—")}</td>${e.qty === null ? "<td>—</td>" : num(e.qty)}`
      + `<td>${route}</td><td class="mono">${doc}</td></tr>`;
  });
  $("#history-list").innerHTML = table(
    "<th>Время</th><th>Операция</th><th>SKU</th><th>Кол-во</th><th>Откуда → куда</th><th>Документ</th>", rows, 6,
  );
}

const RENDERERS = {
  stock: renderStock,
  warehouses: async () => renderWarehouses(),
  movements: renderMovements,
  fbs: renderFbs,
  fbo: renderFbo,
  history: renderHistory,
};

async function refresh() {
  try {
    await loadRefs();
    await RENDERERS[state.tab]();
  } catch (err) {
    toast(errorText(err), "err");
  }
  loadReconcile();
}

function selectTab(tab) {
  state.tab = TABS.includes(tab) ? tab : "stock";
  state.editing = null;
  state.armedDelete = null;
  $$("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  $$("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== state.tab; });
  if (location.hash !== `#${state.tab}`) history.replaceState(null, "", `#${state.tab}`);
  refresh();
}

function shipmentBody(data) {
  return { product_id: asInt(data.get("product_id")), warehouse_id: asInt(data.get("warehouse_id")), qty: asInt(data.get("qty")) };
}

const FORMS = {
  "warehouse-create": async (data, form) => {
    const wh = await api("POST", "/warehouses", { name: String(data.get("name") ?? "") });
    form.reset();
    return `Склад «${wh.name}» добавлен`;
  },
  receipt: async (data) => {
    const r = await api("POST", "/receipts", shipmentBody(data));
    return `Оприходовано ${r.qty} шт. ${r.product.sku} на «${r.warehouse.name}»`;
  },
  movement: async (data) => {
    const m = await api("POST", "/movements", {
      product_id: asInt(data.get("product_id")),
      from_warehouse_id: asInt(data.get("from_warehouse_id")),
      to_warehouse_id: asInt(data.get("to_warehouse_id")),
      qty: asInt(data.get("qty")),
    });
    return `Перемещение #${m.id}: ${m.qty} шт. ${m.product.sku} в пути «${m.from_warehouse.name}» → «${m.to_warehouse.name}»`;
  },
  fbs: async (data, form) => submitShipment("fbs", shipmentBody(data), form),
  fbo: async (data, form) => submitShipment("fbo", shipmentBody(data), form),
};

async function submitShipment(kind, body, form) {
  try {
    const doc = await api("POST", `/${kind}`, body);
    return kind === "fbs"
      ? `Резерв #${doc.id}: ${doc.qty} шт. ${doc.product.sku} на «${doc.warehouse.name}»`
      : `Поставка FBO #${doc.id}: ${doc.qty} шт. ${doc.product.sku} в пути на склад МП`;
  } catch (err) {
    if (err instanceof ApiError && err.error.code === "insufficient_stock") showShortage(kind, body, err.error, form);
    throw err;
  }
}

function showShortage(kind, request, error, form) {
  state.shortage = { kind, request };
  const box = $(".shortage", form);
  const enough = error.alternatives.filter((a) => a.available >= request.qty);
  const partial = error.alternatives.filter((a) => a.available < request.qty);
  let html = `<p>Всего доступно на работающих складах: <strong>${esc(error.total_available)}</strong> шт.</p>`;
  html += enough.map((a) => button("shortage-use", a.warehouse_id, `Взять с «${a.warehouse}» (доступно ${a.available})`, "ok")).join("");
  if (kind === "fbs" && error.can_split) html += button("shortage-split", 0, "Разделить резерв по складам", "ok");
  if (partial.length) html += `<p>Частично: ${partial.map((a) => `${esc(a.warehouse)} — ${esc(a.available)}`).join(", ")}</p>`;
  if (!enough.length && !(kind === "fbs" && error.can_split)) html += "<p>Общего остатка не хватает: оформите приход.</p>";
  box.innerHTML = html;
  box.hidden = false;
}

function hideShortage() {
  state.shortage = null;
  $$(".shortage").forEach((box) => { box.hidden = true; box.innerHTML = ""; });
}

async function mutate(path, message, body) {
  await api("POST", path, body);
  hideShortage();
  toast(message);
}

async function renameWarehouse(id) {
  const input = $(`input[data-rename="${CSS.escape(String(id))}"]`);
  const wh = await api("PATCH", `/warehouses/${id}`, { name: input ? input.value : "" });
  state.editing = null;
  toast(`Склад переименован в «${wh.name}»`);
}

let disarmTimer = 0;
const ACTIONS = {
  "movement-confirm": (id) => mutate(`/movements/${id}/confirm`, `Перемещение #${id} принято на склад`),
  "movement-cancel": (id) => mutate(`/movements/${id}/cancel`, `Перемещение #${id} отменено, товар вернулся`),
  "fbs-ship": (id) => mutate(`/fbs/${id}/ship`, `Заказ FBS #${id} отправлен клиенту`),
  "fbs-deliver": (id) => mutate(`/fbs/${id}/deliver`, `Заказ FBS #${id} доставлен`),
  "fbs-cancel": (id) => mutate(`/fbs/${id}/cancel`, `Резерв FBS #${id} снят`),
  "fbo-receive": (id) => mutate(`/fbo/${id}/receive`, `Поставка FBO #${id} принята маркетплейсом`),
  "fbo-cancel": (id) => mutate(`/fbo/${id}/cancel`, `Поставка FBO #${id} отменена, товар вернулся`),
  "shortage-use": (warehouseId) => {
    const { kind, request } = state.shortage;
    return mutate(`/${kind}`, "Оформлено с другого склада", { ...request, warehouse_id: warehouseId });
  },
  "shortage-split": () => {
    const { request } = state.shortage;
    return mutate("/fbs/allocate", "Резерв разделён по складам", {
      product_id: request.product_id, qty: request.qty, preferred_warehouse_id: request.warehouse_id,
    });
  },
  "wh-edit": (id) => { state.editing = id; state.armedDelete = null; renderWarehouses(); return null; },
  "wh-edit-cancel": () => { state.editing = null; renderWarehouses(); return null; },
  "wh-save": (id) => renameWarehouse(id),
  "wh-delete": async (id) => {
    if (state.armedDelete !== id) {
      state.armedDelete = id;
      renderWarehouses();
      clearTimeout(disarmTimer);
      disarmTimer = setTimeout(() => { state.armedDelete = null; if (state.tab === "warehouses") renderWarehouses(); }, 4000);
      return null;
    }
    state.armedDelete = null;
    const wh = await api("DELETE", `/warehouses/${id}`);
    toast(`Склад «${wh.name}» удалён, остатки и история сохранены`);
    return true;
  },
};

document.addEventListener("click", async (event) => {
  const tab = event.target.closest("[data-tab]");
  if (tab) { selectTab(tab.dataset.tab); return; }

  const el = event.target.closest("[data-action]");
  if (!el || el.disabled) return;
  const handler = ACTIONS[el.dataset.action];
  if (!handler) return;
  el.disabled = true;
  try {
    const result = await handler(Number(el.dataset.id));
    if (result !== null) await refresh();
  } catch (err) {
    toast(errorText(err), "err");
    await refresh();
  } finally {
    el.disabled = false;
  }
});

document.addEventListener("keydown", (event) => {
  const input = event.target.closest("input[data-rename]");
  if (!input) return;
  if (event.key === "Enter") { event.preventDefault(); $('[data-action="wh-save"]')?.click(); }
  if (event.key === "Escape") { $('[data-action="wh-edit-cancel"]')?.click(); }
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("form[data-form]");
  if (!form) return;
  event.preventDefault();
  const submit = $('[type="submit"]', form);
  const msg = $(".form-msg", form);
  if (submit.disabled) return;
  submit.disabled = true;
  msg.textContent = "";
  msg.className = "form-msg";
  hideShortage();
  try {
    msg.textContent = await FORMS[form.dataset.form](new FormData(form), form);
    msg.classList.add("ok");
    await refresh();
  } catch (err) {
    msg.textContent = errorText(err);
    msg.classList.add("err");
  } finally {
    submit.disabled = false;
  }
});

window.addEventListener("hashchange", () => selectTab(location.hash.slice(1)));
selectTab(location.hash.slice(1));
