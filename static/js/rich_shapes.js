
(function () {
    "use strict";

    if (!window.Quill) {
        console.error("AssignHub: Quill is not loaded.");
        return;
    }

    const Quill = window.Quill;
    const BlockEmbed = Quill.import("blots/block/embed");

    const allowedShapes = new Set([
        "rectangle",
        "circle",
        "diamond",
        "arrow",
        "line"
    ]);

    // =====================================
    // SHAPES
    // =====================================

    class ShapeBlot extends BlockEmbed {
        static blotName = "shape";
        static tagName = "DIV";
        static className = "ah-shape";

        static create(value) {
            const node = super.create();

            const data =
                value && typeof value === "object"
                    ? value
                    : {};

            const kind = allowedShapes.has(data.kind)
                ? data.kind
                : "rectangle";

            const label = String(
                data.label ?? ""
            ).slice(0, 80);

            node.dataset.kind = kind;
            node.dataset.label = label;

            node.setAttribute(
                "contenteditable",
                "false"
            );

            const span = document.createElement("span");
            span.className = "ah-shape-label";
            span.textContent = label;

            node.appendChild(span);

            return node;
        }

        static value(node) {
            return {
                kind: node.dataset.kind || "rectangle",
                label: node.dataset.label || ""
            };
        }
    }

    // =====================================
    // CUSTOM TABLE
    // Important: NOT named "table"
    // Quill 2 reserves that format name.
    // =====================================

    class AssignHubTableBlot extends BlockEmbed {
        static blotName = "ahTable";
        static tagName = "DIV";
        static className = "ah-table-embed";

        static create(value) {
            const node = super.create();

            const incoming =
                value &&
                typeof value === "object" &&
                Array.isArray(value.rows)
                    ? value.rows
                    : [["", ""], ["", ""]];

            const rows = incoming
                .slice(0, 10)
                .filter(Array.isArray)
                .map(row =>
                    row
                        .slice(0, 8)
                        .map(cell =>
                            String(cell ?? "").slice(0, 400)
                        )
                );

            if (!rows.length || !rows[0].length) {
                rows.splice(0, rows.length, ["", ""]);
            }

            const width = rows[0].length;

            const normalizedRows = rows.map(row => {
                const cells = row.slice(0, width);

                while (cells.length < width) {
                    cells.push("");
                }

                return cells;
            });

            node.dataset.value = JSON.stringify({
                rows: normalizedRows
            });

            node.setAttribute("contenteditable", "false");
            node.setAttribute("tabindex", "0");
            node.setAttribute("role", "button");

            node.setAttribute(
                "aria-label",
                "Assignment table. Click to edit."
            );

            const table = document.createElement("table");
            table.className = "ah-doc-table";

            const tbody = document.createElement("tbody");

            normalizedRows.forEach((row, rowIndex) => {
                const tr = document.createElement("tr");

                row.forEach(cell => {
                    const td = document.createElement(
                        rowIndex === 0 ? "th" : "td"
                    );

                    // Always use textContent for safety.
                    td.textContent = cell;

                    tr.appendChild(td);
                });

                tbody.appendChild(tr);
            });

            table.appendChild(tbody);
            node.appendChild(table);

            const hint = document.createElement("span");
            hint.className = "ah-table-edit-hint";
            hint.textContent = "Click to edit table";

            node.appendChild(hint);

            return node;
        }

        static value(node) {
            try {
                const data = JSON.parse(
                    node.dataset.value || "{}"
                );

                return {
                    rows: Array.isArray(data.rows)
                        ? data.rows
                        : [[""]]
                };
            } catch (error) {
                return {
                    rows: [[""]]
                };
            }
        }
    }

    // =====================================
    // HORIZONTAL RULE
    // =====================================

    class AssignHubRuleBlot extends BlockEmbed {
        static blotName = "ahRule";
        static tagName = "HR";
        static className = "ah-rich-rule";

        static create() {
            const node = super.create();

            node.setAttribute(
                "contenteditable",
                "false"
            );

            return node;
        }

        static value() {
            return true;
        }
    }

    // =====================================
    // REGISTER CUSTOM EMBEDS
    // Must run BEFORE Quill editor is created.
    // =====================================

    Quill.register(ShapeBlot, true);
    Quill.register(AssignHubTableBlot, true);
    Quill.register(AssignHubRuleBlot, true);

    window.AssignHubTableBlot = AssignHubTableBlot;
    window.AssignHubRuleBlot = AssignHubRuleBlot;

    // =====================================
    // LINE SPACING
    // =====================================

    const Parchment = Quill.import("parchment");

    const lineHeight = new Parchment.ClassAttributor(
        "lineheight",
        "ql-lineheight",
        {
            scope: Parchment.Scope.BLOCK,
            whitelist: [
                "single",
                "normal",
                "relaxed",
                "double"
            ]
        }
    );

    Quill.register(lineHeight, true);

    // =====================================
    // FONT FAMILIES
    // =====================================

    const font = Quill.import(
        "attributors/class/font"
    );

    font.whitelist = [
        "arial",
        "serif",
        "monospace"
    ];

    Quill.register(font, true);

    // =====================================
    // FONT SIZES
    // =====================================

    const size = Quill.import(
        "attributors/style/size"
    );

    size.whitelist = [
        "12px",
        "14px",
        "16px",
        "18px",
        "24px",
        "32px"
    ];

    Quill.register(size, true);

    window.AssignHubEmbedsReady = true;

    console.info(
        "AssignHub: Table and Rule embeds registered."
    );
})();
