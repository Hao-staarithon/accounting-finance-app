/* Local table sorting and Excel-style column filters. No external dependencies. */
(() => {
  "use strict";
  const collator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };
  let activeMenu = null;

  class TableTools {
    constructor(table, columns, onChange) {
      this.table = document.querySelector(table);
      this.columns = columns;
      this.onChange = onChange;
      this.rows = [];
      this.filters = new Map();
      this.ranges = new Map();
      this.sort = null;
      for (const column of columns) {
        const header = this.table.querySelector(`th[data-col="${column.key}"]`);
        if (!header) continue;
        const button = element("button", "column-menu-button");
        button.type = "button";
        button.setAttribute("aria-label", `${column.label}：筛选和排序`);
        button.setAttribute("aria-haspopup", "dialog");
        button.setAttribute("aria-expanded", "false");
        button.append(element("span", "", column.label), element("span", "column-menu-indicator", "▾"));
        button.addEventListener("click", () => this.openMenu(column, button));
        header.replaceChildren(button);
      }
    }

    values(row, column) {
      const raw = column.value(row);
      const values = Array.isArray(raw) ? raw : [raw];
      return [...new Set((values.length ? values : [""]).map(value => String(value ?? "")))];
    }

    matches(row, exceptKey = null) {
      return this.columns.every(column => {
        if (column.key === exceptKey) return true;
        const values = this.values(row, column);
        const selected = this.filters.get(column.key);
        if (selected && !values.some(value => selected.has(value))) return false;
        const range = this.ranges.get(column.key);
        if (!range) return true;
        return values.some(value => {
          if (!value) return false;
          const comparable = column.type === "number" ? Number(value) : value;
          return (range.min === "" || comparable >= range.min) && (range.max === "" || comparable <= range.max);
        });
      });
    }

    visibleRows() {
      const rows = this.rows.filter(row => this.matches(row));
      if (!this.sort) return rows;
      const column = this.columns.find(item => item.key === this.sort.key);
      const value = column.sortValue || column.value;
      const sign = this.sort.direction === "asc" ? 1 : -1;
      return rows.sort((a, b) => {
        let av = value(a), bv = value(b);
        if (Array.isArray(av)) av = av.join("、");
        if (Array.isArray(bv)) bv = bv.join("、");
        if (av == null || av === "") return bv == null || bv === "" ? 0 : 1;
        if (bv == null || bv === "") return -1;
        return sign * (column.type === "number" ? Number(av) - Number(bv) : collator.compare(String(av), String(bv)));
      });
    }

    setRows(rows) {
      this.rows = rows;
      this.updateHeaders();
      return this.visibleRows();
    }

    reset(notify = true) {
      this.filters.clear();
      this.ranges.clear();
      this.sort = null;
      this.closeMenu();
      this.updateHeaders();
      if (notify) this.onChange();
    }

    get active() { return this.filters.size > 0 || this.ranges.size > 0 || this.sort != null; }

    updateHeaders() {
      for (const column of this.columns) {
        const header = this.table.querySelector(`th[data-col="${column.key}"]`);
        if (!header) continue;
        const sorted = this.sort?.key === column.key;
        const filtered = this.filters.has(column.key) || this.ranges.has(column.key);
        header.setAttribute("aria-sort", sorted ? (this.sort.direction === "asc" ? "ascending" : "descending") : "none");
        header.querySelector("button").classList.toggle("is-active", sorted || filtered);
        header.querySelector(".column-menu-indicator").textContent = `${sorted ? (this.sort.direction === "asc" ? "↑" : "↓") : ""}${filtered ? "●" : "▾"}`;
      }
    }

    closeMenu() {
      if (activeMenu?.owner === this) activeMenu.close();
    }

    openMenu(column, anchor) {
      const same = activeMenu?.anchor === anchor;
      activeMenu?.close();
      if (same) return;
      const popup = element("div", "table-column-menu");
      popup.setAttribute("role", "dialog");
      popup.setAttribute("aria-label", `${column.label}筛选和排序`);
      const makeButton = (text, action, className = "") => {
        const button = element("button", className, text);
        button.type = "button";
        button.addEventListener("click", action);
        return button;
      };
      const close = (restoreFocus = false) => {
        popup.remove();
        anchor.setAttribute("aria-expanded", "false");
        document.removeEventListener("pointerdown", outside);
        document.removeEventListener("keydown", keyboard, true);
        window.removeEventListener("resize", position);
        document.removeEventListener("scroll", scroll, true);
        if (activeMenu?.popup === popup) activeMenu = null;
        if (restoreFocus) anchor.focus();
      };
      const outside = event => { if (!popup.contains(event.target) && !anchor.contains(event.target)) close(); };
      const keyboard = event => {
        if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(true); }
        if (event.key === "Tab") {
          const controls = [...popup.querySelectorAll("button,input")].filter(node => !node.disabled);
          const edge = event.shiftKey ? controls[0] : controls.at(-1);
          if (document.activeElement === edge) {
            event.preventDefault();
            (event.shiftKey ? controls.at(-1) : controls[0]).focus();
          }
        }
      };
      const position = () => {
        const rect = anchor.getBoundingClientRect();
        popup.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - popup.offsetWidth - 8))}px`;
        popup.style.top = `${Math.max(8, Math.min(rect.bottom + 5, window.innerHeight - popup.offsetHeight - 8))}px`;
      };
      const scroll = event => { if (!popup.contains(event.target)) close(); };
      const title = element("div", "menu-title");
      const closeButton = makeButton("×", () => close(true));
      closeButton.setAttribute("aria-label", "关闭筛选菜单");
      title.append(element("strong", "", column.label), closeButton);
      popup.append(title);
      const sort = element("div", "menu-sort");
      for (const [direction, text] of [["asc", "↑ 升序"], ["desc", "↓ 降序"]]) {
        const button = makeButton(text, () => {
          this.sort = { key: column.key, direction };
          close(); this.onChange();
        }, this.sort?.key === column.key && this.sort.direction === direction ? "primary" : "");
        button.dataset.sort = direction;
        sort.append(button);
      }
      popup.append(sort, makeButton("清除此列筛选", () => {
        this.filters.delete(column.key); this.ranges.delete(column.key);
        close(); this.onChange();
      }, "menu-clear"));
      const search = element("input");
      search.type = "search";
      search.placeholder = "搜索筛选值";
      search.setAttribute("aria-label", "搜索筛选值");
      popup.append(search);
      // Other column filters narrow the options, as in a spreadsheet.
      const values = [...new Set(this.rows.filter(row => this.matches(row, column.key)).flatMap(row => this.values(row, column)))];
      values.sort((a, b) => column.type === "number" ? Number(a) - Number(b) : collator.compare(a, b));
      const selected = new Set(this.filters.get(column.key) || values);
      const allLabel = element("label", "menu-option");
      const selectAll = element("input");
      selectAll.type = "checkbox";
      selectAll.dataset.selectAll = "true";
      allLabel.append(selectAll, element("span", "", "全选当前结果"));
      const list = element("div", "menu-values");
      const count = element("div", "menu-count");
      const matching = () => values.filter(value => (value || "（空白）").toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));
      const renderValues = () => {
        const matches = matching();
        list.replaceChildren();
        for (const value of matches) {
          const label = element("label", "menu-option");
          const input = element("input");
          input.type = "checkbox";
          input.value = value;
          input.checked = selected.has(value);
          input.addEventListener("change", () => {
            if (input.checked) selected.add(value); else selected.delete(value);
            updateAll();
          });
          const formatted = column.format ? column.format(value) : value;
          label.append(input, element("span", "", formatted || "（空白）"));
          list.append(label);
        }
        if (!matches.length) list.append(element("div", "menu-empty", "没有匹配值"));
        updateAll();
        position();
      };
      const updateAll = () => {
        const matches = matching();
        const checkedCount = matches.filter(value => selected.has(value)).length;
        selectAll.checked = matches.length > 0 && checkedCount === matches.length;
        selectAll.indeterminate = checkedCount > 0 && checkedCount < matches.length;
        count.textContent = `已选 ${checkedCount} / ${matches.length} 个值`;
      };
      selectAll.addEventListener("change", () => {
        for (const value of matching()) { if (selectAll.checked) selected.add(value); else selected.delete(value); }
        renderValues();
      });
      search.addEventListener("input", renderValues);
      popup.append(allLabel, list, count);
      let minimum = null, maximum = null;
      if (column.type === "number" || column.type === "date") {
        const range = element("div", "menu-range");
        const saved = this.ranges.get(column.key);
        [minimum, maximum] = ["min", "max"].map(key => {
          const label = element("label", "", column.type === "date" ? (key === "min" ? "起始日期" : "结束日期") : (key === "min" ? "最小金额" : "最大金额"));
          const input = element("input");
          input.type = column.type === "date" ? "date" : "number";
          if (column.type === "number") input.step = "any";
          input.value = saved?.[key] ?? "";
          input.dataset.range = key;
          label.append(input); range.append(label);
          return input;
        });
        popup.append(range);
      }
      const error = element("div", "menu-error");
      const footer = element("div", "menu-footer");
      const apply = () => {
        let min = minimum?.value || "", max = maximum?.value || "";
        if (column.type === "number") {
          min = min === "" ? "" : Number(min); max = max === "" ? "" : Number(max);
        }
        if ((min !== "" && max !== "" && min > max) || minimum?.validity.badInput || maximum?.validity.badInput) {
          error.textContent = "请输入有效范围，起始值不能大于结束值";
          return;
        }
        const picked = search.value.trim() ? new Set(matching().filter(value => selected.has(value))) : selected;
        if (picked.size === values.length && values.every(value => picked.has(value))) this.filters.delete(column.key);
        else this.filters.set(column.key, new Set(picked));
        if (min === "" && max === "") this.ranges.delete(column.key);
        else this.ranges.set(column.key, { min, max });
        close(); this.onChange();
      };
      footer.append(makeButton("取消", () => close(true)), makeButton("确定", apply, "primary"));
      popup.append(error, footer);
      popup.addEventListener("keydown", event => {
        if (event.key === "Enter" && event.target.tagName === "INPUT") { event.preventDefault(); apply(); }
      });
      document.body.append(popup);
      activeMenu = { owner: this, anchor, popup, close };
      anchor.setAttribute("aria-expanded", "true");
      renderValues();
      position();
      document.addEventListener("pointerdown", outside);
      document.addEventListener("keydown", keyboard, true);
      window.addEventListener("resize", position);
      document.addEventListener("scroll", scroll, true);
      search.focus();
    }
  }
  window.TableTools = TableTools;
})();
