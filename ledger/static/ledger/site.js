(() => {
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-payment-source-form]");
    if (!form) return;
    const kind = form.querySelector("#id_kind");
    const linkedSource = form.querySelector("[data-linked-source-field]");
    if (!kind || !linkedSource) return;

    const sourceKinds = Object.fromEntries((form.dataset.sourceKinds || "").split(",").filter(Boolean).map((item) => item.split(":")));
    const allowedKinds = (sourceKind) => sourceKind === "code_payment"
      ? ["credit_card", "bank", "cash"] : sourceKind === "credit_card" ? ["bank"] : [];
    const updateLinkedSourceVisibility = () => {
      const allowed = allowedKinds(kind.value);
      linkedSource.hidden = !allowed.length;
      const select = linkedSource.querySelector("select");
      if (select) {
        select.disabled = !allowed.length;
        select.required = kind.value === "code_payment";
        [...select.options].forEach((option) => {
          if (!option.value) return;
          option.disabled = !allowed.includes(sourceKinds[option.value]);
        });
        if (select.value && !allowed.includes(sourceKinds[select.value])) select.value = "";
      }
    };

    kind.addEventListener("change", updateLinkedSourceVisibility);
    updateLinkedSourceVisibility();
  });

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-payment-link-form]");
    if (!form) return;
    const target = form.querySelector("#id_code_payment");
    const linked = form.querySelector("#id_linked_source");
    const sourceKinds = Object.fromEntries((form.dataset.sourceKinds || "").split(",").filter(Boolean).map((item) => item.split(":")));
    const allowedKinds = (sourceKind) => sourceKind === "code_payment"
      ? ["credit_card", "bank", "cash"] : sourceKind === "credit_card" ? ["bank"] : [];
    const updateOptions = () => {
      if (!target || !linked) return;
      const allowed = allowedKinds(sourceKinds[target.value]);
      [...linked.options].forEach((option) => {
        if (!option.value) return;
        option.disabled = !allowed.includes(sourceKinds[option.value]);
      });
      if (linked.value && !allowed.includes(sourceKinds[linked.value])) linked.value = "";
    };
    target?.addEventListener("change", updateOptions);
    updateOptions();
  });

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-household-batch-form]");
    if (!form) return;
    const rows = form.querySelector("[data-breakdown-rows]");
    const template = form.querySelector("[data-breakdown-template]");
    const total = form.querySelector('[name="lines-TOTAL_FORMS"]');
    const add = form.querySelector("[data-add-breakdown]");
    const source = form.querySelector('[name="payment_source"]');
    const fleaType = form.querySelector("[data-flea-entry-type]");
    const fleaSourceIds = (form.dataset.fleaSourceIds || "").split(",").filter(Boolean);
    if (!rows || !template || !total || !add) return;

    const updateFleaTypeVisibility = () => {
      if (!source || !fleaType) return;
      const select = fleaType.querySelector("select");
      const isFlea = fleaSourceIds.includes(source.value);
      fleaType.hidden = !isFlea;
      fleaType.setAttribute("aria-hidden", String(!isFlea));
      if (select) {
        select.disabled = !isFlea;
        select.required = isFlea;
        if (!isFlea) select.value = "";
      }
    };
    source?.addEventListener("change", updateFleaTypeVisibility);
    updateFleaTypeVisibility();

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
