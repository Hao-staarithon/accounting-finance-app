"""Run the table interactions in Qt WebEngine against an isolated test database.

Usage: python -B tests/check_table_ui.py
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_OPENGL", "software")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from werkzeug.serving import make_server

import app as bill_app


CHECKS = r"""
(async () => {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (condition, label) => {
    for (let i = 0; i < 100; i++) { if (condition()) return; await sleep(50); }
    throw new Error('Timeout: ' + label);
  };
  const menu = () => document.querySelector('.table-column-menu');
  const header = (table, col) => document.querySelector(`${table} th[data-col="${col}"] button`);
  const apply = () => menu().querySelector('.menu-footer .primary').click();
  const search = text => {
    const input = menu().querySelector('input[type="search"]');
    input.value = text; input.dispatchEvent(new Event('input', {bubbles:true}));
  };
  const rawAmounts = () => [...document.querySelectorAll('#detail-body td[data-col="amount"]')].map(td => Number(td.textContent.replace('¥','')));
  const groupAmounts = () => [...document.querySelectorAll('#ledger-display-body > tr > td:last-child')].map(td => Number(td.textContent.trim().replace('¥','').replace('已调整','')));
  const equal = (a,b,label) => assert(JSON.stringify(a) === JSON.stringify(b), `${label}: ${JSON.stringify(a)}`);
  try {
    await until(() => allLedgers.length > 0 && document.querySelector('#page-summary').classList.contains('active'), 'initialization');
    switchPage('detail');
    document.querySelector('#filter-branch').value = '__all__';
    await loadDetail();
    assert(detailState.items.length === 6, 'all six source transactions loaded');
    assert(document.querySelector('#btn-detail-batch').disabled, 'total bill batch action requires a selection');
    header('#detail-table','amount').click();
    menu().querySelector('[data-sort="asc"]').click();
    equal(rawAmounts(), [2,5,10,30,50,100], 'numeric ascending');
    header('#detail-table','amount').click();
    menu().querySelector('[data-sort="desc"]').click();
    equal(rawAmounts(), [100,50,30,10,5,2], 'numeric descending');
    document.querySelector('#check-all').click();
    assert(detailState.selected.size === 6, 'select visible rows');
    assert(!document.querySelector('#btn-detail-batch').disabled, 'total bill toolbar action enabled');
    document.querySelector('#btn-detail-batch').click();
    assert(batchOrganizeContext.ids.length === 6, 'total bill toolbar includes selected source rows');
    document.querySelector('#btn-batch-organize-close').click();
    header('#detail-table','category').click(); search('学习'); apply();
    equal(rawAmounts(), [30,10], 'category search filter');
    assert(detailState.selected.size === 2, 'hidden selections cleared');
    header('#detail-table','counterparty').click(); search('不存在'); apply();
    assert(document.querySelectorAll('#detail-body tr').length === 0, 'no matching rows');
    assert(detailState.selected.size === 0, 'no hidden batch selection');
    assert(!document.querySelector('#check-all').checked, 'empty select all unchecked');
    document.querySelector('#btn-detail-table-reset').click();
    header('#detail-table','category').click();
    menu().querySelector('[data-select-all]').click();
    [...menu().querySelectorAll('.menu-values input')].find(input => input.value === '吃饭').click();
    apply();
    equal(rawAmounts().slice().sort((a,b)=>a-b), [2,50], 'checkbox value filter');
    document.querySelector('#btn-detail-table-reset').click();
    header('#detail-table','category').click();
    menu().querySelector('[data-select-all]').click();
    menu().querySelector('.menu-footer button').click();
    assert(rawAmounts().length === 6, 'cancel preserves existing view');
    header('#detail-table','time').click();
    menu().querySelector('[data-range="min"]').value = '2026-10-02';
    menu().querySelector('[data-range="max"]').value = '2026-10-04'; apply();
    assert(rawAmounts().length === 3, 'inclusive date range');
    header('#detail-table','amount').click();
    menu().querySelector('[data-range="min"]').value = '20';
    menu().querySelector('[data-range="max"]').value = '100'; apply();
    assert(rawAmounts().length === 2, 'numeric and date range intersect');
    header('#detail-table','category').click(); search('购物'); apply();
    equal(rawAmounts(), [100], 'three columns intersect');
    document.querySelector('#btn-detail-table-reset').click();
    header('#detail-table','amount').click();
    menu().querySelector('[data-range="min"]').value = '100';
    menu().querySelector('[data-range="max"]').value = '1'; apply();
    assert(menu().querySelector('.menu-error').textContent.length > 0, 'invalid range explained');
    document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',bubbles:true}));
    assert(!menu(), 'Escape closes column menu');
    console.log('PASS: main table sorting, search, range filters and visible selection');

    openLedger('界面验证账本'); await loadLedgerStats();
    await until(() => ledgerDisplayItems.length === 5, 'ledger loaded'); openLedgerDisplayModal();
    header('.ledger-display-table','amount').click(); menu().querySelector('[data-sort="asc"]').click();
    equal(groupAmounts(), [5,12,30,50,100], 'ledger numeric sorting with group');
    document.querySelectorAll('.ledger-row-check').forEach(input => input.click());
    header('.ledger-display-table','category').click(); search('学习'); apply();
    assert(document.querySelectorAll('#ledger-display-body > tr').length === 2, 'group matches member category');
    assert(ledgerSelectedIds.size === 2, 'hidden ledger selections cleared');
    document.querySelector('#btn-ledger-clear-filter').click();
    document.querySelector('.ledger-group-rename').click();
    const rename = document.querySelector('#ledger-group-name-modal');
    assert(!rename.classList.contains('hidden'), 'rename dialog opens');
    assert(Number(getComputedStyle(rename).zIndex) > Number(getComputedStyle(document.querySelector('#ledger-display-modal')).zIndex), 'rename dialog above ledger');
    const title = '考研 <资料> & "交通"';
    document.querySelector('#ledger-group-name').value = title;
    document.querySelector('#btn-ledger-group-name-save').click();
    await until(() => ledgerDisplayItems.some(item => item.title === title), 'renamed group refreshed');
    assert(document.querySelector('.ledger-group-main summary').textContent.includes(title), 'name renders as plain text');
    assert(!document.querySelector('.ledger-group-main summary 资料'), 'name is escaped');
    header('.ledger-display-table','amount').click();
    const rect = menu().getBoundingClientRect();
    assert(rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight, 'menu inside viewport');
    document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',bubbles:true}));
    header('.ledger-display-table','amount').click();
    menu().querySelector('[data-range="min"]').value = '20'; apply();
    assert(document.querySelectorAll('#ledger-display-body > tr').length === 3, 'ledger amount range');
    document.querySelector('#btn-ledger-clear-filter').click();
    const checks = [...document.querySelectorAll('.ledger-row-check')].filter(input => !input.value.startsWith('g-')).slice(0,2);
    checks.forEach(input => input.click());
    document.querySelector('#btn-ledger-group').click();
    assert(!document.querySelector('#ledger-group-modal').classList.contains('hidden'), 'create named group dialog');
    document.querySelector('#ledger-group-title').value = '考研新增组合';
    document.querySelector('#btn-ledger-group-save').click();
    await until(() => ledgerDisplayItems.some(item => item.title === '考研新增组合'), 'new named group saved');
    console.log('PASS: ledger filters, group member categories, rename and named creation');

    await loadLedgers();
    const groupRow = () => document.querySelector('#ledger-display-body [data-display-id="g-1"]');
    groupRow().querySelector('details').open = true;
    const scroll = document.querySelector('#ledger-display-modal .ledger-display-scroll');
    scroll.style.maxHeight = '150px'; scroll.scrollTop = 40;
    const savedScroll = scroll.scrollTop;
    const savedDetails = groupRow().querySelector('details');
    const unchangedRow = document.querySelector('#ledger-display-body [data-display-id="3"]');
    await loadLedgerStats();
    assert(groupRow().querySelector('details') === savedDetails, 'unchanged group DOM reused');
    assert(savedDetails.open && scroll.scrollTop === savedScroll, 'unchanged refresh preserves expansion and scroll');
    groupRow().querySelector('.ledger-member-check[value="1"]').click();
    equal(selectedLedgerSourceIds(), [1], 'partial group member selection');
    assert(groupRow().querySelector('.ledger-row-check').indeterminate, 'partial group shows indeterminate');
    groupRow().querySelector('.ledger-member-check[value="2"]').click();
    equal(selectedLedgerSourceIds().slice().sort(), [1,2], 'full group has distinct source ids');
    assert(groupRow().querySelector('.ledger-row-check').checked, 'all members promote group selection');
    groupRow().querySelector('.ledger-row-check').click();
    assert(selectedLedgerSourceIds().length === 0, 'group deselect clears all members');
    document.querySelector('#ledger-check-all').click();
    assert(selectedLedgerSourceIds().length === 6, 'select all counts underlying source transactions');
    document.querySelector('#ledger-check-all').click();
    groupRow().querySelector('.ledger-row-check').click();
    const target = (await api('/api/ledgers',{method:'POST',body:{name:'批量目标账本'}})).item.id;
    await loadLedgers();
    assert(selectedLedgerSourceIds().length === 2, 'refresh preserves selection');
    document.querySelector('#btn-ledger-batch').click();
    assert(batchOrganizeContext.ids.length === 2, 'whole group expands to original transactions');
    document.querySelector('#batch-organize-category').value = '学习';
    document.querySelector('#batch-organize-mode').value = 'add';
    document.querySelector('#batch-organize-mode').dispatchEvent(new Event('change'));
    document.querySelector(`#batch-organize-ledgers input[value="${target}"]`).click();
    document.querySelector('#btn-batch-organize-save').click();
    await until(() => document.querySelector('#batch-organize-modal').classList.contains('hidden') &&
      ledgerDisplayItems.find(item=>item.group_id===1)?.members.every(member=>member.category==='学习'), 'batch group change');
    assert(groupRow().querySelector('details').open, 'batch category keeps edited group expanded');
    assert(document.querySelector('#ledger-display-body [data-display-id="3"]') === unchangedRow, 'unaffected rows not redrawn');
    for (const id of [1,2]) {
      const memberships = await api(`/api/transactions/${id}/ledgers`);
      assert(memberships.ledger_ids.includes(target) && memberships.ledger_ids.length === 3, 'add preserves original ledgers');
    }
    assert(!(await api('/api/transactions/3/ledgers')).ledger_ids.includes(target), 'unselected transaction unaffected');

    await loadLedgers();
    const otherGroup = [...document.querySelectorAll('#ledger-display-body > tr')].find(row=>row.dataset.displayId!=='g-1');
    const preservedScroll = scroll.scrollTop;
    const oldFetch = window.fetch; let displayFetches = 0;
    window.fetch = (...args) => { if (/\/api\/ledgers\/\d+\/display(?:\?|$)/.test(String(args[0]))) displayFetches++; return oldFetch(...args); };
    const categorySelect = groupRow().querySelector('select[data-tx-id="1"]');
    categorySelect.focus({preventScroll:true}); categorySelect.value='玩乐';
    categorySelect.dispatchEvent(new Event('change',{bubbles:true}));
    await until(()=>ledgerDisplayItems.find(item=>item.group_id===1)?.members.find(member=>member.id===1)?.category==='玩乐','single member edit');
    await sleep(100); window.fetch = oldFetch;
    assert(displayFetches === 1, 'one ledger fetch for a category edit');
    assert(groupRow().querySelector('details').open, 'single edit preserves expansion');
    assert(scroll.scrollTop === preservedScroll, 'single edit preserves scroll position');
    assert(document.querySelector(`[data-display-id="${otherGroup.dataset.displayId}"]`) === otherGroup, 'single edit preserves unaffected DOM');
    scroll.style.maxHeight = '';

    switchPage('detail'); document.querySelector('#filter-branch').value='生活'; await loadDetail();
    for (const id of [3,4]) document.querySelector(`#detail-body .tx-check[value="${id}"]`).click();
    document.querySelector('#btn-detail-batch').click();
    document.querySelector('#batch-organize-category').value='购物';
    document.querySelector('#batch-organize-mode').value='replace';
    document.querySelector('#batch-organize-mode').dispatchEvent(new Event('change'));
    document.querySelector(`#batch-organize-ledgers input[value="${target}"]`).click();
    document.querySelector('#btn-batch-organize-save').click();
    await until(()=>document.querySelector('#batch-organize-modal').classList.contains('hidden'),'main detail batch saved');
    for (const id of [3,4]) equal((await api(`/api/transactions/${id}/ledgers`)).ledger_ids, [target], 'replace membership from main detail');
    await loadDetail();
    assert(detailState.items.every(item=>![3,4].includes(item.id)), 'total bill reflects removed main memberships');
    assert(document.querySelector('#btn-detail-batch').disabled, 'batch selection resets after applying');
    console.log('PASS: batch group/member selection, category and ledger changes, stable row refresh');

    const allTables = [...document.querySelectorAll('table')];
    const batchButton = source => source === 'detail' ? document.querySelector('#btn-detail-batch')
      : source === 'ledger' ? document.querySelector('#btn-ledger-batch')
      : transactionTables[source]?.toolbar.querySelector('[data-table-batch]');
    assert(allTables.length > 0 && allTables.every(table => table.dataset.transactionTable &&
      table.querySelector('thead input[type="checkbox"]') && batchButton(table.dataset.transactionTable)), 'every table has selection and a batch action');
    assert(allTables.every(table => [...table.querySelectorAll('th[data-col]')].every(th =>
      th.dataset.col === 'actions' || th.querySelector('.column-menu-button'))), 'every data column has filter and sorting');

    selectedComboLedgers=[0]; await loadSummary();
    document.querySelector('#btn-combined-details').click();
    header('#combined-table','amount').click(); menu().querySelector('[data-sort="desc"]').click();
    equal(transactionTables.combined.visible.map(item=>item.amount),[50,10,5,2],'combined table amount sorting');
    header('#combined-table','amount').click(); menu().querySelector('[data-range="min"]').value='10'; apply();
    document.querySelector('#combined-table .table-select-all').click();
    equal([...transactionTables.combined.selected].sort((a,b)=>a-b),[2,6],'combined select all respects range filter');
    batchButton('combined').click();
    document.querySelector('#batch-organize-category').value='学习';
    document.querySelector('#batch-organize-mode').value='add';
    document.querySelector('#batch-organize-mode').dispatchEvent(new Event('change'));
    document.querySelector(`#batch-organize-ledgers input[value="${target}"]`).click();
    document.querySelector('#btn-batch-organize-save').click();
    await until(()=>[2,6].every(id=>transactionTables.combined.items.find(item=>item.id===id)?.category==='学习') &&
      document.querySelector('#batch-organize-modal').classList.contains('hidden'),'combined batch refresh');
    for(const id of [2,6]) assert((await api(`/api/transactions/${id}/ledgers`)).ledger_ids.includes(target),'combined batch applied to raw transaction');
    transactionTables.combined.tools.reset();
    document.querySelector('#btn-combined-details-close').click();

    await openDrill('学习','2026-10');
    equal(transactionTables.drill.items.map(item=>item.id).sort((a,b)=>a-b),[2,6],'summary category detail loaded');
    header('#drill-table','counterparty').click(); search('书店'); apply();
    document.querySelector('#drill-table .table-select-all').click();
    equal([...transactionTables.drill.selected],[2],'drill select all respects column search');
    batchButton('drill').click(); document.querySelector('#batch-organize-category').value='购物';
    document.querySelector('#btn-batch-organize-save').click();
    await until(()=>transactionTables.drill.items.length===1 && transactionTables.drill.items[0].id===6 &&
      document.querySelector('#batch-organize-modal').classList.contains('hidden'),'summary drill removes reclassified transaction');
    assert(transactionTables.drill.visible.length===0 && transactionTables.drill.selected.size===0,'drill keeps filter and clears hidden selection');
    document.querySelector('#btn-drill-close').click();
    await openLedgerDrill('学习','支出');
    equal(transactionTables.drill.visible.map(item=>item.id),[6],'independent category detail resets previous context filters');
    document.querySelector('#drill-table .table-select-all').click(); batchButton('drill').click();
    document.querySelector('#batch-organize-category').value='吃饭'; document.querySelector('#btn-batch-organize-save').click();
    await until(()=>transactionTables.drill.items.length===0 && document.querySelector('#batch-organize-modal').classList.contains('hidden'),'independent category detail batch refresh');
    document.querySelector('#btn-drill-close').click();

    for(const id of [3,4]) await api(`/api/transactions/${id}/count`,{method:'POST',body:{count_in_expense:false,exclude_reason:'保留排除原因'}});
    const beforeTotal=(await api('/api/summary?month=2026-10')).total;
    switchPage('excluded'); await loadExcluded();
    header('#excluded-table','amount').click(); menu().querySelector('[data-sort="desc"]').click();
    equal(transactionTables.excluded.visible.map(item=>item.amount),[100,30],'excluded amount sorting');
    header('#excluded-table','counterparty').click(); search('书店'); apply();
    document.querySelector('#excluded-table .table-select-all').click();
    equal([...transactionTables.excluded.selected],[4],'excluded select all respects filters');
    batchButton('excluded').click();
    assert(document.querySelector('#batch-organize-count').textContent.includes('仍保留在不记录'),'excluded batch explains record state');
    document.querySelector('#batch-organize-category').value='玩乐';
    document.querySelector('#batch-organize-mode').value='add'; document.querySelector('#batch-organize-mode').dispatchEvent(new Event('change'));
    document.querySelector(`#batch-organize-ledgers input[value="${currentLedgerItem().id}"]`).click();
    document.querySelector('#btn-batch-organize-save').click();
    await until(()=>transactionTables.excluded.items.find(item=>item.id===4)?.category==='玩乐' &&
      document.querySelector('#batch-organize-modal').classList.contains('hidden'),'excluded batch refresh');
    const excluded=(await api('/api/transactions?count_in_expense=0')).items;
    const changed=excluded.find(item=>item.id===4);
    assert(changed.count_in_expense===0 && changed.exclude_reason==='保留排除原因','excluded batch preserves exclusion and reason');
    assert(changed.ledger_ids.includes(currentLedgerItem().id),'excluded membership updated');
    assert(excluded.find(item=>item.id===3).category==='购物','excluded unselected row unaffected');
    assert((await api('/api/summary?month=2026-10')).total===beforeTotal,'excluded batch leaves accounting totals unchanged');
    console.log('PASS: every table has filters, sorting, selection and bulk classification/membership, including excluded and both category drills');
    window.__tableCheck = {done:true, success:true};
  } catch (error) {
    console.error(error.stack);
    window.__tableCheck = {done:true, success:false, error:String(error.stack)};
  }
})();
"""


class TestPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith("PASS:") or level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print(message, flush=True)


def main():
    qt = QApplication([])
    with tempfile.TemporaryDirectory(prefix="eachbill-ui-") as sandbox:
        bill_app.DB_PATH = str(Path(sandbox) / "test.db")
        bill_app.init_db()
        client = bill_app.app.test_client()
        ledger_id = client.post("/api/ledgers", json={"name": "界面验证账本", "include_in_summary": True}).get_json()["item"]["id"]
        for index, (name, amount, category) in enumerate([
            ("咖啡店", 2, "吃饭"), ("书店", 10, "学习"), ("网店", 100, "购物"),
            ("书店", 30, "学习"), ("退款", 5, "购物"), ("餐厅", 50, "吃饭"),
        ], 1):
            response = client.post("/api/manual/add", json={
                "branch": "界面验证账本", "amount": str(amount), "direction": "收入" if name == "退款" else "支出",
                "category": category, "counterparty": name, "transaction_time": f"2026-10-{index:02d} 12:00:00",
            })
            assert response.status_code == 200, response.get_json()
        response = client.post(f"/api/ledgers/{ledger_id}/display-groups", json={"tx_ids": [1, 2]})
        assert response.status_code == 200
        server = make_server("127.0.0.1", 0, bill_app.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        web = QWebEngineView()
        web.setPage(TestPage(web))
        web.resize(1400, 900)
        web.show()
        loop = QEventLoop()
        result = {}

        def receive(value):
            if not value:
                return
            state = json.loads(value)
            if state.get("done"):
                result.update(state)
                loop.quit()

        timer = QTimer()
        timer.timeout.connect(lambda: web.page().runJavaScript(
            "JSON.stringify(window.__tableCheck || {})", receive
        ))
        timer.start(100)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(45000)
        web.loadFinished.connect(lambda ok: web.page().runJavaScript(CHECKS) if ok else loop.quit())
        web.setUrl(QUrl(f"http://127.0.0.1:{server.server_port}"))
        loop.exec()
        timer.stop()
        watchdog.stop()
        web.close()
        web.page().deleteLater()
        web.deleteLater()
        qt.processEvents()
        server.shutdown()
        assert result.get("success"), result.get("error", "UI check timed out")
        conn = bill_app.get_db()
        try:
            assert conn.execute("SELECT count(*) FROM transactions").fetchone()[0] == 6
        finally:
            conn.close()
    print("UI checks passed; source transactions preserved.", flush=True)


if __name__ == "__main__":
    main()
