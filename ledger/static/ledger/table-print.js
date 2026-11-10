/* Local-only range selection and browser print preview. No data leaves this page. */
(() => {
  let table, anchor, focus, selecting = false;
  const $ = (selector) => document.querySelector(selector);
  const selectableCells = (row) => Array.from(row.cells).filter((cell) => !cell.classList.contains("no-select") && !cell.classList.contains("empty") && cell.colSpan === 1);
  const dataRows = () => table ? Array.from(table.tBodies[0]?.rows || []).filter((row) => !row.hidden && !row.querySelector(".empty") && selectableCells(row).length) : [];
  const clear = () => {
    if (table) table.querySelectorAll(".cell-selected").forEach((cell) => cell.classList.remove("cell-selected"));
    anchor = focus = null;
    const button = $("[data-print-range]"); if (button) button.disabled = true;
  };
  const position = (cell) => ({row: dataRows().indexOf(cell.parentElement), col: selectableCells(cell.parentElement).indexOf(cell)});
  const valid = (point) => point && point.row >= 0 && point.col >= 0;
  const paint = () => {
    if (!table || !valid(anchor) || !valid(focus)) return;
    table.querySelectorAll(".cell-selected").forEach((cell) => cell.classList.remove("cell-selected"));
    const minRow = Math.min(anchor.row, focus.row), maxRow = Math.max(anchor.row, focus.row);
    const minCol = Math.min(anchor.col, focus.col), maxCol = Math.max(anchor.col, focus.col);
    dataRows().forEach((row, rowIndex) => selectableCells(row).forEach((cell, colIndex) => {
      if (rowIndex >= minRow && rowIndex <= maxRow && colIndex >= minCol && colIndex <= maxCol) cell.classList.add("cell-selected");
    }));
    $("[data-print-range]").disabled = false;
  };
  const cellAtPoint = (x, y) => {
    const element = document.elementFromPoint(x, y);
    const cell = element && element.closest("td");
    return cell && table && table.contains(cell) && !cell.classList.contains("no-select") && !cell.classList.contains("empty") && cell.colSpan === 1 ? cell : null;
  };
  const selectedTable = () => {
    const rows = dataRows(), minRow = Math.min(anchor.row, focus.row), maxRow = Math.max(anchor.row, focus.row);
    const minCol = Math.min(anchor.col, focus.col), maxCol = Math.max(anchor.col, focus.col);
    const out = document.createElement("table"); out.id = "range-print-table"; out.className = "print-table";
    out.dataset.printOrientation = table.dataset.printOrientation || "portrait";
    const header = out.createTHead().insertRow();
    selectableCells(table.tHead.rows[0]).slice(minCol, maxCol + 1).forEach((cell) => { const th = document.createElement("th"); th.textContent = cell.textContent.trim(); header.append(th); });
    const body = out.createTBody();
    rows.slice(minRow, maxRow + 1).forEach((row) => { const tr = body.insertRow(); selectableCells(row).slice(minCol, maxCol + 1).forEach((cell) => { const td = tr.insertCell(); td.textContent = cell.textContent.trim(); }); });
    return out;
  };
  document.addEventListener("DOMContentLoaded", () => {
    const mode = $("[data-range-mode]"), print = $("[data-print-range]"), reset = $("[data-clear-range]");
    document.addEventListener("submit", (event) => {
      const message = event.target.dataset.confirm;
      if (message && !window.confirm(message)) event.preventDefault();
    });
    if (!mode) return;
    const stopSelection = () => {
      selecting = false;
      clear();
      if (table) table.classList.remove("selection-active");
      mode.disabled = false;
      mode.textContent = "範囲選択";
      mode.setAttribute("aria-pressed", "false");
    };
    $("[data-selectable-table]")?.addEventListener("records-filtered", stopSelection);
    mode.setAttribute("aria-pressed", "false");
    mode.addEventListener("click", () => {
      table = $("[data-selectable-table]");
      if (!table || !dataRows().length) return;
      if (table.classList.contains("selection-active")) {
        stopSelection();
        return;
      }
      table.classList.add("selection-active"); table.focus();
      mode.textContent = "範囲選択を終了";
      mode.setAttribute("aria-pressed", "true");
    });
    document.addEventListener("pointerdown", (event) => {
      if (!table || !table.classList.contains("selection-active")) return;
      const cell = cellAtPoint(event.clientX, event.clientY);
      if (!cell) return;
      event.preventDefault(); selecting = true; anchor = focus = position(cell); paint();
    });
    document.addEventListener("pointermove", (event) => {
      if (!selecting) return;
      const cell = cellAtPoint(event.clientX, event.clientY);
      if (cell) { focus = position(cell); paint(); }
    });
    document.addEventListener("pointerup", () => { selecting = false; });
    document.addEventListener("pointercancel", () => { selecting = false; });
    document.addEventListener("keydown", (event) => {
      if (!table || document.activeElement !== table || !table.classList.contains("selection-active")) return;
      if (event.key === "Escape") {
        stopSelection();
        mode.focus();
        return;
      }
      if (!table || !table.classList.contains("selection-active") || !["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
      const rows = dataRows(); if (!rows.length) return;
      event.preventDefault();
      if (!anchor) {
        anchor = {row: 0, col: 0};
        focus = {...anchor};
      }
      focus = {...focus};
      const maxRow = rows.length - 1, maxCol = selectableCells(rows[0]).length - 1;
      if (event.key === "ArrowUp") focus.row = Math.max(0, focus.row - 1);
      if (event.key === "ArrowDown") focus.row = Math.min(maxRow, focus.row + 1);
      if (event.key === "ArrowLeft") focus.col = Math.max(0, focus.col - 1);
      if (event.key === "ArrowRight") focus.col = Math.min(maxCol, focus.col + 1);
      paint();
    });
    reset.addEventListener("click", stopSelection);
    print.addEventListener("click", () => {
      if (!table || !anchor) return;
      $("#range-print-container")?.remove();
      const container = document.createElement("section"); container.id = "range-print-container";
      const heading = document.createElement("h1"); heading.textContent = $("[data-print-title]")?.textContent.trim() || document.title;
      container.append(heading, selectedTable()); document.body.append(container);
      window.print(); window.setTimeout(() => container.remove(), 1000);
    });
  });
})();
