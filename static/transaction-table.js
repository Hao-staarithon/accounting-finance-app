/* Shared selection, column tools and bulk actions for transaction tables. */
(() => {
  "use strict";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);

  class TransactionTable {
    constructor({source, table, body, toolbar, empty, columns, onBatch, onDelete}) {
      this.source = source;
      this.table = document.querySelector(table);
      this.body = document.querySelector(body);
      this.toolbar = document.querySelector(toolbar);
      this.empty = document.querySelector(empty);
      this.columns = columns;
      this.items = [];
      this.visible = [];
      this.selected = new Set();
      this.context = null;
      this.table.dataset.transactionTable = source;
      this.table.tHead.innerHTML = `<tr><th><input type="checkbox" class="table-select-all" aria-label="全选当前筛选结果"></th>${columns.map(column => `<th data-col="${column.key}">${escape(column.label)}</th>`).join("")}</tr>`;
      this.toolbar.classList.add("transaction-table-toolbar");
      this.toolbar.innerHTML = '<span class="small" data-table-status aria-live="polite"></span><div class="row"><button data-table-reset class="small hidden">清除筛选和排序</button><button data-table-delete class="danger" disabled>删除选中</button><button data-table-batch class="primary" disabled>批量设置分类/账本</button></div>';
      this.tools = new TableTools(table, columns.filter(column => column.filterable !== false), () => this.render());
      this.all = this.table.querySelector(".table-select-all");
      this.all.addEventListener("change", () => {
        this.selected.clear();
        if (this.all.checked) this.visible.filter(item => this.eligible(item)).forEach(item => this.selected.add(item.id));
        this.updateSelection();
      });
      this.body.addEventListener("change", event => {
        if (!event.target.classList.contains("table-tx-check")) return;
        const id = Number(event.target.value);
        if (event.target.checked) this.selected.add(id); else this.selected.delete(id);
        this.updateSelection();
      });
      this.toolbar.querySelector("[data-table-batch]").addEventListener("click", () => onBatch(source));
      this.toolbar.querySelector("[data-table-delete]").addEventListener("click", () => onDelete(source));
      this.toolbar.querySelector("[data-table-reset]").addEventListener("click", () => this.tools.reset());
      this.updateSelection();
    }

    eligible(item) { return !item.is_deleted && !item.is_duplicate; }

    setContext(context) {
      if (this.context === context) return;
      this.context = context;
      this.selected.clear();
      this.tools.reset(false);
    }

    setRows(items) { this.items = items; this.render(); }

    clearSelection() { this.selected.clear(); this.updateSelection(); }

    updateSelection() {
      const eligible = this.visible.filter(item => this.eligible(item));
      const count = this.selected.size;
      this.body.querySelectorAll(".table-tx-check").forEach(input => { input.checked = this.selected.has(Number(input.value)); });
      this.all.checked = eligible.length > 0 && eligible.every(item => this.selected.has(item.id));
      this.all.indeterminate = !this.all.checked && count > 0;
      this.all.disabled = eligible.length === 0;
      this.toolbar.querySelector("[data-table-batch]").disabled = count === 0;
      this.toolbar.querySelector("[data-table-delete]").disabled = count === 0;
      this.toolbar.querySelector("[data-table-reset]").classList.toggle("hidden", !this.tools.active);
      this.toolbar.querySelector("[data-table-status]").textContent = `显示 ${this.visible.length} / ${this.items.length} 笔 · 已选 ${count} 笔`;
    }

    render() {
      this.visible = this.tools.setRows(this.items);
      const visibleIds = new Set(this.visible.filter(item => this.eligible(item)).map(item => item.id));
      this.selected = new Set([...this.selected].filter(id => visibleIds.has(id)));
      const wrap = this.body.closest(".table-wrap");
      const top = wrap.scrollTop, left = wrap.scrollLeft;
      const focused = this.body.contains(document.activeElement) ? document.activeElement.dataset.txId : null;
      const oldRows = new Map([...this.body.children].map(row => [row.dataset.txId, row]));
      let cursor = this.body.firstElementChild;
      for (const item of this.visible) {
        const id = String(item.id);
        const markup = `<tr data-tx-id="${id}"><td><input type="checkbox" class="table-tx-check" value="${id}" ${this.eligible(item) ? "" : 'disabled title="已合并的记录不可批量修改"'} aria-label="选择交易"></td>${this.columns.map(column => {
          const value = column.value(item);
          const cell = column.cell ? column.cell(item) : escape(Array.isArray(value) ? value.join("、") : value);
          return `<td data-col="${column.key}"${column.className ? ` class="${column.className}"` : ""}>${cell}</td>`;
        }).join("")}</tr>`;
        const old = oldRows.get(id);
        let row = old;
        if (!row || row._transactionMarkup !== markup) {
          const template = document.createElement("template");
          template.innerHTML = markup;
          row = template.content.firstElementChild;
          row._transactionMarkup = markup;
          if (old) { this.body.replaceChild(row, old); if (cursor === old) cursor = row; }
        }
        if (row === cursor) cursor = cursor.nextElementSibling;
        else this.body.insertBefore(row, cursor);
        oldRows.delete(id);
      }
      oldRows.forEach(row => row.remove());
      if (focused) this.body.querySelector(`select[data-tx-id="${focused}"]`)?.focus({preventScroll:true});
      wrap.scrollTop = top; wrap.scrollLeft = left;
      this.empty.textContent = this.items.length ? "没有符合筛选条件的交易" : "暂无记录";
      this.empty.classList.toggle("hidden", this.visible.length > 0);
      this.updateSelection();
    }
  }
  window.TransactionTable = TransactionTable;
})();
