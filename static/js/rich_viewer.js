(() => {
    "use strict";

    const element = document.getElementById(
        "rich-viewer"
    );

    const dataElement = document.getElementById(
        "rich-viewer-delta"
    );

    const fallback = document.getElementById(
        "rich-viewer-fallback"
    );

    if (
        !element ||
        !dataElement ||
        !window.Quill ||
        !window.katex
    ) {
        return;
    }

    try {
        const documentData = JSON.parse(
            dataElement.textContent
        );

        if (
            !documentData ||
            !Array.isArray(documentData.ops) ||
            !documentData.ops.length
        ) {
            return;
        }

        const viewer = new Quill(
            "#rich-viewer",
            {
                theme: "snow",
                readOnly: true,

                modules: {
                    toolbar: false
                },

                formats: [
                    "header",
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
                    "link",
                    "formula",
                    "shape"
                ]
            }
        );

        viewer.setContents(
            documentData,
            "silent"
        );

        viewer.disable();

        fallback.hidden = true;

    } catch (error) {
        console.error(
            "Rich answer rendering failed:",
            error
        );
    }
})();