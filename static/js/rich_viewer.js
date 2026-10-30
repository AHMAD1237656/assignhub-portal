
(() => {
    "use strict";

    const container = document.getElementById(
        "rich-viewer"
    );

    const script = document.getElementById(
        "rich-viewer-delta"
    );

    const fallback = document.getElementById(
        "rich-viewer-fallback"
    );

    if (
        !container ||
        !script ||
        !window.Quill ||
        !window.katex
    ) {
        return;
    }

    try {

        const delta = JSON.parse(
            script.textContent
        );

        if (
            !delta ||
            !Array.isArray(delta.ops) ||
            !delta.ops.length
        ) {
            return;
        }

        // ==================================
        // CREATE READ-ONLY QUILL INSTANCE
        // ==================================

        const viewer = new Quill(
            container,
            {
                theme: "snow",

                readOnly: true,

                modules: {
                    toolbar: false
                },

                formats: [
                    "header",
                    "font",
                    "size",
                    "bold",
                    "italic",
                    "underline",
                    "strike",
                    "color",
                    "background",
                    "script",
                    "list",
                    "blockquote",
                    "align",
                    "indent",
                    "lineheight",
                    "link",
                    "formula",
                    "shape",
                    "ahTable",
                    "ahRule"
                ]
            }
        );

        // ==================================
        // LOAD FORMATTED ANSWER
        // ==================================


const compatibleDelta = {
    ops: delta.ops.map(op => {
        if (
            op.insert &&
            typeof op.insert === "object"
        ) {
            if (
                Object.prototype.hasOwnProperty.call(
                    op.insert,
                    "table"
                )
            ) {
                return {
                    ...op,
                    insert: {
                        ahTable: op.insert.table
                    }
                };
            }

            if (
                Object.prototype.hasOwnProperty.call(
                    op.insert,
                    "rule"
                )
            ) {
                return {
                    ...op,
                    insert: {
                        ahRule: op.insert.rule
                    }
                };
            }
        }

        return op;
    })
};

viewer.setContents(
    compatibleDelta,
    "silent"
);


        viewer.disable();

        // ==================================
        // SECURE VIEWER HYPERLINKS
        // ==================================

        viewer.root.querySelectorAll(
            "a[href]"
        ).forEach(
            link => {

                try {

                    const target = new URL(
                        link.href,
                        location.href
                    );

                    if (
                        ![
                            "http:",
                            "https:"
                        ].includes(
                            target.protocol
                        )
                    ) {

                        link.removeAttribute(
                            "href"
                        );

                        return;
                    }

                    link.target = "_blank";

                    link.rel = (
                        "noopener noreferrer nofollow"
                    );

                } catch (error) {

                    link.removeAttribute(
                        "href"
                    );

                }

            }
        );

        // Hide fallback only after
        // successful rich rendering.
        fallback.hidden = true;

    } catch (error) {

        console.error(
            "Rich answer viewer failed:",
            error
        );

        // Plain text remains visible
        // when rich rendering fails.

    }

})();
