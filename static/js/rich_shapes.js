(function () {
    "use strict";

    if (!window.Quill) {
        return;
    }

    const Quill = window.Quill;

    const BlockEmbed = Quill.import(
        "blots/block/embed"
    );

    const allowed = new Set([
        "rectangle",
        "circle",
        "diamond",
        "arrow",
        "line"
    ]);

    class ShapeBlot extends BlockEmbed {

        static blotName = "shape";
        static tagName = "DIV";
        static className = "ah-shape";

        static create(value) {
            const node = super.create();

            const data = (
                value &&
                typeof value === "object"
            ) ? value : {};

            const kind = allowed.has(data.kind)
                ? data.kind
                : "rectangle";

            const label = String(
                data.label || ""
            ).slice(0, 80);

            node.dataset.kind = kind;
            node.dataset.label = label;

            node.setAttribute(
                "contenteditable",
                "false"
            );

            const text = document.createElement(
                "span"
            );

            text.className = "ah-shape-label";
            text.textContent = label;

            node.appendChild(text);

            return node;
        }

        static value(node) {
            return {
                kind: node.dataset.kind,
                label: node.dataset.label || ""
            };
        }
    }

    Quill.register(ShapeBlot);

    window.AssignHubShapeBlot = ShapeBlot;
})();