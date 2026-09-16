/* Search the rendered records only; totals and CSV always cover the full period. */
(() => {
  document.addEventListener("DOMContentLoaded", () => {
    const table = document.querySelector("[data-selectable-table]");
    if (!table?.tBodies[0]) return;
    const rows = [...table.tBodies[0].rows].filter(row => !row.querySelector(".empty"));
    if (!rows.length) return;
    const normalize = text => text.normalize("NFKC").toLocaleLowerCase("ja").trim();
    const records = rows.map(row => ({row, text: normalize([...row.cells]
      .filter(cell => !cell.classList.contains("no-select")).map(cell => cell.textContent).join(" "))}));
    const controls = document.createElement("div");
    controls.className = "record-search";
    const label = document.createElement("label");
    label.textContent = "表示中の明細を検索";
    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = "店名・内訳・日付など";
    input.setAttribute("aria-describedby", "record-search-note");
    label.append(input);
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "secondary";
    reset.textContent = "検索をクリア";
    reset.hidden = true;
    const count = document.createElement("output");
    count.setAttribute("aria-live", "polite");
    const note = document.createElement("p");
    note.id = "record-search-note";
    note.className = "record-search-note";
    note.textContent = "検索はこの一覧のみが対象です。合計金額・CSVの内容は変わりません。";
    const empty = table.tBodies[0].insertRow();
    const emptyCell = empty.insertCell();
    emptyCell.colSpan = table.tHead.rows[0].cells.length;
    emptyCell.className = "empty";
    emptyCell.textContent = "一致する明細がありません。検索語を変えるか、検索をクリアしてください。";
    empty.hidden = true;
    const update = () => {
      const words = normalize(input.value).split(/\s+/).filter(Boolean);
      let visible = 0;
      records.forEach(({row, text}) => {
        row.hidden = !words.every(word => text.includes(word));
        if (!row.hidden) visible++;
      });
      empty.hidden = visible > 0;
      reset.hidden = !input.value;
      count.textContent = `${visible} / ${rows.length}件`;
      table.dispatchEvent(new Event("records-filtered"));
    };
    input.addEventListener("input", update);
    reset.addEventListener("click", () => { input.value = ""; update(); input.focus(); });
    controls.append(label, reset, count);
    table.closest(".table-wrap").before(controls, note);
    update();
  });
})();
