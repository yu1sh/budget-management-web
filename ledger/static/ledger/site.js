(() => {
  document.addEventListener("DOMContentLoaded", () => {
    const nav = document.querySelector("[data-main-nav]");
    nav?.querySelectorAll("a[href]").forEach((link) => {
      const path = new URL(link.href).pathname;
      if (window.location.pathname.startsWith(path)) {
        link.setAttribute("aria-current", "page");
        const menu = link.closest("details");
        if (menu) menu.open = true;
      }
    });
    nav?.addEventListener("keydown", (event) => {
      const menu = event.target.closest("details");
      if (event.key === "Escape" && menu?.open) {
        menu.open = false;
        menu.querySelector("summary").focus();
      }
    });
    document.querySelector("[data-error-summary]")?.focus();
  });

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
      linkedSource.setAttribute("aria-hidden", String(!allowed.length));
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

    const scheduleFields = [...form.querySelectorAll("[data-credit-schedule-field]")];
    const updateScheduleVisibility = () => {
      const isCredit = kind.value === "credit_card";
      scheduleFields.forEach((field) => {
        field.hidden = !isCredit;
        field.setAttribute("aria-hidden", String(!isCredit));
        const input = field.querySelector("select, input");
        if (input) input.disabled = !isCredit;
      });
    };
    kind.addEventListener("change", updateScheduleVisibility);
    updateScheduleVisibility();
  });

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-payment-link-form]");
    if (!form) return;
    const target = form.querySelector("#id_code_payment");
    const linked = form.querySelector("#id_linked_source");
    const sourceKinds = Object.fromEntries((form.dataset.sourceKinds || "").split(",").filter(Boolean).map((item) => item.split(":")));
    const sourceActive = Object.fromEntries((form.dataset.sourceActive || "").split(",").filter(Boolean).map((item) => item.split(":")));
    const currentLinks = Object.fromEntries((form.dataset.currentLinks || "").split(",").filter(Boolean).map((item) => item.split(":")));
    const preserveSelection = form.dataset.preserveSelection === "true";
    const allowedKinds = (sourceKind) => sourceKind === "code_payment"
      ? ["credit_card", "bank", "cash"] : sourceKind === "credit_card" ? ["bank"] : [];
    const updateOptions = (applyCurrentLink = false) => {
      if (!target || !linked) return;
      const allowed = allowedKinds(sourceKinds[target.value]);
      const currentLink = currentLinks[target.value] || "";
      [...linked.options].forEach((option) => {
        if (!option.value) return;
        option.disabled = !allowed.includes(sourceKinds[option.value])
          || (sourceActive[option.value] !== "1" && option.value !== currentLink);
      });
      if (applyCurrentLink || (!preserveSelection && target.value && !linked.value)) {
        linked.value = currentLink;
      }
    };
    target?.addEventListener("change", () => updateOptions(true));
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

    const summary = form.querySelector("[data-batch-summary]");
    const amountOutput = form.querySelector("[data-batch-amount]");
    const countOutput = form.querySelector("[data-batch-count]");
    const yen = new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" });
    const updateSummary = () => {
      let amount = 0;
      let count = 0;
      let invalid = false;
      rows.querySelectorAll("[data-breakdown-row]").forEach((row) => {
        const deleted = row.querySelector('[name$="-DELETE"]');
        row.hidden = Boolean(deleted?.checked);
        if (row.hidden) return;
        const input = row.querySelector('[name$="-amount_yen"]');
        if (input.validity.badInput || (input.value && !input.validity.valid)) invalid = true;
        if (input.value && input.validity.valid) {
          amount += Number(input.value);
          count += 1;
        }
      });
      if (!summary || !amountOutput || !countOutput) return;
      summary.hidden = false;
      amountOutput.textContent = invalid ? "金額を確認してください" : yen.format(amount);
      countOutput.textContent = count ? `${count}行の金額を入力済み` : "金額を入力してください";
    };
    rows.addEventListener("input", updateSummary);
    updateSummary();

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
      updateSummary();
    });

    rows.addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-breakdown]");
      if (!button) return;
      const row = button.closest("[data-breakdown-row]");
      const deleted = row?.querySelector('input[name$="-DELETE"]');
      if (!row || !deleted) return;
      deleted.checked = true;
      row.hidden = true;
      add.focus();
      updateSummary();
    });
  });
})();
