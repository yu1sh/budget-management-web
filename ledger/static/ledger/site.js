(() => {
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-payment-source-form]");
    if (!form) return;
    const kind = form.querySelector("#id_kind");
    const linkedSource = form.querySelector("[data-linked-source-field]");
    if (!kind || !linkedSource) return;

    const updateLinkedSourceVisibility = () => {
      const isCodePayment = kind.value === "code_payment";
      linkedSource.hidden = !isCodePayment;
      const select = linkedSource.querySelector("select");
      if (select) select.disabled = !isCodePayment;
    };

    kind.addEventListener("change", updateLinkedSourceVisibility);
    updateLinkedSourceVisibility();
  });

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-household-batch-form]");
    if (!form) return;
    const rows = form.querySelector("[data-breakdown-rows]");
    const template = form.querySelector("[data-breakdown-template]");
    const total = form.querySelector('[name="lines-TOTAL_FORMS"]');
    const add = form.querySelector("[data-add-breakdown]");
    if (!rows || !template || !total || !add) return;

    add.addEventListener("click", () => {
      const index = Number(total.value);
      const fragment = template.content.cloneNode(true);
      const wrapper = document.createElement("div");
      wrapper.append(fragment);
      wrapper.innerHTML = wrapper.innerHTML.replaceAll("__prefix__", String(index));
      rows.append(...wrapper.children);
      total.value = String(index + 1);
      rows.lastElementChild.querySelector("input:not([type=checkbox])")?.focus();
    });

    rows.addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-breakdown]");
      if (!button) return;
      const row = button.closest("[data-breakdown-row]");
      const deleted = row?.querySelector('input[name$="-DELETE"]');
      if (!row || !deleted) return;
      deleted.checked = true;
      row.hidden = true;
    });
  });
})();
