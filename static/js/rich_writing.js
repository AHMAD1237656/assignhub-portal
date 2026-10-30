
(() => {
    "use strict";

    const root = document.getElementById(
        "timed-writing"
    );

    if (!root) {
        return;
    }

    const $ = id => document.getElementById(id);

    const clock = $("writing-clock");
    const state = $("writing-state");
    const saveButton = $("writing-save");
    const finishButton = $("writing-finish");
    const stats = $("ah-document-stats");

    function show(message, type = "pending") {
        state.textContent = message;
        state.dataset.state = type;
    }

    // ======================================
    // LIBRARY CHECK
    // ======================================

    if (
        !window.Quill ||
        !window.katex ||
        !window.bootstrap
    ) {
        show(
            "Editor libraries failed to load. Check internet access.",
            "error"
        );

        clock.textContent = "Unavailable";
        return;
    }

    const csrfNode = document.querySelector(
        '#writing-csrf input[name="csrfmiddlewaretoken"]'
    );

    if (!csrfNode) {
        show(
            "Missing CSRF token.",
            "error"
        );
        return;
    }

    const csrf = csrfNode.value;

    // ======================================
    // INITIALIZE QUILL EDITOR
    // ======================================

    let quill;

    try {

        quill = new Quill(
            "#writing-editor",
            {
                theme: "snow",

                placeholder:
                    "Write your assignment answer here...",

                modules: {

                    toolbar: "#writing-toolbar",

                    history: {
                        delay: 650,
                        maxStack: 100,
                        userOnly: true
                    }

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

        // ----------------------------------
        // RESTORE SAVED CONTENT
        // ----------------------------------

        const initial = JSON.parse(
            $("initial-rich-delta").textContent
        );

        const plain = JSON.parse(
            $("initial-plain-answer").textContent
        );

        if (
            initial &&
            Array.isArray(initial.ops) &&
            initial.ops.length
        ) {

            
const updatedInitial = {
    ops: initial.ops.map(op => {
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

quill.setContents(
    updatedInitial,
    "silent"
);


        } else {

            quill.setText(
                plain || "",
                "silent"
            );

        }

    } catch (error) {

        console.error(
            "AssignHub Quill initialization:",
            error
        );

        show(
            "Editor initialization failed. See developer console.",
            "error"
        );

        return;
    }

    // ======================================
    // SERVER ATTEMPT STATE
    // ======================================

    let revision = Number(
        root.dataset.revision
    );

    let serverOffset = (
        Number(root.dataset.serverNow) * 1000
        - Date.now()
    );

    const expiresAt = (
        Number(root.dataset.expiry) * 1000
    );

    let busy = false;
    let locked = false;
    let saveFailed = false;
    let finalizedLocally = false;
    let lastRange = null;

    // ======================================
    // DOCUMENT STATE
    // ======================================

    function documentData() {
        return quill.getContents();
    }

    function fingerprint(data) {
        return JSON.stringify(
            data.ops || []
        );
    }

    let lastSaved = fingerprint(
        documentData()
    );

    function isDirty() {
        return (
            fingerprint(documentData())
            !== lastSaved
        );
    }

    // ======================================
    // WORD / CHARACTER COUNTS
    // ======================================

    function flatText() {

        // Each Quill embed occupies one index.
        // U+FFFC preserves index positions.

        return documentData().ops.map(
            op => (
                typeof op.insert === "string"
                    ? op.insert
                    : "\uFFFC"
            )
        ).join("");

    }

    function updateCounts() {

        const text = flatText().replace(
            /\n$/,
            ""
        );

        const words = (
            text
                .replace(
                    /\uFFFC/g,
                    " object "
                )
                .trim()
                .match(/\S+/g)
            || []
        );

        stats.textContent = (
            `${words.length} words · `
            + `${text.length} characters`
        );

    }

    // ======================================
    // SECURE SERVER TIMER
    // ======================================

    function serverNow() {
        return (
            Date.now() + serverOffset
        );
    }

    function remaining() {

        return Math.max(
            0,
            Math.ceil(
                (expiresAt - serverNow()) / 1000
            )
        );

    }

    function lock(message) {

        locked = true;

        quill.disable();

        saveButton.disabled = true;
        finishButton.disabled = true;

        document.querySelectorAll(
            "#writing-toolbar button, " +
            "#writing-toolbar select, " +
            ".ah-academic-toolbar button, " +
            ".ah-academic-toolbar select"
        ).forEach(
            el => {
                el.disabled = true;
            }
        );

        show(
            message,
            "error"
        );

    }

    function tick() {

        const seconds = remaining();

        const minutes = Math.floor(
            seconds / 60
        );

        const rest = seconds % 60;

        clock.textContent = (
            String(minutes).padStart(2, "0")
            + ":"
            + String(rest).padStart(2, "0")
        );

        clock.classList.toggle(
            "is-urgent",
            seconds <= 60
        );

        if (
            seconds === 0 &&
            !locked
        ) {

            lock(
                "Time expired. Server will finalize the last saved answer."
            );

            checkServer();

        }

    }

    // ======================================
    // SERVER STATUS CHECK
    // ======================================

    async function checkServer() {

        try {

            const response = await fetch(
                root.dataset.statusUrl,
                {
                    credentials: "same-origin",
                    cache: "no-store"
                }
            );

            if (!response.ok) {
                throw new Error(
                    "Status unavailable"
                );
            }

            const data = await response.json();

            serverOffset = (
                Number(data.server_now) * 1000
                - Date.now()
            );

            if (data.status !== "ACTIVE") {

                lock(
                    data.status === "SUBMITTED"
                        ? "Answer finalized. Refresh to view the saved submission."
                        : "Time expired without a saved answer."
                );

                return;
            }

            if (
                Number(data.revision) !== revision
                && !busy
            ) {

                lock(
                    "Another tab saved a different revision. Copy unsaved text before refreshing."
                );

            }

        } catch (error) {

            if (
                !locked &&
                !busy
            ) {

                show(
                    "Cannot verify server timer. Check connection.",
                    "error"
                );

            }

        }

    }

    // ======================================
    // CHECK ANSWER CONTENT
    // ======================================

    function hasAnswer() {

        return documentData().ops.some(
            op => {

                if (
                    typeof op.insert === "string"
                ) {
                    return Boolean(
                        op.insert.trim()
                    );
                }

                if (
                    !op.insert ||
                    typeof op.insert !== "object"
                ) {
                    return false;
                }

                if (
                    typeof op.insert.formula === "string"
                ) {
                    return true;
                }

                if (op.insert.shape) {

                    return Boolean(
                        op.insert.shape.label &&
                        op.insert.shape.label.trim()
                    );

                }

                if (op.insert.ahTable || op.insert.table) {

                    const table = (
    op.insert.ahTable ||
    op.insert.table
);

return (table.rows || []).some(
    row => row.some(
        cell => String(cell).trim()
    )
);

                }

                return false;

            }
        );

    }

    // ======================================
    // AUTOSAVE / FINAL SUBMISSION
    // ======================================

    async function save(action = "save") {

        if (
            busy ||
            locked
        ) {
            return false;
        }

        if (
            action === "save" &&
            !isDirty()
        ) {

            if (!saveFailed) {
                show(
                    "All changes saved",
                    "saved"
                );
            }

            return true;
        }

        if (
            action === "finish" &&
            !hasAnswer()
        ) {

            show(
                "Write an answer before submitting.",
                "error"
            );

            return false;
        }

        if (remaining() <= 0) {
            tick();
            return false;
        }

        busy = true;

        saveButton.disabled = true;
        finishButton.disabled = true;

        show(
            action === "finish"
                ? "Submitting final answer..."
                : "Saving...",
            "pending"
        );

        const snapshot = documentData();

        const snapshotHash = fingerprint(
            snapshot
        );

        try {

            const response = await fetch(
                root.dataset.saveUrl,
                {
                    method: "POST",
                    credentials: "same-origin",
                    cache: "no-store",

                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrf
                    },

                    body: JSON.stringify({
                        answer: quill.getText(),
                        delta: snapshot,
                        revision,
                        action
                    })
                }
            );

            const data = await response.json();

            if (!response.ok) {

                saveFailed = true;

                if (
                    response.status === 409 ||
                    (
                        data.status &&
                        data.status !== "ACTIVE"
                    )
                ) {

                    lock(
                        "Attempt closed or another tab saved. Copy any unsaved text before refreshing."
                    );

                } else {

                    show(
                        data.error ||
                        "Save failed. Retry.",
                        "error"
                    );

                }

                return false;
            }

            revision = Number(
                data.revision
            );

            lastSaved = snapshotHash;

            saveFailed = false;

            if (
                Number.isFinite(
                    Number(data.server_now)
                )
            ) {

                serverOffset = (
                    Number(data.server_now) * 1000
                    - Date.now()
                );

            }

            if (data.status !== "ACTIVE") {

                locked = true;
                finalizedLocally = true;

                quill.disable();

                show(
                    "Final answer submitted successfully.",
                    "saved"
                );

                window.location.reload();

                return true;
            }

            show(
                isDirty()
                    ? "New changes pending"
                    : "Saved to server",

                isDirty()
                    ? "pending"
                    : "saved"
            );

            return true;

        } catch (error) {

            saveFailed = true;

            show(
                "Connection error — latest changes NOT saved.",
                "error"
            );

            return false;

        } finally {

            busy = false;

            if (!locked) {
                saveButton.disabled = false;
                finishButton.disabled = false;
            }

        }

    }

    // ======================================
    // SELECTION TRACKING
    // ======================================

    quill.on(
        "selection-change",
        range => {
            if (range) {
                lastRange = range;
            }
        }
    );

    quill.on(
        "text-change",
        (delta, old, source) => {

            updateCounts();

            if (
                !locked &&
                source !== "silent"
            ) {

                show(
                    "Unsaved changes",
                    "pending"
                );

            }

        }
    );

    function selection() {

        return (
            quill.getSelection()
            || lastRange
            || {
                index: Math.max(
                    0,
                    quill.getLength() - 1
                ),
                length: 0
            }
        );

    }

    // ======================================
    // INSERT PLAIN TEXT
    // ======================================

    function insertText(value) {

        if (
            locked ||
            !value
        ) {
            return;
        }

        const range = selection();

        if (range.length) {

            quill.deleteText(
                range.index,
                range.length,
                "user"
            );

        }

        quill.insertText(
            range.index,
            value,
            "user"
        );

        quill.setSelection(
            range.index + value.length,
            0,
            "silent"
        );

        quill.focus();

    }

    // ======================================
    // INSERT QUILL EMBED
    // ======================================

    
function insertEmbed(type, payload) {
    if (locked) {
        return false;
    }

    const permittedTypes = new Set([
        "formula",
        "shape",
        "ahTable",
        "ahRule"
    ]);

    if (!permittedTypes.has(type)) {
        show(
            "Unsupported document object.",
            "error"
        );
        return false;
    }

    const range = selection();

    const index = Math.min(
        Math.max(0, range.index),
        Math.max(0, quill.getLength() - 1)
    );

    try {
        if (range.length > 0) {
            quill.deleteText(
                index,
                range.length,
                "user"
            );
        }

        // Quill stores embeds as Delta objects.
        // Every embed has length 1.
        quill.insertEmbed(
            index,
            type,
            payload,
            "user"
        );

        quill.update("user");

        const exists = quill.getContents().ops.some(
            op => (
                op.insert &&
                typeof op.insert === "object" &&
                Object.prototype.hasOwnProperty.call(
                    op.insert,
                    type
                )
            )
        );

        if (!exists) {
            show(
                "Object could not be inserted. Check editor registration.",
                "error"
            );

            return false;
        }

        quill.setSelection(
            Math.min(
                index + 1,
                Math.max(0, quill.getLength() - 1)
            ),
            0,
            "silent"
        );

        quill.focus();

        updateCounts();

        show(
            "Object inserted — unsaved changes",
            "pending"
        );

        return true;

    } catch (error) {
        console.error(
            "AssignHub embed insertion failed:",
            error
        );

        show(
            "Could not insert object. Check browser console.",
            "error"
        );

        return false;
    }
}


    // ======================================
    // PLAIN-TEXT PASTE
    // ======================================

    quill.root.addEventListener(
        "paste",
        event => {

            if (
                locked ||
                !event.clipboardData
            ) {
                return;
            }

            const text = event.clipboardData.getData(
                "text/plain"
            );

            event.preventDefault();

            insertText(
                text.replace(
                    /\r\n?/g,
                    "\n"
                )
            );

        }
    );

    $("ah-clean-paste").addEventListener(
        "click",
        async () => {

            if (locked) {
                return;
            }

            try {

                const text = await navigator.clipboard.readText();

                insertText(text);

            } catch (error) {

                show(
                    "Clipboard access denied. Use Ctrl+V (plain-text paste).",
                    "error"
                );

            }

        }
    );

    // ======================================
    // UNDO / REDO
    // ======================================

    $("ah-undo").addEventListener(
        "click",
        () => {

            if (!locked) {
                quill.getModule("history").undo();
            }

        }
    );

    $("ah-redo").addEventListener(
        "click",
        () => {

            if (!locked) {
                quill.getModule("history").redo();
            }

        }
    );

    // ======================================
    // LINE SPACING
    // ======================================

    $("ah-line-height").addEventListener(
        "change",
        event => {

            if (locked) {
                return;
            }

            const range = selection();

            quill.formatLine(
                range.index,
                Math.max(
                    1,
                    range.length
                ),
                "lineheight",
                event.target.value,
                "user"
            );

            quill.focus();

        }
    );

    // ======================================
    // INSERT SPECIAL SYMBOL
    // ======================================

    $("insert-symbol").addEventListener(
        "click",
        () => {

            insertText(
                $("math-symbol").value
            );

            $("math-symbol").value = "";

        }
    );

    // ======================================
    // MATHEMATICAL EQUATIONS
    // ======================================

    function insertEquation(value) {

        if (
            locked ||
            !value
        ) {
            return;
        }

        if (
            value.length > 2000 ||
            /\\(?:href|url|html\w*|includegraphics)\b/i.test(value)
        ) {

            show(
                "Equation is too long or contains a prohibited command.",
                "error"
            );

            return;
        }

        try {

            window.katex.renderToString(
                value,
                {
                    throwOnError: true,
                    trust: false
                }
            );

            insertEmbed(
                "formula",
                value
            );

        } catch (error) {

            show(
                "Invalid LaTeX equation. Check its syntax.",
                "error"
            );

        }

    }

    $("insert-equation").addEventListener(
        "click",
        () => {

            insertEquation(
                $("math-preset").value
            );

            $("math-preset").value = "";

        }
    );

    $("custom-equation").addEventListener(
        "click",
        () => {

            if (locked) {
                return;
            }

            const value = window.prompt(
                "Enter a LaTeX equation",
                "\\frac{a}{b}"
            );

            if (value !== null) {
                insertEquation(
                    value.trim()
                );
            }

        }
    );

    // ======================================
    // SHAPES / RULE
    // ======================================

    $("insert-shape").addEventListener(
        "click",
        () => {

            if (locked) {
                return;
            }

            const text = window.prompt(
                "Shape label (optional)",
                ""
            );

            if (text === null) {
                return;
            }

            insertEmbed(
                "shape",
                {
                    kind: $("shape-kind").value,
                    label: text.slice(0, 80)
                }
            );

        }
    );

$("ah-insert-rule").addEventListener(
    "click",
    () => {
        insertEmbed("ahRule", true);
    }
);

    // ======================================
    // TABLE EDITING
    // ======================================

    const tableModalElement = $("ahTableModal");

    const tableModal = bootstrap.Modal.getOrCreateInstance(
        tableModalElement
    );

    const tableGrid = $("ah-table-grid");

    let currentTableIndex = null;

    let tableCells = [
        ["", ""],
        ["", ""]
    ];

    function readGrid() {

        const inputs = tableGrid.querySelectorAll(
            "input[data-row][data-col]"
        );

        inputs.forEach(input => {

            const row = Number(
                input.dataset.row
            );

            const col = Number(
                input.dataset.col
            );

            tableCells[row][col] = (
                input.value.slice(0, 400)
            );

        });

    }

    function renderGrid() {

        tableGrid.replaceChildren();

        const table = document.createElement(
            "table"
        );

        table.className = (
            "table table-bordered ah-table-entry"
        );

        const tbody = document.createElement(
            "tbody"
        );

        tableCells.forEach(
            (row, rowIndex) => {

                const tr = document.createElement(
                    "tr"
                );

                row.forEach(
                    (cell, colIndex) => {

                        const td = document.createElement(
                            "td"
                        );

                        const input = document.createElement(
                            "input"
                        );

                        input.type = "text";

                        input.className = (
                            "form-control form-control-sm"
                        );

                        input.maxLength = 400;

                        input.value = cell;

                        input.dataset.row = rowIndex;
                        input.dataset.col = colIndex;

                        input.setAttribute(
                            "aria-label",
                            `Row ${rowIndex + 1}, column ${colIndex + 1}`
                        );

                        td.appendChild(input);

                        tr.appendChild(td);

                    }
                );

                tbody.appendChild(tr);

            }
        );

        table.appendChild(tbody);

        tableGrid.appendChild(table);

    }

    function openTable(
        index = null,
        values = null
    ) {

        if (locked) {
            return;
        }

        currentTableIndex = index;

        tableCells = (
            values &&
            Array.isArray(values.rows)
        )
            ? values.rows.map(
                row => [...row]
            )
            : [
                ["", ""],
                ["", ""]
            ];

        renderGrid();

        tableModal.show();

    }

    $("ah-insert-table").addEventListener(
        "click",
        () => openTable()
    );

    // Click existing table to edit.

    quill.root.addEventListener(
        "click",
        event => {

            const node = event.target.closest(
                ".ah-table-embed"
            );

            if (
                !node ||
                locked
            ) {
                return;
            }

            const blot = Quill.find(node);

            if (!blot) {
                return;
            }

            openTable(
                quill.getIndex(blot),
                window.AssignHubTableBlot.value(node)
            );

        }
    );

    // Keyboard access for tables.

    quill.root.addEventListener(
        "keydown",
        event => {

            if (
                event.key !== "Enter" &&
                event.key !== " "
            ) {
                return;
            }

            const node = event.target.closest(
                ".ah-table-embed"
            );

            if (
                !node ||
                locked
            ) {
                return;
            }

            event.preventDefault();

            const blot = Quill.find(node);

            if (blot) {

                openTable(
                    quill.getIndex(blot),
                    window.AssignHubTableBlot.value(node)
                );

            }

        }
    );

    // --------------------------------------
    // TABLE ROW ACTIONS
    // --------------------------------------

    $("ah-table-row-add").addEventListener(
        "click",
        () => {

            readGrid();

            if (tableCells.length < 10) {

                tableCells.push(
                    Array(
                        tableCells[0].length
                    ).fill("")
                );

            }

            renderGrid();

        }
    );

    $("ah-table-row-remove").addEventListener(
        "click",
        () => {

            readGrid();

            if (tableCells.length > 1) {
                tableCells.pop();
            }

            renderGrid();

        }
    );

    // --------------------------------------
    // TABLE COLUMN ACTIONS
    // --------------------------------------

    $("ah-table-col-add").addEventListener(
        "click",
        () => {

            readGrid();

            if (
                tableCells[0].length < 8
            ) {

                tableCells.forEach(
                    row => row.push("")
                );

            }

            renderGrid();

        }
    );

    $("ah-table-col-remove").addEventListener(
        "click",
        () => {

            readGrid();

            if (
                tableCells[0].length > 1
            ) {

                tableCells.forEach(
                    row => row.pop()
                );

            }

            renderGrid();

        }
    );

    // --------------------------------------
    // SAVE TABLE TO QUILL
    // --------------------------------------

    
$("ah-table-apply").addEventListener(
    "click",
    () => {
        if (locked) {
            return;
        }

        readGrid();

        const payload = {
            rows: tableCells.map(
                row => row.map(
                    cell => String(cell).slice(0, 400)
                )
            )
        };

        let inserted = false;

        try {
            if (currentTableIndex !== null) {
                // Replace the existing table embed.
                // Block embeds have Delta length 1.
                const index = currentTableIndex;

                quill.deleteText(
                    index,
                    1,
                    "user"
                );

                quill.insertEmbed(
                    index,
                    "ahTable",
                    payload,
                    "user"
                );

                quill.update("user");

                inserted = true;

            } else {
                // Insert a new table at cursor position.
                inserted = insertEmbed(
                    "ahTable",
                    payload
                );
            }

            if (inserted) {
                tableModal.hide();

                show(
                    "Table inserted — awaiting autosave",
                    "pending"
                );
            }

        } catch (error) {
            console.error(
                "AssignHub table insertion failed:",
                error
            );

            show(
                "Unable to insert table.",
                "error"
            );
        }
    }
);

    // ======================================
    // FIND AND REPLACE
    // ======================================

    const findPanel = $("ah-find-panel");
    const findBox = $("ah-find-text");
    const replaceBox = $("ah-replace-text");
    const findInfo = $("ah-find-info");

    let findIndex = -1;

    function searchFrom(startIndex) {

        const needle = findBox.value;

        if (!needle) {

            findInfo.textContent = (
                "Enter search text"
            );

            return -1;
        }

        const text = flatText()
            .toLocaleLowerCase();

        const query = needle
            .toLocaleLowerCase();

        let at = text.indexOf(
            query,
            Math.max(
                0,
                startIndex
            )
        );

        if (at < 0) {

            at = text.indexOf(query);

        }

        if (at < 0) {

            findInfo.textContent = (
                "No matches"
            );

            return -1;
        }

        findInfo.textContent = (
            `Match at character ${at + 1}`
        );

        quill.setSelection(
            at,
            needle.length,
            "user"
        );

        quill.focus();

        findIndex = at;

        return at;

    }

    $("ah-toggle-find").addEventListener(
        "click",
        () => {

            findPanel.hidden = (
                !findPanel.hidden
            );

            if (!findPanel.hidden) {
                findBox.focus();
            }

        }
    );

    $("ah-close-find").addEventListener(
        "click",
        () => {
            findPanel.hidden = true;
        }
    );

    findBox.addEventListener(
        "input",
        () => {
            findIndex = -1;
        }
    );

    $("ah-find-next").addEventListener(
        "click",
        () => searchFrom(
            findIndex + 1
        )
    );

    // --------------------------------------
    // REPLACE ONE
    // --------------------------------------

    $("ah-replace-one").addEventListener(
        "click",
        () => {

            if (
                locked ||
                !findBox.value
            ) {
                return;
            }

            let at = findIndex;

            if (
                at < 0 ||
                flatText()
                    .slice(
                        at,
                        at + findBox.value.length
                    )
                    .toLowerCase()
                !== findBox.value.toLowerCase()
            ) {

                at = searchFrom(0);

            }

            if (at < 0) {
                return;
            }

            quill.deleteText(
                at,
                findBox.value.length,
                "user"
            );

            quill.insertText(
                at,
                replaceBox.value,
                "user"
            );

            findIndex = (
                at + replaceBox.value.length
            );

            searchFrom(findIndex);

        }
    );

    // --------------------------------------
    // REPLACE ALL
    // --------------------------------------

    $("ah-replace-all").addEventListener(
        "click",
        () => {

            if (
                locked ||
                !findBox.value
            ) {
                return;
            }

            const text = flatText()
                .toLowerCase();

            const needle = findBox.value
                .toLowerCase();

            const locations = [];

            let at = 0;

            while (
                (
                    at = text.indexOf(
                        needle,
                        at
                    )
                ) !== -1 &&
                locations.length < 1000
            ) {

                locations.push(at);

                at += needle.length;

            }

            locations.reverse().forEach(
                index => {

                    quill.deleteText(
                        index,
                        findBox.value.length,
                        "user"
                    );

                    quill.insertText(
                        index,
                        replaceBox.value,
                        "user"
                    );

                }
            );

            findIndex = -1;

            findInfo.textContent = (
                `${locations.length} replacements`
            );

        }
    );

    // ======================================
    // FIND SHORTCUTS
    // ======================================

    document.addEventListener(
        "keydown",
        event => {

            if (
                locked ||
                !(
                    event.ctrlKey ||
                    event.metaKey
                )
            ) {
                return;
            }

            const active = document.activeElement;

            const typingInEditor = (
                quill.root.contains(active)
            );

            if (!typingInEditor) {
                return;
            }

            if (
                ["f", "h"].includes(
                    event.key.toLowerCase()
                )
            ) {

                event.preventDefault();

                findPanel.hidden = false;

                findBox.focus();

            }

        }
    );

    // ======================================
    // FINAL SUBMISSION MODAL
    // ======================================

    function confirmation() {

        return new Promise(
            resolve => {

                const element = $("finalSubmitModal");

                const button = $("finalSubmitConfirmBtn");

                const modal = bootstrap.Modal.getOrCreateInstance(
                    element
                );

                let agreed = false;

                function onConfirm() {

                    agreed = (
                        !locked &&
                        !busy &&
                        remaining() > 0
                    );

                    modal.hide();

                }

                function onHidden() {

                    button.removeEventListener(
                        "click",
                        onConfirm
                    );

                    element.removeEventListener(
                        "hidden.bs.modal",
                        onHidden
                    );

                    resolve(agreed);

                }

                button.addEventListener(
                    "click",
                    onConfirm
                );

                element.addEventListener(
                    "hidden.bs.modal",
                    onHidden,
                    {
                        once: true
                    }
                );

                modal.show();

            }
        );

    }

    // ======================================
    // SAVE BUTTON
    // ======================================

    saveButton.addEventListener(
        "click",
        () => save("save")
    );

    // ======================================
    // FINAL SUBMIT BUTTON
    // ======================================

    finishButton.addEventListener(
        "click",
        async () => {

            if (
                locked ||
                busy
            ) {
                return;
            }

            if (!hasAnswer()) {

                show(
                    "Write an answer before submitting.",
                    "error"
                );

                return;
            }

            if (
                await confirmation()
            ) {

                await save("finish");

            }

        }
    );

    // ======================================
    // UNSAVED CHANGES WARNING
    // ======================================

    window.addEventListener(
        "beforeunload",
        event => {

            if (
                !finalizedLocally &&
                (
                    busy ||
                    isDirty() ||
                    saveFailed
                )
            ) {

                event.preventDefault();

                event.returnValue = "";

            }

        }
    );

    // ======================================
    // EDITOR STARTUP
    // ======================================

    updateCounts();

    saveButton.disabled = false;
    finishButton.disabled = false;

    show(
        "Editor ready — saved draft loaded",
        "saved"
    );

    tick();

    // Update timer every second.
    setInterval(
        tick,
        1000
    );

    // Autosave every 4 seconds.
    setInterval(
        () => {

            if (
                !locked &&
                !busy &&
                isDirty()
            ) {

                save("save");

            }

        },
        4000
    );

    // Save more frequently near deadline.
    setInterval(
        () => {

            if (
                !locked &&
                !busy &&
                remaining() <= 15 &&
                isDirty()
            ) {

                save("save");

            }

        },
        1000
    );

    // Save when leaving active browser tab.
    document.addEventListener(
        "visibilitychange",
        () => {

            if (
                document.hidden &&
                !locked &&
                !busy &&
                isDirty()
            ) {

                save("save");

            }

        }
    );

    // Verify server state periodically.
    setInterval(
        checkServer,
        10000
    );

})();
